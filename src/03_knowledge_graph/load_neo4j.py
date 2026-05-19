"""
load_neo4j.py
===========================================================================
Module 03 — Chargement du Graphe de Connaissances Neo4j

Pipeline de chargement en 7 étapes ordonnées :
  1. Création du schéma (contraintes + index)
  2. Chargement des référentiels ESCO (Compétences, Métiers, ISCO, GroupeComp)
  3. Chargement des référentiels MEPC (3 niveaux)
  4. Chargement des référentiels NCF (4 niveaux)
  5. Chargement des Offres + nœuds contextuels (Secteur, Employeur, Localisation)
  6. Chargement des Candidats
  7. Création des relations inter-entités

Principe d'idempotence : MERGE sur la clé unique → relancer sans doublon.
Principe de batch : toutes les transactions sont batched pour la performance.

Usage :
    python load_neo4j.py                    # pipeline complet
    python load_neo4j.py --step esco        # étape spécifique
    python load_neo4j.py --step offres
    python load_neo4j.py --dry-run          # validation sans écriture
    python load_neo4j.py --clear            # vider la base avant rechargement

Dépendances :
    pip install neo4j pandas pyarrow
===========================================================================
"""

import argparse
import csv
import logging
import sys
import time
from pathlib import Path
from typing import Generator

import pandas as pd
from neo4j import GraphDatabase, Driver

sys.path.insert(0, str(Path(__file__).parent))
from config_neo4j import *

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# DRIVER + UTILITAIRES
# ─────────────────────────────────────────────────────────────────────────

def get_driver() -> Driver:
    driver = GraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
    )
    driver.verify_connectivity()
    log.info(f"Connexion Neo4j OK → {NEO4J_URI}")
    return driver


def run_query(driver: Driver, query: str, params: dict = None):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(query, params or {})
        return result.consume()


def batch_merge(
    driver: Driver,
    query: str,
    rows: list[dict],
    batch_size: int = BATCH_SIZE_NODES,
    label: str = "",
) -> int:
    """
    Exécute une requête MERGE en lots.
    La requête doit utiliser UNWIND $rows AS row.
    Retourne le nombre total de nœuds/relations créés.
    """
    total = 0
    n_batches = (len(rows) - 1) // batch_size + 1
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        with driver.session(database=NEO4J_DATABASE) as session:
            result = session.run(query, rows=batch)
            summary = result.consume()
            total += (summary.counters.nodes_created
                      + summary.counters.relationships_created)
        if (i // batch_size + 1) % 5 == 0 or i + batch_size >= len(rows):
            pct = min(100, (i + batch_size) / len(rows) * 100)
            log.info(f"  [{label}] {pct:.0f}%  ({min(i+batch_size, len(rows)):,}/{len(rows):,})")
    return total


def read_csv_safe(path: Path, **kwargs) -> list[dict]:
    """Lit un CSV et retourne une liste de dicts, None → ''."""
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: (v.strip() if v else "") for k, v in row.items()})
    return rows


def to_rows(df: pd.DataFrame) -> list[dict]:
    """Convertit un DataFrame en liste de dicts (None → None conservé)."""
    return df.where(df.notna(), other=None).to_dict(orient="records")


# ─────────────────────────────────────────────────────────────────────────
# ÉTAPE 1 — SCHÉMA
# ─────────────────────────────────────────────────────────────────────────

def create_schema(driver: Driver):
    log.info("[1/7] Création du schéma (contraintes + index)...")
    schema_path = Path(__file__).parent / "schema.cypher"
    cypher = schema_path.read_text(encoding="utf-8")
    # Exécuter chaque statement séparément (ignorer les commentaires)
    statements = [s.strip() for s in cypher.split(";")
                  if s.strip() and not s.strip().startswith("//")]
    created = 0
    for stmt in statements:
        try:
            run_query(driver, stmt)
            created += 1
        except Exception as e:
            if "already exists" not in str(e).lower():
                log.warning(f"  Schema warning: {e}")
    log.info(f"  {created} contraintes/index appliqués")


# ─────────────────────────────────────────────────────────────────────────
# ÉTAPE 2 — ESCO : Compétences, Métiers, ISCO, GroupeCompétences
# ─────────────────────────────────────────────────────────────────────────

def load_esco_skills(driver: Driver):
    log.info("[2a] Chargement des Compétences ESCO...")
    rows = read_csv_safe(ESCO_SKILLS)

    # Collections spéciales → set d'URIs
    def load_uris(path: Path) -> set:
        if not path.exists(): return set()
        r = read_csv_safe(path)
        return {row.get("conceptUri", "") for row in r}

    digital_uris     = load_uris(ESCO_DIGITAL)
    green_uris       = load_uris(ESCO_GREEN)
    transversal_uris = load_uris(ESCO_TRANSVERSAL)
    language_uris    = load_uris(ESCO_LANGUAGE)
    research_uris    = load_uris(ESCO_RESEARCH_S)

    enriched = []
    for row in rows:
        uri = row.get("conceptUri", "")
        enriched.append({
            "uri":          uri,
            "label":        row.get("preferredLabel", ""),
            "altLabels":    row.get("altLabels", "").replace("\n", ", ")[:300],
            "description":  row.get("description", "")[:500],
            "skillType":    row.get("skillType", ""),
            "reuseLevel":   row.get("reuseLevel", ""),
            "pillar":       "K" if row.get("skillType") == "knowledge" else "S",
            "isDigital":    uri in digital_uris,
            "isGreen":      uri in green_uris,
            "isTransversal":uri in transversal_uris,
            "isLanguage":   uri in language_uris,
            "isResearch":   uri in research_uris,
        })

    query = """
    UNWIND $rows AS row
    MERGE (s:Compétence {conceptUri: row.uri})
    SET   s.preferredLabel = row.label,
          s.altLabels      = row.altLabels,
          s.description    = row.description,
          s.skillType      = row.skillType,
          s.reuseLevel     = row.reuseLevel,
          s.pillar         = row.pillar,
          s.isDigital      = row.isDigital,
          s.isGreen        = row.isGreen,
          s.isTransversal  = row.isTransversal,
          s.isLanguage     = row.isLanguage,
          s.isResearch     = row.isResearch
    """
    n = batch_merge(driver, query, enriched, BATCH_SIZE_ESCO, "Compétences")
    log.info(f"  → {len(enriched):,} compétences ESCO chargées")


