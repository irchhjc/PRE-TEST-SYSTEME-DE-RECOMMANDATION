"""
config.py — Configuration centralisée du module ETL
Contient tous les mappings, chemins et constantes du projet
"""
from pathlib import Path

# ── CHEMINS ─────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent.parent.parent
DATA_RAW   = ROOT / "data" / "raw"
DATA_PROC  = ROOT / "data" / "processed"
DATA_FT    = ROOT / "data" / "finetune"

# Sources brutes
OFFRES_RAW     = DATA_RAW / "offres.xlsx"
DEMANDEUR_RAW  = DATA_RAW / "demandeur.xlsx"
MEPC_RAW       = DATA_RAW / "MEPC_Nomenclature_Camerounaise_Metiers.xlsx"
NCF_RAW        = DATA_RAW / "NCF_Nomenclature_Camerounaise_Formations.xlsx"

# ESCO CSVs (chemin uploads partagé ou raw/)
ESCO_DIR       = DATA_RAW / "esco"

# Sorties processed
OFFRES_PROC    = DATA_PROC / "offres_normalized.parquet"
DEMANDEUR_PROC = DATA_PROC / "candidats_normalized.parquet"
MEPC_PROC      = DATA_PROC / "mepc_referentiel.parquet"
NCF_PROC       = DATA_PROC / "ncf_referentiel.parquet"
MAPPING_PROC   = DATA_PROC / "mapping_isco_mepc_esco.parquet"

# Sorties fine-tuning SentenceTransformer
PAIRS_TRAIN    = DATA_FT / "pairs_train.jsonl"
PAIRS_VAL      = DATA_FT / "pairs_val.jsonl"
PAIRS_TEST     = DATA_FT / "pairs_test.jsonl"
PAIRS_META     = DATA_FT / "pairs_metadata.json"

# ── MAPPING NIVEAU ÉTUDES OFFRES → CODE NCF (1-9) ────────────────
# Colonne : "Niveau d'Études" dans offres.xlsx
NIVEAU_ETUDES_OFFRES_TO_NCF = {
    "Sans diplôme":     1,
    "BEPC/CAP":         4,
    "BAC":              5,
    "BTS/DUT (BAC+2)":  6,
    "Licence (BAC+3)":  7,
    "Master (BAC+5)":   8,
    "Doctorat":         9,
    "Non spécifié":     None,
}

# ── MAPPING NIVEAU ÉTUDES DEMANDEURS → CODE NCF (1-9) ────────────
# Colonne : "niveau_etude" dans demandeur.xlsx
NIVEAU_ETUDES_CAND_TO_NCF = {
    "Aucun":                        1,
    "Primaire":                     3,
    "Secondaire 1":                 4,
    "Bac":                          5,
    "Post-secondaire – Professionnel": 6,
    "Bac +3":                       7,
    "Bac +4/+5 et plus":            8,
}

# ── MAPPING DIPLÔME DEMANDEURS → CODE NCF ────────────────────────
DIPLOME_TO_NCF = {
    "Certificat d'Études Primaires Élémentaires (CEPE)": 3,
    "Brevet d'Études du Premier Cycle (BEPC)":           4,
    "Brevet d'Etude Technique (BET)":                    4,
    "CAP/BEP":                                           4,
    "Certificat d'Aptitude Professionnelle (CAP)":       4,
    "Baccalauréat Général":                              5,
    "Baccalauréat Professionnel":                        5,
    "Baccalauréat Technologique":                        5,
    "BAC Technique":                                     5,
    "Baccalauréat":                                      5,
    "Brevet de Technicien":                              5,
    "Brevet de Technicien Supérieur (BTS)":              6,
    "BTS/DUT":                                           6,
    "Bac +2":                                            6,
    "Diplôme de Technicien Supérieur (DTS)":             6,
    "Licence":                                           7,
    "Licence Professionnelle ":                          7,
    "Master 1":                                          7,  # M1 = BAC+4 → NCF 7 ou 8
    "Maîtrise":                                          8,
    "Master":                                            8,
    "Doctorat":                                          9,
    "Pas de diplôme":                                    1,
}

# ── NORMALISATION VILLES ─────────────────────────────────────────
# Harmonise les casses et variantes
VILLE_NORMALIZE = {
    "yaoundé":    "Yaoundé",
    "yaounde":    "Yaoundé",
    "yaound":     "Yaoundé",
    "douala":     "Douala",
    "doula":      "Douala",
    "bafoussam":  "Bafoussam",
    "maroua":     "Maroua",
    "garoua":     "Garoua",
    "bamenda":    "Bamenda",
    "buéa":       "Buéa",
    "buea":       "Buéa",
    "limbe":      "Limbé",
    "ngaoundéré": "Ngaoundéré",
    "ngaoundere": "Ngaoundéré",
    "bertoua":    "Bertoua",
    "ebolowa":    "Ebolowa",
    "kribi":      "Kribi",
    "cameroun (ville non précisée)": None,  # → None = localisation non précisée
}

