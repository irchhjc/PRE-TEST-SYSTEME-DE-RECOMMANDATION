"""
normalize_offres.py — Pipeline ETL complet pour le dataset des offres d'emploi

Stratégie de nettoyage :
  1. Déduplication sur (Titre + Employeur + Ville + Secteur)
  2. Nettoyage texte : espaces insécables, strip, casse
  3. Nettoyage 'Détails de l'Annonce' : boilerplate scraping
  4. Explosion multi-valeurs : Ville / Région, Secteur d'Activité, Compétences
  5. Mapping Niveau Études → code NCF (1-9)
  6. Mapping Niveau Expérience → entier
  7. Normalisation Type de Contrat et Groupe de Contrat
  8. Génération UUID stable par offre
  9. Construction text_to_embed (côté corpus fine-tuning ST)
 10. Sauvegarde en Parquet (format optimisé)
"""

import sys
import logging
from pathlib import Path

import pandas as pd
import numpy as np

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    OFFRES_RAW, OFFRES_PROC, DATA_PROC,
    NIVEAU_ETUDES_OFFRES_TO_NCF, TYPE_CONTRAT_NORMALIZE,
    GROUPE_CONTRAT_NORMALIZE, EXPERIENCE_TO_INT,
    FT_MAX_DESC_CHARS,
)
from utils import (
    clean_whitespace, clean_details_annonce,
    normalize_ville, normalize_secteurs, normalize_skills,
    generate_uuid, profil_qualite, log_etape, log,
)


# ─────────────────────────────────────────────────────────────────
# CHARGEMENT
# ─────────────────────────────────────────────────────────────────

def load_raw(path=OFFRES_RAW) -> pd.DataFrame:
    log.info(f"Chargement offres : {path}")
    df = pd.read_excel(path, dtype=str)
    log.info(f"  → {df.shape[0]} lignes, {df.shape[1]} colonnes")
    return df


# ─────────────────────────────────────────────────────────────────
# ÉTAPE 1 — NETTOYAGE DE BASE
# ─────────────────────────────────────────────────────────────────

def clean_base(df: pd.DataFrame) -> pd.DataFrame:
    """Strip + espaces insécables sur toutes les colonnes texte."""
    df = df.copy()
    str_cols = df.select_dtypes(include="object").columns
    for col in str_cols:
        df[col] = df[col].apply(
            lambda x: clean_whitespace(x) if isinstance(x, str) else x
        )
        # NaN explicites → pd.NA
        df[col] = df[col].replace("", pd.NA).replace("nan", pd.NA).replace("NaN", pd.NA)
    return df


# ─────────────────────────────────────────────────────────────────
# ÉTAPE 2 — DÉDUPLICATION
# ─────────────────────────────────────────────────────────────────

def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Supprime les doublons exacts.
    Clé de déduplication : Titre + Employeur + Ville + Secteur.
    Si doublon, garde la ligne avec le plus de contenu (Details non nul en priorité).
    """
    n_before = len(df)

    # Trier pour que les lignes avec Details non nuls arrivent en premier
    df = df.sort_values(
        by=["Détails de l'Annonce"],
        key=lambda s: s.isna(),
        ascending=True,
    )

    # Déduplication sur clé composite
    subset = ["Titre du Poste", "Employeur", "Ville / Région", "Secteur d'Activité"]
    df = df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)

    log_etape("Déduplication", pd.DataFrame(index=range(n_before)), df)
    return df


# ─────────────────────────────────────────────────────────────────
# ÉTAPE 3 — NETTOYAGE DÉTAILS ANNONCE
# ─────────────────────────────────────────────────────────────────

def clean_details(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoie le champ texte brut scraped."""
    df = df.copy()
    df["details_clean"] = df["Détails de l'Annonce"].apply(
        lambda x: clean_details_annonce(x) if isinstance(x, str) else ""
    )
    # Tronquer à FT_MAX_DESC_CHARS pour le fine-tuning
    df["details_truncated"] = df["details_clean"].str[:FT_MAX_DESC_CHARS]
    log.info(f"  Détails nettoyés : {(df['details_clean'] != '').sum()} / {len(df)} non vides")
    return df


# ─────────────────────────────────────────────────────────────────
# ÉTAPE 4 — EXPLOSION MULTI-VALEURS
# ─────────────────────────────────────────────────────────────────