def load_esco_occupations(driver: Driver):
    log.info("[2b] Chargement des Métiers ESCO...")
    rows = read_csv_safe(ESCO_OCCUPATIONS)

    # Charger green share
    green_share = {}
    if ESCO_GREEN_OCC.exists():
        for row in read_csv_safe(ESCO_GREEN_OCC):
            uri = row.get("occupationUri") or row.get("conceptUri", "")
            green_share[uri] = row.get("greenShareCategory", "")

    # Charger mapping MEPC
    df_map = pd.read_parquet(MAPPING_PARQUET)
    mepc_by_esco = {}
    for _, r in df_map.iterrows():
        uri = r.get("esco_uri")
        if uri and uri not in mepc_by_esco:
            mepc_by_esco[uri] = {
                "mepc_base":  str(r.get("mepc_code_base", "")),
                "mepc_sous":  str(r.get("code_sous_groupe", "")),
                "mepc_grand": str(r.get("code_grand_groupe", "")),
            }

    enriched = []
    for row in rows:
        uri = row.get("conceptUri", "")
        mepc = mepc_by_esco.get(uri, {})
        enriched.append({
            "uri":          uri,
            "label":        row.get("preferredLabel", ""),
            "altLabels":    row.get("altLabels", "").replace("\n", ", ")[:300],
            "description":  row.get("description", "")[:500],
            "iscoCode":     row.get("iscoGroup", ""),
            "naceCode":     row.get("naceCode", ""),
            "mepc_base":    mepc.get("mepc_base", ""),
            "mepc_sous":    mepc.get("mepc_sous", ""),
            "mepc_grand":   mepc.get("mepc_grand", ""),
            "greenShare":   green_share.get(uri, ""),
        })

    query = """
    UNWIND $rows AS row
    MERGE (m:Métier {conceptUri: row.uri})
    SET   m.preferredLabel = row.label,
          m.altLabels      = row.altLabels,
          m.description    = row.description,
          m.iscoCode       = row.iscoCode,
          m.naceCode       = row.naceCode,
          m.mepc_base      = row.mepc_base,
          m.mepc_sous      = row.mepc_sous,
          m.mepc_grand     = row.mepc_grand,
          m.greenShareCat  = row.greenShare
    """
    batch_merge(driver, query, enriched, BATCH_SIZE_ESCO, "Métiers")
    log.info(f"  → {len(enriched):,} métiers ESCO chargés")


def load_esco_isco(driver: Driver):
    log.info("[2c] Chargement des GroupeISCO...")
    rows = read_csv_safe(ESCO_ISCO)
    enriched = [{
        "code":   row.get("code", ""),
        "label":  row.get("preferredLabel", ""),
        "desc":   row.get("description", "")[:300],
        "niveau": len(row.get("code", "")),
    } for row in rows if row.get("code")]

    query = """
    UNWIND $rows AS row
    MERGE (g:GroupeISCO {code: row.code})
    SET   g.preferredLabel = row.label,
          g.description    = row.desc,
          g.niveau         = row.niveau
    """
    batch_merge(driver, query, enriched, BATCH_SIZE_NODES, "GroupeISCO")
    log.info(f"  → {len(enriched):,} groupes ISCO chargés")


def load_esco_skill_groups(driver: Driver):
    log.info("[2d] Chargement des GroupeCompétences...")
    rows = read_csv_safe(ESCO_BROADER_SK)
    # GroupeCompétences = nœuds SkillGroup (conceptUri, conceptLabel)
    seen = {}
    for row in rows:
        for uri_key, lbl_key in [("conceptUri","conceptLabel"), ("broaderUri","broaderLabel")]:
            uri = row.get(uri_key, "")
            lbl = row.get(lbl_key, "")
            if uri and uri not in seen:
                seen[uri] = lbl

    enriched = [{"uri": uri, "label": lbl} for uri, lbl in seen.items()]

    query = """
    UNWIND $rows AS row
    MERGE (g:GroupeCompétences {conceptUri: row.uri})
    SET   g.preferredLabel = row.label
    """
    batch_merge(driver, query, enriched, BATCH_SIZE_NODES, "GroupeComp")
    log.info(f"  → {len(enriched):,} groupes de compétences chargés")