# ── NORMALISATION TYPE DE CONTRAT ────────────────────────────────
TYPE_CONTRAT_NORMALIZE = {
    "CDI":              "CDI",
    "CDD":              "CDD",
    "CDI/CDD":          "CDI/CDD",
    "Contrat":          "Autre",
    "Contrat :":        "Autre",
    "Contractuel":      "Contractuel",
    "Temps plein":      "Temps plein",
    "Temps partiel":    "Temps partiel",
    "Stage":            "Stage",
    "Intérim/Temporaire": "Intérim",
}

# ── NORMALISATION GROUPE DE CONTRAT ─────────────────────────────
GROUPE_CONTRAT_NORMALIZE = {
    "Emploi Durable":           "CDI/Permanent",
    "Emploi Temporaire":        "CDD/Temporaire",
    "Stage":                    "Stage",
    "Freelance / Indépendant":  "Freelance",
    "Non spécifié":             None,
}

# ── NORMALISATION NIVEAU EXPÉRIENCE → entier ────────────────────
EXPERIENCE_TO_INT = {
    "Débutant (0 an)": 0,
    "1-2 ans":         1,
    "3-5 ans":         3,
    "5-10 ans":        5,
    "10+ ans":         10,
    "Non spécifié":    None,
}

# ── PATTERNS BRUIT DETAILS ANNONCE ──────────────────────────────
# Regex à supprimer du texte brut (boilerplate scraping)
BRUIT_PATTERNS = [
    r"PARTAGEZ AVEC VOS PROCHES SUR.*?(?=\n\n|\Z)",
    r"RESTEZ INFORME!!.*?(?=\n\n|\Z)",
    r"REJOIGNEZ.*?(?:WHATSAPP|TELEGRAM).*?(?=\n|\Z)",
    r"Laisser un commentaire.*?\Z",
    r"Votre adresse e-mail.*?(?=\n|\Z)",
    r"Les champs obligatoires.*?(?=\n|\Z)",
    r"Enregistrer mon nom.*?(?=\n|\Z)",
    r"Prévenez-moi de tous.*?(?=\n|\Z)",
    r"More from \w+.*?(?=\n|\Z)",
    r"More posts in \w+.*?(?=\n|\Z)",
    r"Be First to Comment.*?\Z",
    r"En savoir plus sur.*?(?=\n|\Z)",
    r"Publié il y a \d+ (?:mois?|ans?|jour[s]?).*?(?=\n|\Z)",
    r"Je Postule\s*",
    r"Postuler\s*$",
    r"date cloture.*?(?=\n|\Z)",
    r"villes\s*:.*?(?=\n|\Z)",
    r"Dans \".*?\"",
    r"\n{3,}",   # lignes vides multiples → \n\n max
    r"\xa0",     # espace insécable
]

# ── SECTEURS — NORMALISATION CASSE ──────────────────────────────
# Les secteurs offres sont en MAJUSCULES mixtes → normaliser
SECTEUR_CASSE_MAP = {
    "FINANCE":           "Finance",
    "INFORMATIQUE":      "Informatique",
    "ADMINISTRATION":    "Administration",
    "COMMERCE":          "Commerce",
    "COMPTABILITÉ":      "Comptabilité",
    "MARKETING":         "Marketing",
    "GESTION":           "Gestion",
    "SANTÉ":             "Santé",
    "COMMUNICATION":     "Communication",
    "VENTE":             "Vente",
    "ONG":               "ONG / Humanitaire",
    "SCIENCE SOCIALE":   "Sciences Sociales",
    "ÉDUCATION":         "Éducation",
    "RH":                "Ressources Humaines",
    "JURIDIQUE":         "Droit / Juridique",
    "LOGISTIQUE":        "Logistique",
    "AGRICULTURE":       "Agriculture",
    "GÉNIE CIVIL":       "Génie Civil",
    "ENERGIE":           "Énergie",
    "TRANSPORT":         "Transport",
    "Autre":             "Autre",
}

# ── PARAMÈTRES FINE-TUNING DATASET ──────────────────────────────
FT_TRAIN_RATIO = 0.70
FT_VAL_RATIO   = 0.15
FT_TEST_RATIO  = 0.15
FT_RANDOM_SEED = 42
FT_MAX_DESC_CHARS = 1500  # troncature description côté corpus
FT_MAX_META_CHARS = 300   # troncature métadonnées côté requête
