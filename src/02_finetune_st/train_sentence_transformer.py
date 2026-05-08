"""
train_sentence_transformer.py
===========================================================================
Module 02 — Fine-tuning du SentenceTransformer
API : sentence-transformers >= 3.0 (Trainer-based, version 5.x)

Tâche : apprendre a rapprocher les métadonnées structurées d'une offre
        et sa description textuelle dans le même espace vectoriel 384d.

Exécution :
    python train_sentence_transformer.py
    python train_sentence_transformer.py --epochs 3 --batch 16
    python train_sentence_transformer.py --eval-only --model ./models/st_finetuned/final

Dépendances :
    pip install sentence-transformers>=3.0 datasets torch accelerate
===========================================================================
"""

import argparse
import json
import logging
import time
from pathlib import Path

import torch
from sentence_transformers import (
    SentenceTransformer,
    SentenceTransformerTrainer,
    SentenceTransformerTrainingArguments,
    util,
)
from sentence_transformers.sentence_transformer.losses import MultipleNegativesRankingLoss
from sentence_transformers.sentence_transformer.evaluation import InformationRetrievalEvaluator
from datasets import Dataset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
for noisy_logger in (
    "httpx",
    "httpcore",
    "huggingface_hub",
    "huggingface_hub.utils",
    "huggingface_hub.utils._http",
):
    logging.getLogger(noisy_logger).setLevel(logging.ERROR)
log = logging.getLogger(__name__)


ROOT      = Path(__file__).resolve().parent.parent.parent
DATA_FT   = ROOT / "data" / "finetune"
MODEL_DIR = ROOT / "models" / "st_finetuned"
CFG_PATH  = Path(__file__).parent / "config_st.json"

with open(CFG_PATH) as f:
    CFG = json.load(f)

SIMILARITY_FUNCTIONS = {
    "cosine": util.cos_sim,
    "dot": util.dot_score,
}