def load_esco_relations(driver: Driver):
    """Charge toutes les relations ESCO entre nœuds déjà créés."""
    log.info("[2e] Création des relations ESCO...")

    # 2e.1 — Métier :NECESSSITE Compétence
    occ_skill_rows = read_csv_safe(ESCO_OCC_SKILLS)
    rel_rows = [{
        "occUri":      row["occupationUri"],
        "skillUri":    row["skillUri"],
        "relType":     row["relationType"],
        "skillType":   row["skillType"],
    } for row in occ_skill_rows if row.get("occupationUri") and row.get("skillUri")]

    q_necessite = """
    UNWIND $rows AS row
    MATCH (m:Métier     {conceptUri: row.occUri})
    MATCH (s:Compétence {conceptUri: row.skillUri})
    MERGE (m)-[r:NECESSITE]->(s)
    SET r.relationType = row.relType,
        r.skillType    = row.skillType
    """
    batch_merge(driver, q_necessite, rel_rows, BATCH_SIZE_RELS, ":NECESSITE")
    log.info(f"  :NECESSITE → {len(rel_rows):,} relations")

    # 2e.2 — Métier :CLASSIFIE_DANS GroupeISCO
    occ_rows = read_csv_safe(ESCO_OCCUPATIONS)
    isco_rels = [{
        "occUri":   row["conceptUri"],
        "iscoCode": row["iscoGroup"][:2] if row.get("iscoGroup") else "",
    } for row in occ_rows if row.get("conceptUri") and row.get("iscoGroup")]

    q_classifie = """
    UNWIND $rows AS row
    MATCH (m:Métier     {conceptUri: row.occUri})
    MATCH (g:GroupeISCO {code: row.iscoCode})
    MERGE (m)-[:CLASSIFIE_DANS]->(g)
    """
    batch_merge(driver, q_classifie, isco_rels, BATCH_SIZE_RELS, ":CLASSIFIE_DANS")
    log.info(f"  :CLASSIFIE_DANS → {len(isco_rels):,} relations")

    # 2e.3 — Compétence :PLUS_LARGE_QUE Compétence (hiérarchie ESCO)
    hier_rows = read_csv_safe(ESCO_SKILL_HIER)
    plq_rels = []
    for row in hier_rows:
        parent = row.get("Level 0 URI", "")
        child  = row.get("Level 1 URI", "")
        if parent and child:
            plq_rels.append({"parentUri": parent, "childUri": child})

    q_plq = """
    UNWIND $rows AS row
    MATCH (parent:Compétence {conceptUri: row.parentUri})
    MATCH (child:Compétence  {conceptUri: row.childUri})
    MERGE (parent)-[:PLUS_LARGE_QUE]->(child)
    """
    batch_merge(driver, q_plq, plq_rels, BATCH_SIZE_RELS, ":PLUS_LARGE_QUE")
    log.info(f"  :PLUS_LARGE_QUE → {len(plq_rels):,} relations")

    # 2e.4 — Compétence :PARTIE_DE GroupeCompétences
    broader_rows = read_csv_safe(ESCO_BROADER_SK)
    pde_rels = [{
        "skillUri":  row.get("conceptUri", ""),
        "groupUri":  row.get("broaderUri", ""),
    } for row in broader_rows
      if row.get("conceptUri") and row.get("broaderUri")]

    q_pde = """
    UNWIND $rows AS row
    MATCH (s:Compétence      {conceptUri: row.skillUri})
    MATCH (g:GroupeCompétences {conceptUri: row.groupUri})
    MERGE (s)-[:PARTIE_DE]->(g)
    """
    batch_merge(driver, q_pde, pde_rels, BATCH_SIZE_RELS, ":PARTIE_DE")
    log.info(f"  :PARTIE_DE → {len(pde_rels):,} relations")

    # 2e.5 — GroupeISCO :CONTIENT GroupeISCO (hiérarchie)
    isco_hier = [{"parent": c, "child": c + str(i)}
                 for c in ["0","1","2","3","4","5","6","7","8","9"]
                 for i in range(10)]
    q_isco_hier = """
    UNWIND $rows AS row
    MATCH (p:GroupeISCO {code: row.parent})
    MATCH (c:GroupeISCO {code: row.child})
    MERGE (p)-[:CONTIENT]->(c)
    """
    batch_merge(driver, q_isco_hier, isco_hier, BATCH_SIZE_RELS, "ISCO hiérarchie")


# ─────────────────────────────────────────────────────────────────────────
# ÉTAPE 3 — MEPC (3 niveaux + relations hiérarchiques + ALIGNE_AVEC ISCO)
# ─────────────────────────────────────────────────────────────────────────

