"""
align_referentiels.py — Chargement et alignement des référentiels MEPC, NCF et ESCO

Rôle dans le projet :
  - Structurer les référentiels MEPC et NCF en DataFrames normalisés
  - Construire la table de mapping ISCO-08 ↔ MEPC ↔ ESCO
  - Préparer les textes text_to_embed pour les nœuds NCF et MEPC (pgvector)
  - Sauvegarder les tables de correspondance utilisées par Neo4j et pgvector
"""

import sys
import csv
import logging
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    MEPC_RAW, NCF_RAW, DATA_PROC, DATA_RAW,
    MEPC_PROC, NCF_PROC, MAPPING_PROC,
)
from utils import clean_whitespace, log

ESCO_DIR = DATA_RAW / "esco"
ESCO_OCC_PATH   = Path("/mnt/user-data/uploads/occupations_fr.csv")
ESCO_SKILLS_PATH = Path("/mnt/user-data/uploads/skills_fr.csv")
ESCO_ISCO_PATH  = Path("/mnt/user-data/uploads/ISCOGroups_fr.csv")
ESCO_REL_PATH   = Path("/mnt/user-data/uploads/occupationSkillRelations_fr.csv")


# ─────────────────────────────────────────────────────────────────
# CHARGEMENT MEPC
# ─────────────────────────────────────────────────────────────────

def load_mepc() -> dict[str, pd.DataFrame]:
    """Charge les 3 feuilles du référentiel MEPC."""
    log.info(f"Chargement MEPC : {MEPC_RAW}")
    sheets = pd.read_excel(MEPC_RAW, sheet_name=None)

    mepc_grands   = sheets["Grands Groupes"].copy()
    mepc_sous     = sheets["Sous-Groupes"].copy()
    mepc_base     = sheets["Groupes de Base"].copy()

    # Nettoyage colonnes texte
    for df in [mepc_grands, mepc_sous, mepc_base]:
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].apply(
                lambda x: clean_whitespace(x) if isinstance(x, str) else x
            )

    # Renommage colonnes standard
    for df in [mepc_grands, mepc_sous, mepc_base]:
        df.rename(columns={
            "Code":                     "code",
            "Intitulé":                 "intitule",
            "Notes Explicatives (MEPC)": "notes_explicatives",
            "Codes CITP rev.4":         "codes_citp",
            "Code Grand Groupe":        "code_grand_groupe",
            "Code Sous-Groupe":         "code_sous_groupe",
        }, inplace=True)
        df["code"] = df["code"].astype(str)

    # text_to_embed pour pgvector (nœuds MEPC dans Neo4j)
    def build_mepc_embed(row, niveau):
        text = f"{row['intitule']}."
        if pd.notna(row.get("notes_explicatives")):
            text += f" {str(row['notes_explicatives'])[:400]}"
        return text.strip()

    mepc_grands["text_to_embed"] = mepc_grands.apply(
        lambda r: build_mepc_embed(r, "grand"), axis=1)
    mepc_sous["text_to_embed"]   = mepc_sous.apply(
        lambda r: build_mepc_embed(r, "sous"), axis=1)
    mepc_base["text_to_embed"]   = mepc_base.apply(
        lambda r: build_mepc_embed(r, "base"), axis=1)

    log.info(f"  MEPC chargé : {len(mepc_grands)} grands groupes, "
             f"{len(mepc_sous)} sous-groupes, {len(mepc_base)} groupes de base")

    return {
        "grands_groupes": mepc_grands,
        "sous_groupes":   mepc_sous,
        "groupes_base":   mepc_base,
    }


# ─────────────────────────────────────────────────────────────────
# CHARGEMENT NCF
# ─────────────────────────────────────────────────────────────────

def load_ncf() -> dict[str, pd.DataFrame]:
    """Charge les 4 feuilles du référentiel NCF."""
    log.info(f"Chargement NCF : {NCF_RAW}")
    sheets = pd.read_excel(NCF_RAW, sheet_name=None)

    ncf_niveaux   = sheets["Niveaux de Formation"].copy()
    ncf_grands    = sheets["Grands Domaines"].copy()
    ncf_spec      = sheets["Domaines Spécialisés"].copy()
    ncf_det       = sheets["Domaines Détaillés"].copy()

    # Nettoyage + renommage
    rename_common = {"Code": "code", "Intitulé": "intitule"}
    rename_expl = {
        "Notes explicatives (NCF)": "explication",
        "Explication (NCF)": "explication",
    }
    rename_keys = {
        "Code Dom. Spécialisé": "code_dom_specialise",
        "Code Grand Domaine": "code_grand_domaine",
    }

    for df in [ncf_niveaux, ncf_grands, ncf_spec, ncf_det]:
        df.rename(columns={**rename_common, **rename_expl, **rename_keys},
                  inplace=True, errors="ignore")
        df["code"] = df["code"].astype(str)
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].apply(
                lambda x: clean_whitespace(x) if isinstance(x, str) else x
            )

    # text_to_embed pour pgvector (DomaineDétaillé a pgvector_id dans Neo4j)
    def build_ncf_embed(row):
        text = f"{row['intitule']}."
        if pd.notna(row.get("explication")):
            text += f" {str(row['explication'])[:400]}"
        return text.strip()

    for df in [ncf_niveaux, ncf_grands, ncf_spec, ncf_det]:
        df["text_to_embed"] = df.apply(build_ncf_embed, axis=1)

    log.info(f"  NCF chargé : {len(ncf_niveaux)} niveaux, {len(ncf_grands)} grands domaines, "
             f"{len(ncf_spec)} spécialisés, {len(ncf_det)} détaillés")

    return {
        "niveaux":         ncf_niveaux,
        "grands_domaines": ncf_grands,
        "dom_specialises": ncf_spec,
        "dom_detailles":   ncf_det,
    }


