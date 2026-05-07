"""
run_etl.py — Orchestrateur principal du module ETL

Exécute les 4 étapes du pipeline dans l'ordre :
  1. normalize_offres     → offres_normalized.parquet
  2. normalize_candidats  → candidats_normalized.parquet
  3. align_referentiels   → mepc_*.parquet, ncf_*.parquet, mapping_*.parquet
  4. build_pairs          → pairs_{train,val,test}.jsonl
"""

import sys
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils import log
import normalize_offres
import normalize_candidats
import align_referentiels
import build_pairs


def run_all():
    log.info("=" * 70)
    log.info("PIPELINE ETL COMPLET — SYSTÈME RECOMMANDATION EMPLOI-CAMEROUN")
    log.info("=" * 70)

    t0 = time.time()
    results = {}

    # ── Étape 1 : Offres ──────────────────────────────────────
    t = time.time()
    log.info("\n[ÉTAPE 1/4] Normalisation des offres d'emploi")
    results["offres"] = normalize_offres.run(save=True)
    log.info(f"  ✓ Temps : {time.time()-t:.1f}s")

    # ── Étape 2 : Candidats ───────────────────────────────────
    t = time.time()
    log.info("\n[ÉTAPE 2/4] Normalisation des demandeurs d'emploi")
    results["candidats"] = normalize_candidats.run(save=True)
    log.info(f"  ✓ Temps : {time.time()-t:.1f}s")

    # ── Étape 3 : Référentiels ────────────────────────────────
    t = time.time()
    log.info("\n[ÉTAPE 3/4] Chargement et alignement MEPC / NCF / ESCO")
    results["referentiels"] = align_referentiels.run(save=True)
    log.info(f"  ✓ Temps : {time.time()-t:.1f}s")

    # ── Étape 4 : Paires fine-tuning ──────────────────────────
    t = time.time()
    log.info("\n[ÉTAPE 4/4] Construction des paires fine-tuning SentenceTransformer")
    results["pairs"] = build_pairs.run(save=True)
    log.info(f"  ✓ Temps : {time.time()-t:.1f}s")

    # ── Résumé final ──────────────────────────────────────────
    total = time.time() - t0
    log.info("\n" + "=" * 70)
    log.info(f"PIPELINE TERMINÉ EN {total:.1f}s")
    log.info(f"  Offres normalisées   : {len(results['offres'])} lignes")
    log.info(f"  Candidats normalisés : {len(results['candidats'])} lignes")
    log.info(f"  Paires FT train      : {len(results['pairs']['train'])} paires")
    log.info(f"  Paires FT val        : {len(results['pairs']['val'])} paires")
    log.info(f"  Paires FT test       : {len(results['pairs']['test'])} paires")
    log.info("=" * 70)

    return results


if __name__ == "__main__":
    run_all()