def load_mepc(driver: Driver):
    log.info("[3/7] Chargement des référentiels MEPC...")

    # Grands Groupes
    df_g = pd.read_parquet(MEPC_GRANDS)
    q_grand = """
    UNWIND $rows AS row
    MERGE (g:GrandGroupeMEPC {code: row.code})
    SET g.intitule           = row.intitule,
        g.notes_explicatives = row.notes_explicatives,
        g.codes_citp         = row.codes_citp,
        g.text_to_embed      = row.text_to_embed
    """
    batch_merge(driver, q_grand, to_rows(df_g), BATCH_SIZE_NODES, "MEPC Grands")
    log.info(f"  GrandGroupeMEPC : {len(df_g)}")

    # Sous-Groupes
    df_s = pd.read_parquet(MEPC_SOUS)
    q_sous = """
    UNWIND $rows AS row
    MERGE (s:SousGroupeMEPC {code: row.code})
    SET s.intitule           = row.intitule,
        s.notes_explicatives = row.notes_explicatives,
        s.codes_citp         = row.codes_citp,
        s.code_grand_groupe  = row.code_grand_groupe,
        s.text_to_embed      = row.text_to_embed
    """
    batch_merge(driver, q_sous, to_rows(df_s), BATCH_SIZE_NODES, "MEPC Sous")
    log.info(f"  SousGroupeMEPC  : {len(df_s)}")

    # Groupes de Base
    df_b = pd.read_parquet(MEPC_BASE)
    q_base = """
    UNWIND $rows AS row
    MERGE (b:GroupeBaseMEPC {code: row.code})
    SET b.intitule           = row.intitule,
        b.notes_explicatives = row.notes_explicatives,
        b.codes_citp         = row.codes_citp,
        b.code_sous_groupe   = row.code_sous_groupe,
        b.code_grand_groupe  = row.code_grand_groupe,
        b.text_to_embed      = row.text_to_embed
    """
    batch_merge(driver, q_base, to_rows(df_b), BATCH_SIZE_NODES, "MEPC Base")
    log.info(f"  GroupeBaseMEPC  : {len(df_b)}")

    # Relations CONTIENT (hiérarchie MEPC)
    q_cont_gs = """
    UNWIND $rows AS row
    MATCH (g:GrandGroupeMEPC {code: row.code_grand_groupe})
    MATCH (s:SousGroupeMEPC  {code: row.code})
    MERGE (g)-[:CONTIENT]->(s)
    """
    batch_merge(driver, q_cont_gs, to_rows(df_s[["code","code_grand_groupe"]]),
                BATCH_SIZE_RELS, "MEPC GG→SG")

    q_cont_sb = """
    UNWIND $rows AS row
    MATCH (s:SousGroupeMEPC {code: row.code_sous_groupe})
    MATCH (b:GroupeBaseMEPC {code: row.code})
    MERGE (s)-[:CONTIENT]->(b)
    """
    batch_merge(driver, q_cont_sb, to_rows(df_b[["code","code_sous_groupe"]]),
                BATCH_SIZE_RELS, "MEPC SG→Base")

    # Relation ALIGNE_AVEC : GroupeBaseMEPC → GroupeISCO (via codes CITP)
    df_map = pd.read_parquet(MAPPING_PARQUET)
    align_rows = []
    for _, r in df_map.iterrows():
        isco = str(r.get("isco_code_mepc", ""))[:2] if r.get("isco_code_mepc") else ""
        mepc = str(r.get("mepc_code_base", ""))
        if mepc and isco:
            align_rows.append({"mepc_code": mepc, "isco_code": isco})

    # Déduplique
    align_rows = list({(r["mepc_code"], r["isco_code"]): r for r in align_rows}.values())
    q_align = """
    UNWIND $rows AS row
    MATCH (b:GroupeBaseMEPC {code: row.mepc_code})
    MATCH (g:GroupeISCO     {code: row.isco_code})
    MERGE (b)-[:ALIGNE_AVEC]->(g)
    """
    batch_merge(driver, q_align, align_rows, BATCH_SIZE_RELS, ":ALIGNE_AVEC")
    log.info(f"  :ALIGNE_AVEC MEPC→ISCO : {len(align_rows)}")

    # Relation CORRESPOND_MEPC : Métier ESCO → GroupeBaseMEPC
    corresp_rows = []
    for _, r in df_map.dropna(subset=["esco_uri","mepc_code_base"]).iterrows():
        corresp_rows.append({
            "esco_uri":  r["esco_uri"],
            "mepc_code": str(r["mepc_code_base"]),
        })
    corresp_rows = list({(r["esco_uri"], r["mepc_code"]): r for r in corresp_rows}.values())
    q_corresp = """
    UNWIND $rows AS row
    MATCH (m:Métier         {conceptUri: row.esco_uri})
    MATCH (b:GroupeBaseMEPC {code: row.mepc_code})
    MERGE (m)-[:CORRESPOND_MEPC]->(b)
    """
    batch_merge(driver, q_corresp, corresp_rows, BATCH_SIZE_RELS, ":CORRESPOND_MEPC")
    log.info(f"  :CORRESPOND_MEPC Métier→MEPC : {len(corresp_rows)}")


# ─────────────────────────────────────────────────────────────────────────
# ÉTAPE 4 — NCF (4 niveaux + relations hiérarchiques)
# ─────────────────────────────────────────────────────────────────────────

def load_ncf(driver: Driver):
    log.info("[4/7] Chargement des référentiels NCF...")

    # Niveaux
    df_n = pd.read_parquet(NCF_NIVEAUX)
    q_niv = """
    UNWIND $rows AS row
    MERGE (n:NiveauFormationNCF {code: toString(row.code)})
    SET n.intitule      = row.intitule,
        n.explication   = row.explication,
        n.text_to_embed = row.text_to_embed
    """
    batch_merge(driver, q_niv, to_rows(df_n), BATCH_SIZE_NODES, "NCF Niveaux")
    log.info(f"  NiveauFormationNCF : {len(df_n)}")

    # Grands Domaines
    df_g = pd.read_parquet(NCF_GRANDS)
    q_grand = """
    UNWIND $rows AS row
    MERGE (d:GrandDomaineNCF {code: toString(row.code)})
    SET d.intitule      = row.intitule,
        d.explication   = row.explication,
        d.text_to_embed = row.text_to_embed
    """
    batch_merge(driver, q_grand, to_rows(df_g), BATCH_SIZE_NODES, "NCF GrandDom")
    log.info(f"  GrandDomaineNCF    : {len(df_g)}")

    # Domaines Spécialisés
    df_s = pd.read_parquet(NCF_SPEC)
    q_spec = """
    UNWIND $rows AS row
    MERGE (d:DomaineSpécialiséNCF {code: toString(row.code)})
    SET d.intitule           = row.intitule,
        d.explication        = row.explication,
        d.code_grand_domaine = row.code_grand_domaine,
        d.text_to_embed      = row.text_to_embed
    """
    batch_merge(driver, q_spec, to_rows(df_s), BATCH_SIZE_NODES, "NCF DomSpec")
    log.info(f"  DomaineSpécialiséNCF : {len(df_s)}")

    # Domaines Détaillés
    df_d = pd.read_parquet(NCF_DET)
    q_det = """
    UNWIND $rows AS row
    MERGE (d:DomaineDétailléNCF {code: toString(row.code)})
    SET d.intitule           = row.intitule,
        d.explication        = row.explication,
        d.code_dom_specialise = row.code_dom_specialise,
        d.code_grand_domaine = row.code_grand_domaine,
        d.text_to_embed      = row.text_to_embed
    """
    batch_merge(driver, q_det, to_rows(df_d), BATCH_SIZE_NODES, "NCF DomDet")
    log.info(f"  DomaineDétailléNCF   : {len(df_d)}")

    # Relations :CONTIENT dans la hiérarchie NCF
    q_gd_ds = """
    UNWIND $rows AS row
    MATCH (g:GrandDomaineNCF      {code: toString(row.code_grand_domaine)})
    MATCH (s:DomaineSpécialiséNCF {code: toString(row.code)})
    MERGE (g)-[:CONTIENT]->(s)
    """
    batch_merge(driver, q_gd_ds, to_rows(df_s[["code","code_grand_domaine"]]),
                BATCH_SIZE_RELS, "NCF GD→DS")

    q_ds_dd = """
    UNWIND $rows AS row
    MATCH (s:DomaineSpécialiséNCF {code: toString(row.code_dom_specialise)})
    MATCH (d:DomaineDétailléNCF   {code: toString(row.code)})
    MERGE (s)-[:CONTIENT]->(d)
    """
    batch_merge(driver, q_ds_dd, to_rows(df_d[["code","code_dom_specialise"]]),
                BATCH_SIZE_RELS, "NCF DS→DD")

    log.info("  Hiérarchie NCF :CONTIENT créée")