# ─────────────────────────────────────────────────────────────────
# CHARGEMENT ESCO
# ─────────────────────────────────────────────────────────────────

def load_esco() -> dict[str, pd.DataFrame]:
    """Charge les fichiers ESCO disponibles (FR)."""
    log.info("Chargement ESCO...")

    paths = {
        "occupations":  ESCO_OCC_PATH,
        "skills":       ESCO_SKILLS_PATH,
        "isco_groups":  ESCO_ISCO_PATH,
        "occ_skill_rel": ESCO_REL_PATH,
    }
    result = {}
    for name, path in paths.items():
        if path.exists():
            df = pd.read_csv(path, dtype=str, low_memory=False)
            result[name] = df
            log.info(f"  ESCO {name}: {len(df)} lignes")
        else:
            log.warning(f"  ESCO {name} NON TROUVÉ : {path}")
            result[name] = pd.DataFrame()

    return result


# ─────────────────────────────────────────────────────────────────
# CONSTRUCTION DU MAPPING ISCO ↔ MEPC ↔ ESCO
# ─────────────────────────────────────────────────────────────────

def build_mapping(mepc: dict, esco: dict) -> pd.DataFrame:
    """
    Table de correspondance ISCO-08 ↔ GroupeBaseMEPC ↔ Métier ESCO.

    Logique :
    1. Chaque GroupeBaseMEPC porte un ou plusieurs codes CITP (ISCO-08)
    2. Les métiers ESCO portent le champ 'iscoGroup' (code ISCO-08 sur 4 chiffres)
    3. On joint sur les 2 premiers chiffres (sous-groupe ISCO)
       pour maximiser le nombre de correspondances.

    Résultat : table (mepc_code_base, mepc_intitule, isco_code, esco_uri, esco_label)
    """
    mepc_base = mepc["groupes_base"].copy()
    df_occ    = esco.get("occupations", pd.DataFrame())

    if df_occ.empty:
        log.warning("ESCO occupations non disponibles - mapping partiel uniquement")
        return pd.DataFrame()

    # Exploser les codes CITP multiples de la MEPC (ex: "111, 112" → ["111", "112"])
    def parse_citp(val):
        if not isinstance(val, str) or not val.strip():
            return []
        return [c.strip() for c in val.replace("/", ",").split(",") if c.strip().isdigit()]

    mepc_base["citp_list"] = mepc_base["codes_citp"].apply(parse_citp)
    mepc_exploded = mepc_base.explode("citp_list").rename(
        columns={"citp_list": "isco_code_mepc"}
    )
    mepc_exploded = mepc_exploded[mepc_exploded["isco_code_mepc"].notna()]

    # Côté ESCO : code ISCO sur 4 chiffres → tronquer à 2-3 chiffres pour join élargi
    df_occ_work = df_occ[["conceptUri", "preferredLabel", "iscoGroup"]].copy()
    df_occ_work["iscoGroup_2"] = df_occ_work["iscoGroup"].str[:2]

    # Join sur les 2 premiers chiffres
    mepc_exploded["isco_code_mepc_2"] = mepc_exploded["isco_code_mepc"].str[:2]

    mapping = mepc_exploded.merge(
        df_occ_work,
        left_on="isco_code_mepc_2",
        right_on="iscoGroup_2",
        how="left",
    ).rename(columns={
        "conceptUri":     "esco_uri",
        "preferredLabel": "esco_label",
        "iscoGroup":      "esco_isco_code",
    })

    mapping_final = mapping[[
        "code", "intitule", "code_sous_groupe", "code_grand_groupe",
        "codes_citp", "isco_code_mepc", "esco_uri", "esco_label", "esco_isco_code",
    ]].rename(columns={
        "code":            "mepc_code_base",
        "intitule":        "mepc_intitule",
    })

    n_mapped = mapping_final["esco_uri"].notna().sum()
    log.info(f"  Mapping MEPC↔ESCO : {n_mapped} / {len(mapping_final)} correspondances")

    return mapping_final


# ─────────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────────────────────────────

def run(save=True) -> dict:
    log.info("=" * 60)
    log.info("PIPELINE ETL - RÉFÉRENTIELS MEPC + NCF + ESCO")
    log.info("=" * 60)

    mepc = load_mepc()
    ncf  = load_ncf()
    esco = load_esco()

    mapping = build_mapping(mepc, esco)

    if save:
        DATA_PROC.mkdir(parents=True, exist_ok=True)

        # MEPC
        for key, df in mepc.items():
            path = DATA_PROC / f"mepc_{key}.parquet"
            df.to_parquet(path, index=False)
            log.info(f"  Sauvegardé → {path.name}")

        # NCF
        for key, df in ncf.items():
            path = DATA_PROC / f"ncf_{key}.parquet"
            df.to_parquet(path, index=False)
            log.info(f"  Sauvegardé → {path.name}")

        # Mapping global
        if not mapping.empty:
            mapping.to_parquet(MAPPING_PROC, index=False)
            log.info(f"  Sauvegardé → {MAPPING_PROC.name}")

    log.info("✓ Référentiels traités")
    return {"mepc": mepc, "ncf": ncf, "esco": esco, "mapping": mapping}


if __name__ == "__main__":
    run()