def load_jsonl(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def to_hf_dataset(pairs: list) -> Dataset:
    """
    Format requis par SentenceTransformerTrainer + MNRL :
        {"anchor": sentence1, "positive": sentence2}
    anchor   = metadata structuree (cote requete / candidat)
    positive = skills + details annonce (cote corpus / offre)
    """
    return Dataset.from_dict({
        "anchor":   [p["sentence1"] for p in pairs],
        "positive": [p["sentence2"] for p in pairs],
    })


def build_evaluators(val_pairs: list, test_pairs: list):
    """
    Construit les evaluateurs de retrieval.

    On n'utilise pas EmbeddingSimilarityEvaluator ici : toutes les paires sont
    positives, donc les labels seraient constants (=1.0) et Pearson/Spearman
    seraient mathematiquement indefinis.
    """
    # --- InformationRetrievalEvaluator (val) ---
    queries, corpus, relevant = {}, {}, {}
    for p in val_pairs:
        qid = p["offre_id"]
        queries[qid]  = p["sentence1"]
        corpus[qid]   = p["sentence2"]
        relevant[qid] = {qid}

    ir_eval = InformationRetrievalEvaluator(
        queries=queries,
        corpus=corpus,
        relevant_docs=relevant,
        mrr_at_k=[1, 5, 10],
        ndcg_at_k=[1, 5, 10],
        precision_recall_at_k=[1, 5, 10],
        name="val-information-retrieval",
        show_progress_bar=True,
    )

    # --- InformationRetrievalEvaluator (test) ---
    queries_t, corpus_t, relevant_t = {}, {}, {}
    for p in test_pairs:
        qid = p["offre_id"]
        queries_t[qid]  = p["sentence1"]
        corpus_t[qid]   = p["sentence2"]
        relevant_t[qid] = {qid}

    test_eval = InformationRetrievalEvaluator(
        queries=queries_t,
        corpus=corpus_t,
        relevant_docs=relevant_t,
        mrr_at_k=[1, 5, 10],
        ndcg_at_k=[1, 5, 10],
        precision_recall_at_k=[1, 5, 10],
        name="test-information-retrieval",
        show_progress_bar=True,
    )

    return ir_eval, test_eval


def train(epochs=None, batch=None, lr=None, eval_only=False, model_path=None, online=False):
    cfg_t = CFG["entrainement"]
    num_epochs    = epochs or int(cfg_t["num_epochs"])
    batch_size    = batch  or int(cfg_t["batch_size"])
    learning_rate = lr     or float(cfg_t["learning_rate"])

    log.info("=" * 65)
    log.info("MODULE 02 — FINE-TUNING SENTENCETRANSFORMER")
    log.info("=" * 65)
    log.info(f"  Modele base  : {CFG['modele_base']}")
    log.info(f"  Epochs       : {num_epochs}")
    log.info(f"  Batch size   : {batch_size} ({batch_size-1} négatifs/exemple)")
    log.info(f"  LR           : {learning_rate}")
    log.info(f"  Perte        : MultipleNegativesRankingLoss")

    train_pairs = load_jsonl(DATA_FT / "pairs_train.jsonl")
    val_pairs   = load_jsonl(DATA_FT / "pairs_val.jsonl")
    test_pairs  = load_jsonl(DATA_FT / "pairs_test.jsonl")
    log.info(f"\n  Train : {len(train_pairs):,} paires")
    log.info(f"  Val   : {len(val_pairs):,} paires")
    log.info(f"  Test  : {len(test_pairs):,} paires")

    train_dataset = to_hf_dataset(train_pairs)

    # Chargement du modele
    src = model_path if (eval_only and model_path) else CFG["modele_base"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info(f"\nChargement : {src}")
    log.info(f"  Device       : {device}")
    log.info(f"  HF local     : {not online}")
    model = SentenceTransformer(src, device=device, local_files_only=not online)
    n = sum(p.numel() for p in model.parameters())
    log.info(f"  Parametres : {n:,}")

    seq_evaluator, test_evaluator = build_evaluators(val_pairs, test_pairs)

    if eval_only:
        log.info("\n[EVAL ONLY] Evaluation directe...")
        results = test_evaluator(model)
        log.info(f"Résultats : {results}")
        return results

    # Fonction de perte
    similarity_name = CFG["perte"].get("similarite", "cosine")
    if similarity_name not in SIMILARITY_FUNCTIONS:
        raise ValueError(
            f"Similarite inconnue: {similarity_name!r}. "
            f"Valeurs supportees: {sorted(SIMILARITY_FUNCTIONS)}"
        )

    train_loss = MultipleNegativesRankingLoss(
        model=model,
        scale=CFG["perte"]["scale"],
        similarity_fct=SIMILARITY_FUNCTIONS[similarity_name],
    )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    steps_per_epoch = max(1, len(train_pairs) // batch_size)
    warmup = min(int(cfg_t["warmup_steps"]), steps_per_epoch)

    training_args = SentenceTransformerTrainingArguments(
        output_dir=str(MODEL_DIR / "checkpoints"),
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        warmup_steps=warmup,
        learning_rate=learning_rate,
        lr_scheduler_type="cosine",
        weight_decay=float(cfg_t["weight_decay"]),
        max_grad_norm=float(cfg_t["max_grad_norm"]),
        fp16=False,
        bf16=False,
        batch_sampler="no_duplicates",
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="val-information-retrieval_cosine_ndcg@10",
        greater_is_better=True,
        dataloader_pin_memory=torch.cuda.is_available(),
        logging_steps=max(1, steps_per_epoch // 5),
        report_to="none",
        seed=int(cfg_t["seed"]),
    )

    log.info(f"\n  Steps/epoch : {steps_per_epoch}")
    log.info(f"  Warmup      : {warmup} steps")
    log.info(f"  Total       : {steps_per_epoch * num_epochs} steps")

    trainer = SentenceTransformerTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        loss=train_loss,
        evaluator=seq_evaluator,
    )

    log.info("\n" + "=" * 65)
    log.info("DÉMARRAGE DE L'ENTRAÎNEMENT")
    log.info("=" * 65)
    t0 = time.time()
    trainer.train()
    elapsed = time.time() - t0
    log.info(f"\n✓ Terminé en {elapsed/60:.1f} minutes")

    # Sauvegarde
    final_path = MODEL_DIR / "final"
    model.save(str(final_path))
    log.info(f"Modele sauvegardé → {final_path}")

    # Evaluation finale sur test
    log.info("\nEvaluation finale — jeu TEST...")
    test_results = test_evaluator(model, output_path=str(MODEL_DIR / "eval_test"))

    # Sauvegarde métriques
    with open(MODEL_DIR / "evaluation_metrics.json", "w") as f:
        json.dump({
            "train_time_s":   round(elapsed, 1),
            "num_epochs":     num_epochs,
            "batch_size":     batch_size,
            "learning_rate":  learning_rate,
            "n_train":        len(train_pairs),
            "n_val":          len(val_pairs),
            "n_test":         len(test_pairs),
            "test_results":   {k: round(v, 4) if isinstance(v, float) else v
                               for k, v in test_results.items()},
            "training_logs":  trainer.state.log_history,
        }, f, ensure_ascii=False, indent=2)

    log.info("\n" + "=" * 65)
    log.info("RÉSULTATS TEST")
    log.info("=" * 65)
    seuils = CFG["seuils_cibles"]
    for key, val in sorted(test_results.items()):
        if not isinstance(val, float): continue
        k_short = key.split("_")[-1]
        s = seuils.get(k_short)
        flag = "✓" if s and val >= s else ("✗" if s else " ")
        log.info(f"  {flag}  {key:<50} = {val:.4f}")

    return test_results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs",    type=int,   default=None)
    parser.add_argument("--batch",     type=int,   default=None)
    parser.add_argument("--lr",        type=float, default=None)
    parser.add_argument("--eval-only", action="store_true")
    parser.add_argument("--model",     type=str,   default=None)
    parser.add_argument(
        "--online",
        action="store_true",
        help="Autorise les requetes Hugging Face. Par defaut, le modele est charge depuis le cache local.",
    )
    args = parser.parse_args()
    train(epochs=args.epochs, batch=args.batch, lr=args.lr,
          eval_only=args.eval_only, model_path=args.model, online=args.online)


if __name__ == "__main__":
    main()