# ─────────────────────────────────────────────────────────────────────────
# ÉTAPE 5 — OFFRES D'EMPLOI + nœuds contextuels
# ─────────────────────────────────────────────────────────────────────────

def load_offres(driver: Driver):
    log.info("[5/7] Chargement des Offres d'emploi...")
    df_o = pd.read_parquet(OFFRES_PARQUET)

    # 5a — Nœuds OffreEmploi
    offre_rows = []
    for _, r in df_o.iterrows():
        offre_rows.append({
            "id":                r["offre_id"],
            "source":            r.get("source"),
            "titre_poste":       r.get("titre_poste"),
            "employeur":         r.get("employeur"),
            "type_entreprise":   r.get("type_entreprise_norm"),
            "pays":              r.get("pays"),
            "ville_principale":  r.get("ville_principale"),
            "secteur_principal": r.get("secteur_principal"),
            "groupe_contrat":    r.get("groupe_contrat_norm"),
            "type_contrat":      r.get("type_contrat_norm"),
            "ncf_niveau_code":   (int(r["ncf_niveau_code"])
                                   if r.get("ncf_niveau_code") is not None
                                   else None),
            "niveau_etudes_raw": r.get("niveau_etudes_raw"),
            "experience_min_ans":(int(r["experience_min_ans"])
                                   if r.get("experience_min_ans") is not None
                                   else None),
            "skills_raw":        r.get("skills_raw"),
            "details_clean":     str(r.get("details_clean", ""))[:1000],
            "text_to_embed":     str(r.get("text_to_embed", ""))[:800],
            "metadata_str":      str(r.get("metadata_str", "")),
        })

    q_offre = """
    UNWIND $rows AS row
    MERGE (o:OffreEmploi {id: row.id})
    SET   o.source           = row.source,
          o.titre_poste      = row.titre_poste,
          o.employeur        = row.employeur,
          o.type_entreprise  = row.type_entreprise,
          o.pays             = row.pays,
          o.ville_principale = row.ville_principale,
          o.secteur_principal= row.secteur_principal,
          o.groupe_contrat   = row.groupe_contrat,
          o.type_contrat     = row.type_contrat,
          o.ncf_niveau_code  = row.ncf_niveau_code,
          o.niveau_etudes_raw= row.niveau_etudes_raw,
          o.experience_min_ans = row.experience_min_ans,
          o.skills_raw       = row.skills_raw,
          o.details_clean    = row.details_clean,
          o.text_to_embed    = row.text_to_embed,
          o.metadata_str     = row.metadata_str
    """
    batch_merge(driver, q_offre, offre_rows, BATCH_SIZE_NODES, "OffreEmploi")
    log.info(f"  OffreEmploi : {len(offre_rows):,}")

    # 5b — Nœuds contextuels : Secteur, Employeur, Localisation
    secteurs    = df_o["secteur_principal"].dropna().unique().tolist()
    employeurs  = df_o["employeur"].dropna().unique().tolist()
    villes      = df_o["ville_principale"].dropna().unique().tolist()

    q_sect = "UNWIND $rows AS row MERGE (:Secteur {label: row.label})"
    batch_merge(driver, q_sect, [{"label":s} for s in secteurs],
                BATCH_SIZE_NODES, "Secteurs")

    q_emp = "UNWIND $rows AS row MERGE (:Employeur {nom: row.nom})"
    batch_merge(driver, q_emp, [{"nom":e} for e in employeurs],
                BATCH_SIZE_NODES, "Employeurs")

    q_loc = "UNWIND $rows AS row MERGE (:Localisation {ville: row.ville})"
    batch_merge(driver, q_loc, [{"ville":v} for v in villes],
                BATCH_SIZE_NODES, "Localisations")
    log.info(f"  Secteurs:{len(secteurs)} Employeurs:{len(employeurs)} Villes:{len(villes)}")

    # 5c — Relations Offre → Secteur, Employeur, Localisation
    ctx_rows = []
    for _, r in df_o.iterrows():
        ctx_rows.append({
            "oid":      r["offre_id"],
            "secteur":  r.get("secteur_principal"),
            "employeur":r.get("employeur"),
            "ville":    r.get("ville_principale"),
            "ncf_code": (str(int(r["ncf_niveau_code"]))
                         if r.get("ncf_niveau_code") is not None
                         else None),
        })

    q_rel_ctx = """
    UNWIND $rows AS row
    MATCH (o:OffreEmploi {id: row.oid})
    WITH o, row
    WHERE row.secteur IS NOT NULL
    MATCH (s:Secteur {label: row.secteur})
    MERGE (o)-[:DANS_SECTEUR]->(s)
    WITH o, row
    WHERE row.employeur IS NOT NULL
    MATCH (e:Employeur {nom: row.employeur})
    MERGE (o)-[:PUBLIEE_PAR]->(e)
    WITH o, row
    WHERE row.ville IS NOT NULL
    MATCH (l:Localisation {ville: row.ville})
    MERGE (o)-[:LOCALISEE_A]->(l)
    """
    # Exécuter relation par relation pour éviter les problèmes de WITH chaîné
    for rel_q, rel_name in [
        ("UNWIND $rows AS row MATCH (o:OffreEmploi {id: row.oid}) WHERE row.secteur IS NOT NULL MATCH (s:Secteur {label: row.secteur}) MERGE (o)-[:DANS_SECTEUR]->(s)", ":DANS_SECTEUR"),
        ("UNWIND $rows AS row MATCH (o:OffreEmploi {id: row.oid}) WHERE row.employeur IS NOT NULL MATCH (e:Employeur {nom: row.employeur}) MERGE (o)-[:PUBLIEE_PAR]->(e)", ":PUBLIEE_PAR"),
        ("UNWIND $rows AS row MATCH (o:OffreEmploi {id: row.oid}) WHERE row.ville IS NOT NULL MATCH (l:Localisation {ville: row.ville}) MERGE (o)-[:LOCALISEE_A]->(l)", ":LOCALISEE_A"),
        ("UNWIND $rows AS row MATCH (o:OffreEmploi {id: row.oid}) WHERE row.ncf_code IS NOT NULL MATCH (n:NiveauFormationNCF {code: row.ncf_code}) MERGE (o)-[:REQUIERT_NIVEAU]->(n)", ":REQUIERT_NIVEAU"),
    ]:
        batch_merge(driver, rel_q, ctx_rows, BATCH_SIZE_RELS, rel_name)
    log.info("  Relations offre contextuelles créées")


