"""
config_neo4j.py
Configuration centralisée du module 03 — Knowledge Graph Neo4j

Contient :
  - Paramètres de connexion Neo4j
  - Chemins des données sources
  - Constantes de chargement (batch sizes, etc.)
  - Labels et types de relations (nomenclature du graphe)
"""
from pathlib import Path

# ── CONNEXION NEO4J ────────────────────────────────────────────────────────
NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "15081960"          # À adapter selon votre installation
NEO4J_DATABASE = "neo4j"             # Base de données cible

# ── CHEMINS ────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent.parent
DATA_PROC = ROOT / "data" / "processed"
ESCO_DIR  = Path("/mnt/user-data/uploads")   # CSV ESCO v1.2 FR

# Sources ESCO (CSV)
ESCO_OCCUPATIONS  = ESCO_DIR / "occupations_fr.csv"
ESCO_SKILLS       = ESCO_DIR / "skills_fr.csv"
ESCO_OCC_SKILLS   = ESCO_DIR / "occupationSkillRelations_fr.csv"
ESCO_SKILL_HIER   = ESCO_DIR / "skillsHierarchy_fr.csv"
ESCO_ISCO         = ESCO_DIR / "ISCOGroups_fr.csv"
ESCO_BROADER_SK   = ESCO_DIR / "broaderRelationsSkillPillar_fr.csv"
ESCO_DIGITAL      = ESCO_DIR / "digitalSkillsCollection_fr.csv"
ESCO_GREEN        = ESCO_DIR / "greenSkillsCollection_fr.csv"
ESCO_TRANSVERSAL  = ESCO_DIR / "transversalSkillsCollection_fr.csv"
ESCO_LANGUAGE     = ESCO_DIR / "languageSkillsCollection_fr.csv"
ESCO_RESEARCH_S   = ESCO_DIR / "researchSkillsCollection_fr.csv"
ESCO_GREEN_OCC    = ESCO_DIR / "greenShareOcc_fr.csv"

# Sources normalisées (Parquet)
OFFRES_PARQUET    = DATA_PROC / "offres_normalized.parquet"
CANDIDATS_PARQUET = DATA_PROC / "candidats_normalized.parquet"
MAPPING_PARQUET   = DATA_PROC / "mapping_isco_mepc_esco.parquet"
MEPC_GRANDS       = DATA_PROC / "mepc_grands_groupes.parquet"
MEPC_SOUS         = DATA_PROC / "mepc_sous_groupes.parquet"
MEPC_BASE         = DATA_PROC / "mepc_groupes_base.parquet"
NCF_NIVEAUX       = DATA_PROC / "ncf_niveaux.parquet"
NCF_GRANDS        = DATA_PROC / "ncf_grands_domaines.parquet"
NCF_SPEC          = DATA_PROC / "ncf_dom_specialises.parquet"
NCF_DET           = DATA_PROC / "ncf_dom_detailles.parquet"

# ── PARAMÈTRES DE CHARGEMENT ──────────────────────────────────────────────
BATCH_SIZE_NODES = 500     # nœuds par transaction MERGE
BATCH_SIZE_RELS  = 2000    # relations par transaction MERGE
BATCH_SIZE_ESCO  = 1000    # lignes ESCO par batch

# ── LABELS DES NŒUDS (16 types) ──────────────────────────────────────────
LABEL_CANDIDAT       = "Candidat"
LABEL_OFFRE          = "OffreEmploi"
LABEL_COMPETENCE     = "Compétence"
LABEL_METIER         = "Métier"
LABEL_GROUPE_COMP    = "GroupeCompétences"
LABEL_GROUPE_ISCO    = "GroupeISCO"
LABEL_MEPC_GRAND     = "GrandGroupeMEPC"
LABEL_MEPC_SOUS      = "SousGroupeMEPC"
LABEL_MEPC_BASE      = "GroupeBaseMEPC"
LABEL_NCF_NIVEAU     = "NiveauFormationNCF"
LABEL_NCF_GRAND      = "GrandDomaineNCF"
LABEL_NCF_SPEC       = "DomaineSpécialiséNCF"
LABEL_NCF_DET        = "DomaineDétailléNCF"
LABEL_SECTEUR        = "Secteur"
LABEL_EMPLOYEUR      = "Employeur"
LABEL_LOCALISATION   = "Localisation"

# ── TYPES DE RELATIONS (22 types) ────────────────────────────────────────
REL_POSSEDE          = "POSSEDE"
REL_REQUIERT         = "REQUIERT"
REL_NECESSITE        = "NECESSITE"
REL_POSTULE          = "POSTULE"
REL_VISE_METIER      = "VISE_METIER"
REL_A_NIVEAU         = "A_NIVEAU"
REL_A_FORMATION      = "A_FORMATION"
REL_SITUE_A          = "SITUE_A"
REL_CORRESPOND_MET   = "CORRESPOND_METIER"
REL_PUBLIEE_PAR      = "PUBLIEE_PAR"
REL_LOCALISEE_A      = "LOCALISEE_A"
REL_DANS_SECTEUR     = "DANS_SECTEUR"
REL_CLASSIFIE_DANS   = "CLASSIFIE_DANS"
REL_CORRESPOND_MEPC  = "CORRESPOND_MEPC"
REL_PARTIE_DE        = "PARTIE_DE"
REL_PLUS_LARGE_QUE   = "PLUS_LARGE_QUE"
REL_SIMILAIRE_A      = "SIMILAIRE_A"
REL_CONTIENT         = "CONTIENT"
REL_PREPARE_POUR     = "PREPARE_POUR"
REL_DEVELOPPE        = "DEVELOPPE"
REL_REQUIS_PAR       = "REQUIS_PAR"
REL_ALIGNE_AVEC      = "ALIGNE_AVEC"