def explode_multivalues(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise les champs multi-valeurs (villes, secteurs, compétences).
    Crée des colonnes LIST et des colonnes scalaires (ville_principale, secteur_principal).
    """
    df = df.copy()

    # Villes
    df["villes_list"] = df["Ville / Région"].apply(
        lambda x: normalize_ville(x) if isinstance(x, str) else []
    )
    df["ville_principale"] = df["villes_list"].apply(
        lambda lst: lst[0] if lst else None
    )

    # Secteurs
    df["secteurs_list"] = df["Secteur d'Activité"].apply(
        lambda x: normalize_secteurs(x) if isinstance(x, str) else []
    )
    df["secteur_principal"] = df["secteurs_list"].apply(
        lambda lst: lst[0] if lst else None
    )

    # Compétences / Skills
    df["skills_list"] = df["Compétences / Skills"].apply(
        lambda x: normalize_skills(x) if isinstance(x, str) else []
    )

    log.info(f"  Villes : {df['ville_principale'].notna().sum()} précisées")
    log.info(f"  Secteurs : {df['secteur_principal'].notna().sum()} précisés")
    return df


# ─────────────────────────────────────────────────────────────────
# ÉTAPE 5 — MAPPING NIVEAUX & NORMALISATION CATÉGORIELS
# ─────────────────────────────────────────────────────────────────

def map_categorical(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Niveau d'études → code NCF
    df["ncf_niveau_code"] = (
        df["Niveau d'Études"]
        .map(NIVEAU_ETUDES_OFFRES_TO_NCF)
        .astype("Int64")        # entier nullable
    )

    # Niveau expérience → entier
    df["experience_min_ans"] = (
        df["Niveau d'Expérience"]
        .map(EXPERIENCE_TO_INT)
        .astype("Int64")
    )

    # Normalisation type de contrat
    df["type_contrat_norm"] = (
        df["Type de Contrat"]
        .map(TYPE_CONTRAT_NORMALIZE)
        .fillna(df["Type de Contrat"])
    )

    # Normalisation groupe de contrat
    df["groupe_contrat_norm"] = (
        df["Groupe de Contrat"]
        .map(GROUPE_CONTRAT_NORMALIZE)
    )

    # Type d'entreprise — simplifié
    df["type_entreprise_norm"] = df["Type d'Entreprise"].apply(
        lambda x: _normalize_type_entreprise(x) if isinstance(x, str) else None
    )

    return df


def _normalize_type_entreprise(val: str) -> str:
    val_low = val.lower()
    if "ong" in val_low or "international" in val_low:
        return "ONG/International"
    if "public" in val_low or "para" in val_low:
        return "Public/Para-public"
    return "Privé"


# ─────────────────────────────────────────────────────────────────
# ÉTAPE 6 — UUID + RENOMMAGE COLONNES
# ─────────────────────────────────────────────────────────────────

def finalize_schema(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renomme les colonnes vers le schéma du projet, génère les UUIDs,
    sélectionne et ordonne les colonnes finales.
    """
    df = df.copy()

    # UUID stable
    df["offre_id"] = [generate_uuid() for _ in range(len(df))]

    # Renommage colonnes brutes → schéma normalisé
    rename_map = {
        "Source":               "source",
        "Lien / Référence":     "lien_reference",
        "Titre du Poste":       "titre_poste",
        "Employeur":            "employeur",
        "Pays":                 "pays",
        "Groupe de Contrat":    "groupe_contrat_raw",
        "Type de Contrat":      "type_contrat_raw",
        "Niveau d'Expérience":  "niveau_experience_raw",
        "Niveau d'Études":      "niveau_etudes_raw",
        "Compétences / Skills": "skills_raw",
        "Détails de l'Annonce": "details_raw",
        "Type d'Entreprise":    "type_entreprise_raw",
        "Secteur d'Activité":   "secteur_activite_raw",
        "Ville / Région":       "ville_region_raw",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Colonnes finales ordonnées
    cols = [
        "offre_id",
        "source",
        "titre_poste",
        "employeur",
        "type_entreprise_norm",
        "pays",
        "ville_principale",
        "villes_list",
        "secteur_principal",
        "secteurs_list",
        "groupe_contrat_norm",
        "type_contrat_norm",
        "ncf_niveau_code",
        "niveau_etudes_raw",
        "experience_min_ans",
        "niveau_experience_raw",
        "skills_list",
        "skills_raw",
        "details_clean",
        "details_truncated",
        "details_raw",
        "lien_reference",
        "groupe_contrat_raw",
        "type_contrat_raw",
        "secteur_activite_raw",
        "ville_region_raw",
        "type_entreprise_raw",
    ]
    # Ne garder que les colonnes qui existent
    cols = [c for c in cols if c in df.columns]
    return df[cols]


# ─────────────────────────────────────────────────────────────────
# ÉTAPE 7 — TEXT_TO_EMBED (côté corpus ST fine-tuning)
# ─────────────────────────────────────────────────────────────────

def build_text_to_embed_offre(row: pd.Series) -> str:
    """
    Construit le texte côté corpus pour le fine-tuning du SentenceTransformer.
    Ce texte encode la sémantique complète de l'offre (description + compétences).
    C'est la sentence2 des paires (metadata → description).
    """
    parts = []

    # Compétences listent ce que demande l'offre
    if isinstance(row.get("skills_list"), list) and row["skills_list"]:
        parts.append("Compétences requises : " + ", ".join(row["skills_list"]))

    # Détails de l'annonce (texte nettoyé)
    if row.get("details_clean"):
        parts.append(row["details_clean"][:FT_MAX_DESC_CHARS])

    return " ".join(parts).strip()


def build_metadata_str_offre(row: pd.Series) -> str:
    """
    Construit le texte côté requête (metadata structurées).
    C'est la sentence1 des paires (metadata → description).
    Aligne le format sur ce que fournirait un profil candidat.
    """
    parts = []
    if pd.notna(row.get("titre_poste")):
        parts.append(f"Poste: {row['titre_poste']}")
    if pd.notna(row.get("secteur_principal")):
        parts.append(f"Secteur: {row['secteur_principal']}")
    if pd.notna(row.get("type_contrat_norm")):
        parts.append(f"Contrat: {row['type_contrat_norm']}")
    if pd.notna(row.get("niveau_etudes_raw")):
        parts.append(f"Études: {row['niveau_etudes_raw']}")
    if pd.notna(row.get("niveau_experience_raw")):
        parts.append(f"Expérience: {row['niveau_experience_raw']}")
    if pd.notna(row.get("ville_principale")):
        parts.append(f"Ville: {row['ville_principale']}")
    return " | ".join(parts)


def add_embed_texts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["text_to_embed"]   = df.apply(build_text_to_embed_offre, axis=1)
    df["metadata_str"]    = df.apply(build_metadata_str_offre,  axis=1)
    # Filtre : ne garder pour le FT que les paires où les deux côtés sont non vides
    df["ft_eligible"] = (
        (df["text_to_embed"].str.len() > 50) &
        (df["metadata_str"].str.len() > 20)
    )
    log.info(f"  Paires FT éligibles: {df['ft_eligible'].sum()} / {len(df)}")
    return df


# ─────────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────────────────────────────

def run(save=True) -> pd.DataFrame:
    log.info("=" * 60)
    log.info("PIPELINE ETL — OFFRES D'EMPLOI")
    log.info("=" * 60)

    df = load_raw()
    rapport_initial = profil_qualite(df, "offres_raw")

    df = clean_base(df)
    log.info(f"[1/7] Nettoyage de base terminé")

    df = deduplicate(df)
    log.info(f"[2/7] Déduplication terminée")

    df = clean_details(df)
    log.info(f"[3/7] Nettoyage détails annonce terminé")

    df = explode_multivalues(df)
    log.info(f"[4/7] Explosion multi-valeurs terminée")

    df = map_categorical(df)
    log.info(f"[5/7] Mapping catégoriels terminé")

    df = finalize_schema(df)
    log.info(f"[6/7] Schéma finalisé")

    df = add_embed_texts(df)
    log.info(f"[7/7] Textes d'embedding construits")

    if save:
        DATA_PROC.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OFFRES_PROC, index=False)
        log.info(f"Sauvegardé → {OFFRES_PROC}")

        # Rapport qualité
        rapport_final = profil_qualite(df, "offres_processed")
        rapport_final.to_csv(DATA_PROC / "rapport_qualite_offres.csv", index=False)

    log.info(f"✓ Offres traitées : {len(df)} lignes")
    return df


if __name__ == "__main__":
    run()