# ─────────────────────────────────────────────────────────────────────────
# ÉTAPE 6 — CANDIDATS
# ─────────────────────────────────────────────────────────────────────────

def load_candidats(driver: Driver):
    log.info("[6/7] Chargement des Candidats...")
    df_c = pd.read_parquet(CANDIDATS_PARQUET)

    cand_rows = []
    for _, r in df_c.iterrows():
        cand_rows.append({
            "id":               str(r["candidat_id"]),
            "age":              (int(r["age"]) if r.get("age") is not None else None),
            "genre":            r.get("genre"),
            "diplome_raw":      r.get("diplome_raw"),
            "ncf_niveau_final": (int(r["ncf_niveau_final"])
                                  if r.get("ncf_niveau_final") is not None
                                  else None),
            "qualification":    r.get("qualification_metier"),
            "secteur_metier":   r.get("secteur_metier"),
            "filiere":          r.get("filiere_specialite"),
            "secteur_demande":  r.get("secteur_demande"),
            "metier_vise":      r.get("metier_vise"),
            "objectif":         str(r.get("objectif", "") or "")[:300],
            "mobilite_geo":     bool(r["mobilite_geo_bool"])
                                 if r.get("mobilite_geo_bool") is not None
                                 else None,
            "ncf_code_str":     (str(int(r["ncf_niveau_final"]))
                                  if r.get("ncf_niveau_final") is not None
                                  else None),
            "text_to_embed":    str(r.get("text_to_embed", ""))[:400],
        })

    q_cand = """
    UNWIND $rows AS row
    MERGE (c:Candidat {id: row.id})
    SET   c.age              = row.age,
          c.genre            = row.genre,
          c.diplome_raw      = row.diplome_raw,
          c.ncf_niveau_final = row.ncf_niveau_final,
          c.qualification    = row.qualification,
          c.secteur_metier   = row.secteur_metier,
          c.filiere_specialite = row.filiere,
          c.secteur_demande  = row.secteur_demande,
          c.metier_vise      = row.metier_vise,
          c.objectif         = row.objectif,
          c.mobilite_geo_bool = row.mobilite_geo,
          c.text_to_embed    = row.text_to_embed
    """
    batch_merge(driver, q_cand, cand_rows, BATCH_SIZE_NODES, "Candidats")
    log.info(f"  Candidat : {len(cand_rows):,}")

    # Relations Candidat → NiveauFormationNCF (:A_NIVEAU)
    ncf_rels = [{"cid": r["id"], "ncf": r["ncf_code_str"]}
                for r in cand_rows if r.get("ncf_code_str")]
    q_aniveau = """
    UNWIND $rows AS row
    MATCH (c:Candidat           {id: row.cid})
    MATCH (n:NiveauFormationNCF {code: row.ncf})
    MERGE (c)-[:A_NIVEAU]->(n)
    """
    batch_merge(driver, q_aniveau, ncf_rels, BATCH_SIZE_RELS, ":A_NIVEAU")

    # Relations Candidat → Localisation (si disponible)
    loc_rels = []
    for _, r in df_c.iterrows():
        # Utiliser secteur_metier comme localisation approximative si département absent
        dept = r.get("secteur_activite_cand")  # ex: "Yaoundé"
        if dept and isinstance(dept, str):
            loc_rels.append({"cid": str(r["candidat_id"]), "ville": dept})

    log.info(f"  :A_NIVEAU → {len(ncf_rels)} relations")


