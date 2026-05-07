"""
build_pairs.py — Construction des paires (metadata → description) pour le fine-tuning ST

Logique :
  - sentence1 = métadonnées structurées de l'offre (côté requête)
  - sentence2 = skills_raw + details_clean de l'offre (côté corpus)
  - Ne retenir que les paires où les deux côtés ont assez de contenu
  - Split stratifié par secteur_principal (70/15/15)
  - Sauvegarder en JSONL format InputExample sentence-transformers
"""

import sys
import json
import logging
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    OFFRES_PROC, PAIRS_TRAIN, PAIRS_VAL, PAIRS_TEST, PAIRS_META,
    DATA_FT, FT_TRAIN_RATIO, FT_VAL_RATIO, FT_RANDOM_SEED,
)
from utils import log

MIN_SENTENCE1_LEN = 20   # chars minimum côté metadata
MIN_SENTENCE2_LEN = 50   # chars minimum côté description


def load_offres_processed() -> pd.DataFrame:
    log.info(f"Chargement offres processed : {OFFRES_PROC}")
    df = pd.read_parquet(OFFRES_PROC)
    log.info(f"  → {len(df)} offres")
    return df


def build_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """
    Construit les paires à partir du DataFrame offres normalisé.
    Filtre sur ft_eligible et longueurs minimales.
    """
    # Ne garder que les paires éligibles
    df_ft = df[df["ft_eligible"] == True].copy()
    log.info(f"  Paires éligibles (ft_eligible=True) : {len(df_ft)}")

    # Vérifier longueurs
    df_ft = df_ft[
        (df_ft["metadata_str"].str.len() >= MIN_SENTENCE1_LEN) &
        (df_ft["text_to_embed"].str.len() >= MIN_SENTENCE2_LEN)
    ].copy()
    log.info(f"  Après filtre longueur : {len(df_ft)}")

    # Créer les colonnes de paires
    df_ft["sentence1"] = df_ft["metadata_str"]    # côté requête
    df_ft["sentence2"] = df_ft["text_to_embed"]   # côté corpus

    return df_ft[["offre_id", "sentence1", "sentence2", "secteur_principal",
                   "titre_poste", "ville_principale"]]


def stratified_split(df: pd.DataFrame, seed: int = FT_RANDOM_SEED) -> tuple:
    """
    Split stratifié sur 'secteur_principal' pour équilibrer les domaines
    entre train, val et test.
    """
    rng = np.random.default_rng(seed)

    train_rows, val_rows, test_rows = [], [], []

    # Grouper par secteur
    for secteur, group in df.groupby("secteur_principal", dropna=False):
        idx = group.index.tolist()
        rng.shuffle(idx)

        n = len(idx)
        n_train = max(1, round(n * FT_TRAIN_RATIO))
        n_val   = max(1, round(n * FT_VAL_RATIO))

        train_rows.extend(idx[:n_train])
        val_rows.extend(idx[n_train:n_train + n_val])
        test_rows.extend(idx[n_train + n_val:])

    train = df.loc[train_rows].reset_index(drop=True)
    val   = df.loc[val_rows].reset_index(drop=True)
    test  = df.loc[test_rows].reset_index(drop=True)

    log.info(f"  Split : train={len(train)}, val={len(val)}, test={len(test)}")
    return train, val, test


def save_jsonl(df: pd.DataFrame, path: Path):
    """Sauvegarde en JSONL format InputExample sentence-transformers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            record = {
                "offre_id":  row["offre_id"],
                "sentence1": row["sentence1"],  # metadata (requête)
                "sentence2": row["sentence2"],  # description (corpus)
                "titre":     row.get("titre_poste", ""),
                "secteur":   row.get("secteur_principal", ""),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    log.info(f"  Sauvegardé → {path.name} ({len(df)} paires)")


def save_metadata(train, val, test, df_all):
    """Sauvegarde les métadonnées du dataset fine-tuning."""
    # Distribution des secteurs
    dist_secteurs = df_all["secteur_principal"].value_counts().to_dict()

    meta = {
        "total_paires":   len(df_all),
        "n_train":        len(train),
        "n_val":          len(val),
        "n_test":         len(test),
        "split_ratios":   {"train": FT_TRAIN_RATIO, "val": FT_VAL_RATIO, "test": 1 - FT_TRAIN_RATIO - FT_VAL_RATIO},
        "random_seed":    FT_RANDOM_SEED,
        "min_s1_len":     MIN_SENTENCE1_LEN,
        "min_s2_len":     MIN_SENTENCE2_LEN,
        "format":         "JSONL — InputExample sentence-transformers",
        "sentence1_role": "metadata structurées (côté requête)",
        "sentence2_role": "skills_raw + details_clean (côté corpus)",
        "modele_cible":   "all-MiniLM-L6-v2",
        "perte":          "MultipleNegativesRankingLoss",
        "distribution_secteurs": dist_secteurs,
        "stats_longueur": {
            "s1_mean": round(df_all["sentence1"].str.len().mean(), 1),
            "s1_max":  int(df_all["sentence1"].str.len().max()),
            "s2_mean": round(df_all["sentence2"].str.len().mean(), 1),
            "s2_max":  int(df_all["sentence2"].str.len().max()),
        },
    }

    PAIRS_META.parent.mkdir(parents=True, exist_ok=True)
    with open(PAIRS_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log.info(f"  Metadata sauvegardée → {PAIRS_META.name}")

    return meta


def run(save=True) -> dict:
    log.info("=" * 60)
    log.info("PIPELINE ETL — PAIRES FINE-TUNING SENTENCETRANSFORMER")
    log.info("=" * 60)

    df_offres = load_offres_processed()
    df_pairs  = build_pairs(df_offres)

    train, val, test = stratified_split(df_pairs)

    if save:
        save_jsonl(train, PAIRS_TRAIN)
        save_jsonl(val,   PAIRS_VAL)
        save_jsonl(test,  PAIRS_TEST)
        meta = save_metadata(train, val, test, df_pairs)
        log.info(f"\n  Résumé : {meta['total_paires']} paires | "
                 f"train={meta['n_train']} | val={meta['n_val']} | test={meta['n_test']}")

    log.info("✓ Paires fine-tuning construites")
    return {"train": train, "val": val, "test": test, "all": df_pairs}


if __name__ == "__main__":
    run()
