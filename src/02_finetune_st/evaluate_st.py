"""
evaluate_st.py — Évaluation comparative baseline vs fine-tuné
"""
import argparse, json, logging, time
from pathlib import Path
from sentence_transformers import SentenceTransformer
from sentence_transformers.sentence_transformer.evaluation import InformationRetrievalEvaluator, EmbeddingSimilarityEvaluator, SequentialEvaluator

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")

ROOT      = Path(__file__).resolve().parent.parent.parent
DATA_FT   = ROOT / "data" / "finetune"
MODEL_DIR = ROOT / "models" / "st_finetuned"
EVAL_DIR  = MODEL_DIR / "eval_comparatif"

with open(Path(__file__).parent / "config_st.json") as f:
    CFG = json.load(f)


def load_jsonl(p):
    with open(p, encoding="utf-8") as f: return [json.loads(l) for l in f]

def build_evaluators(pairs, prefix):
    queries, corpus, relevant = {}, {}, {}
    for p in pairs:
        qid = p["offre_id"]
        queries[qid]  = p["sentence1"]
        corpus[qid]   = p["sentence2"]
        relevant[qid] = {qid}
    ir = InformationRetrievalEvaluator(
        queries=queries, corpus=corpus, relevant_docs=relevant,
        mrr_at_k=[1,5,10], ndcg_at_k=[1,5,10],
        precision_recall_at_k=[1,5,10],
        name=f"{prefix}-ir", show_progress_bar=True,
    )
    sim = EmbeddingSimilarityEvaluator(
        sentences1=[p["sentence1"] for p in pairs],
        sentences2=[p["sentence2"] for p in pairs],
        scores=[1.0]*len(pairs),
        name=f"{prefix}-sim", show_progress_bar=False,
    )
    return SequentialEvaluator([sim, ir]), ir

def evaluate_one(model, evaluator, label):
    log.info(f"\n--- {label} ---")
    t0 = time.time()
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    res = evaluator(model, output_path=str(EVAL_DIR))
    log.info(f"  Temps : {time.time()-t0:.1f}s")
    return res

def print_comparison(base, ft, pairs_n):
    KEYS = [
        "test-ir_cosine_ndcg@10", "test-ir_cosine_mrr@10",
        "test-ir_cosine_recall@1", "test-ir_cosine_recall@5",
        "test-ir_cosine_recall@10", "test-ir_cosine_precision@1",
    ]
    log.info("\n" + "="*70)
    log.info(f"COMPARAISON sur {pairs_n} paires de test")
    log.info(f"{'Metrique':<48} {'Base':>8} {'FT':>8} {'Delta':>8}")
    log.info("-"*70)
    rapport = {}
    seuils = {"ndcg@10":CFG["seuils_cibles"].get("ndcg_at_10"),
              "mrr@10": CFG["seuils_cibles"].get("mrr_at_10"),
              "recall@5":CFG["seuils_cibles"].get("recall_at_5"),
              "recall@10":CFG["seuils_cibles"].get("recall_at_10")}
    for k in KEYS:
        b = base.get(k, 0.0); f = ft.get(k, 0.0)
        d = f - b
        short = k.split("@")[-2].split("_")[-1]+"@"+k.split("@")[-1]
        s = seuils.get(short)
        flag = "✓" if s and f>=s else ("✗" if s else " ")
        log.info(f"  {flag} {k:<46} {b:>7.4f} {f:>7.4f} {d:>+7.4f}")
        rapport[k] = {"baseline":round(b,4),"finetuned":round(f,4),"delta":round(d,4)}
    return rapport

def run(ft_path=None, no_baseline=False):
    test_pairs = load_jsonl(DATA_FT / "pairs_test.jsonl")
    log.info(f"Test : {len(test_pairs)} paires")

    seq_eval_ft, ir_eval_ft = build_evaluators(test_pairs, "test")
    ft_path = ft_path or str(MODEL_DIR / "final")

    log.info(f"Chargement fine-tuné : {ft_path}")
    model_ft = SentenceTransformer(ft_path)
    ft_res = evaluate_one(model_ft, ir_eval_ft, "FINE-TUNÉ")

    base_res = {}
    if not no_baseline:
        log.info(f"Chargement baseline : {CFG['modele_base']}")
        model_base = SentenceTransformer(CFG["modele_base"])
        base_res = evaluate_one(model_base, ir_eval_ft, "BASELINE")

    rapport = print_comparison(base_res, ft_res, len(test_pairs))
    out = EVAL_DIR / "evaluation_comparatif.json"
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(out,"w") as f: json.dump(rapport, f, indent=2)
    log.info(f"Rapport -> {out}")
    return rapport

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model-ft", default=None)
    p.add_argument("--no-baseline", action="store_true")
    args = p.parse_args()
    run(ft_path=args.model_ft, no_baseline=args.no_baseline)

if __name__ == "__main__": main()