# ─────────────────────────────────────────────────────────────────────────
# ÉTAPE 7 — RELATIONS INTER-ENTITÉS COMPLÉMENTAIRES
# ─────────────────────────────────────────────────────────────────────────

def load_relations_complementaires(driver: Driver):
    log.info("[7/7] Création des relations complémentaires...")

    df_o = pd.read_parquet(OFFRES_PARQUET)
    df_c = pd.read_parquet(CANDIDATS_PARQUET)

    # 7a — OffreEmploi :CORRESPOND_METIER Métier
    # Matcher le titre du poste vers un métier ESCO via la propriété iscoCode
    # (relation approximative à affiner par LLM dans le module 05)
    # Ici on lie via le secteur → métiers du même secteur NCF
    ncf_match = []
    for _, r in df_o.dropna(subset=["ncf_niveau_code"]).iterrows():
        ncf_match.append({
            "oid":      r["offre_id"],
            "ncf_code": str(int(r["ncf_niveau_code"])),
        })
    q_ncf_match = """
    UNWIND $rows AS row
    MATCH (o:OffreEmploi        {id: row.oid})
    MATCH (n:NiveauFormationNCF {code: row.ncf_code})
    MERGE (o)-[:REQUIERT_NIVEAU_NCF]->(n)
    """
    batch_merge(driver, q_ncf_match, ncf_match, BATCH_SIZE_RELS, "Offre→NCF niveau")
    log.info(f"  :REQUIERT_NIVEAU_NCF → {len(ncf_match)} relations offre→NCF")

    # 7b — Candidat :A_FORMATION DomaineDétailléNCF
    # Mapper filiere_specialite → code NCF via la table NCF si possible
    df_ncf_d = pd.read_parquet(NCF_DET)
    filiere_ncf_map = {}
    for _, r in df_ncf_d.iterrows():
        label_low = str(r.get("intitule", "")).lower()
        filiere_ncf_map[label_low] = str(r["code"])

    form_rels = []
    for _, r in df_c.dropna(subset=["filiere_specialite"]).iterrows():
        filiere = str(r["filiere_specialite"]).lower()
        # Recherche approximative sur les 20 premiers chars
        for key, code in filiere_ncf_map.items():
            if filiere[:15] in key or key[:15] in filiere:
                form_rels.append({"cid": str(r["candidat_id"]), "ncf_code": code})
                break

    if form_rels:
        q_aform = """
        UNWIND $rows AS row
        MATCH (c:Candidat           {id: row.cid})
        MATCH (d:DomaineDétailléNCF {code: row.ncf_code})
        MERGE (c)-[:A_FORMATION]->(d)
        """
        batch_merge(driver, q_aform, form_rels, BATCH_SIZE_RELS, ":A_FORMATION")
        log.info(f"  :A_FORMATION → {len(form_rels)} candidats liés à NCF détaillé")

    # 7c — DomaineDétailléNCF :PREPARE_POUR Métier
    # Lien formation → métier via le code ISCO partagé (domaine NCF → ISCO à 2 chiffres)
    # Mapping manuel approximatif (à enrichir avec LLM dans module 05)
    NCF_GRAND_TO_ISCO = {
        "01": "2",   "02": "2",   "03": "2",   "04": "1",
        "05": "2",   "06": "2",   "07": "2",   "08": "6",
        "09": "3",   "10": "5",
    }
    prep_rels = []
    for _, dd in df_ncf_d.iterrows():
        grand_code = str(dd.get("code_grand_domaine", ""))[:2]
        isco_1 = NCF_GRAND_TO_ISCO.get(grand_code)
        if not isco_1: continue
        prep_rels.append({"ncf_code": str(dd["code"]), "isco_prefix": isco_1})

    q_prep = """
    UNWIND $rows AS row
    MATCH (d:DomaineDétailléNCF {code: row.ncf_code})
    MATCH (m:Métier) WHERE m.iscoCode STARTS WITH row.isco_prefix
    WITH d, m LIMIT 5
    MERGE (d)-[:PREPARE_POUR]->(m)
    """
    batch_merge(driver, q_prep, prep_rels[:50], BATCH_SIZE_RELS, ":PREPARE_POUR")
    log.info(f"  :PREPARE_POUR DomNCF→Métier (échantillon 50 domaines)")

    log.info("  Relations complémentaires terminées")


# ─────────────────────────────────────────────────────────────────────────
# VALIDATION DU GRAPHE
# ─────────────────────────────────────────────────────────────────────────

def validate_graph(driver: Driver) -> dict:
    """Exécute des requêtes de validation et retourne les statistiques."""
    log.info("\nValidation du graphe...")
    queries = {
        "Candidats":              "MATCH (c:Candidat)       RETURN count(c) AS n",
        "OffreEmploi":            "MATCH (o:OffreEmploi)    RETURN count(o) AS n",
        "Compétences":            "MATCH (s:Compétence)     RETURN count(s) AS n",
        "Métiers":                "MATCH (m:Métier)         RETURN count(m) AS n",
        "GroupeISCO":             "MATCH (g:GroupeISCO)     RETURN count(g) AS n",
        "GrandGroupeMEPC":        "MATCH (g:GrandGroupeMEPC) RETURN count(g) AS n",
        "SousGroupeMEPC":         "MATCH (g:SousGroupeMEPC)  RETURN count(g) AS n",
        "GroupeBaseMEPC":         "MATCH (g:GroupeBaseMEPC)  RETURN count(g) AS n",
        "NiveauFormationNCF":     "MATCH (n:NiveauFormationNCF)    RETURN count(n) AS n",
        "GrandDomaineNCF":        "MATCH (d:GrandDomaineNCF)       RETURN count(d) AS n",
        "DomaineSpécialiséNCF":   "MATCH (d:DomaineSpécialiséNCF)  RETURN count(d) AS n",
        "DomaineDétailléNCF":     "MATCH (d:DomaineDétailléNCF)    RETURN count(d) AS n",
        "Secteurs":               "MATCH (s:Secteur)        RETURN count(s) AS n",
        "Employeurs":             "MATCH (e:Employeur)      RETURN count(e) AS n",
        "Localisations":          "MATCH (l:Localisation)   RETURN count(l) AS n",
        "Rel :NECESSITE":         "MATCH ()-[r:NECESSITE]->()         RETURN count(r) AS n",
        "Rel :CLASSIFIE_DANS":    "MATCH ()-[r:CLASSIFIE_DANS]->()    RETURN count(r) AS n",
        "Rel :PLUS_LARGE_QUE":    "MATCH ()-[r:PLUS_LARGE_QUE]->()   RETURN count(r) AS n",
        "Rel :CORRESPOND_MEPC":   "MATCH ()-[r:CORRESPOND_MEPC]->()   RETURN count(r) AS n",
        "Rel :ALIGNE_AVEC":       "MATCH ()-[r:ALIGNE_AVEC]->()       RETURN count(r) AS n",
        "Rel :CONTIENT (MEPC)":   "MATCH (:GrandGroupeMEPC)-[r:CONTIENT]->() RETURN count(r) AS n",
        "Rel :CONTIENT (NCF)":    "MATCH (:GrandDomaineNCF)-[r:CONTIENT]->() RETURN count(r) AS n",
        "Rel :A_NIVEAU":          "MATCH ()-[r:A_NIVEAU]->()          RETURN count(r) AS n",
        "Rel :DANS_SECTEUR":      "MATCH ()-[r:DANS_SECTEUR]->()      RETURN count(r) AS n",
        "Rel :PUBLIEE_PAR":       "MATCH ()-[r:PUBLIEE_PAR]->()       RETURN count(r) AS n",
    }

    stats = {}
    log.info(f"\n{'Entité/Relation':<30} {'Compte':>10}")
    log.info("-" * 42)
    for label, query in queries.items():
        with driver.session(database=NEO4J_DATABASE) as session:
            result = session.run(query)
            n = result.single()["n"]
            stats[label] = n
            log.info(f"  {label:<28} {n:>10,}")

    return stats


# ─────────────────────────────────────────────────────────────────────────
# ORCHESTRATEUR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────

STEPS = {
    "schema":    create_schema,
    "esco":      lambda d: [load_esco_skills(d), load_esco_occupations(d),
                             load_esco_isco(d), load_esco_skill_groups(d),
                             load_esco_relations(d)],
    "mepc":      load_mepc,
    "ncf":       load_ncf,
    "offres":    load_offres,
    "candidats": load_candidats,
    "relations": load_relations_complementaires,
}


def run(step: str = None, dry_run: bool = False, clear: bool = False):
    log.info("=" * 65)
    log.info("MODULE 03 — CHARGEMENT DU GRAPHE DE CONNAISSANCES NEO4J")
    log.info("=" * 65)

    if dry_run:
        log.info("[DRY-RUN] Validation sans écriture dans Neo4j")
        log.info("  Données disponibles :")
        log.info(f"    Offres    : {pd.read_parquet(OFFRES_PARQUET).shape}")
        log.info(f"    Candidats : {pd.read_parquet(CANDIDATS_PARQUET).shape}")
        log.info(f"    Mapping   : {pd.read_parquet(MAPPING_PARQUET).shape}")
        return

    driver = get_driver()

    if clear:
        log.warning("SUPPRESSION DE TOUS LES NŒUDS ET RELATIONS...")
        run_query(driver, "MATCH (n) DETACH DELETE n")
        log.info("  Base vidée.")

    t0 = time.time()

    if step:
        fn = STEPS.get(step)
        if not fn:
            log.error(f"Étape inconnue : {step}. Options : {list(STEPS.keys())}")
            return
        log.info(f"Exécution de l'étape : {step}")
        fn(driver)
    else:
        log.info("Exécution du pipeline complet (7 étapes)")
        for step_name, fn in STEPS.items():
            log.info(f"\n{'='*50}")
            t_step = time.time()
            fn(driver)
            log.info(f"  ✓ {step_name} terminé en {time.time()-t_step:.1f}s")

    # Validation finale
    stats = validate_graph(driver)

    elapsed = time.time() - t0
    log.info(f"\n✓ Pipeline Neo4j terminé en {elapsed:.1f}s")

    driver.close()
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Module 03 — Chargement Neo4j"
    )
    parser.add_argument("--step",    type=str, choices=list(STEPS.keys()),
                        help="Exécuter une seule étape")
    parser.add_argument("--dry-run", action="store_true",
                        help="Valider sans écrire")
    parser.add_argument("--clear",   action="store_true",
                        help="Vider la base avant chargement")
    args = parser.parse_args()
    run(step=args.step, dry_run=args.dry_run, clear=args.clear)


if __name__ == "__main__":
    main()
