"""
queries_cypher.py
===========================================================================
Module 03 — Bibliothèque de requêtes Cypher

Toutes les requêtes Cypher utilisées dans le projet :
  - Requêtes de validation du graphe
  - Requêtes de skill gap (calcul d'écart de compétences)
  - Requêtes de matching offre-candidat
  - Requêtes de recommandation (filtrages contextuels)
  - Requêtes de chemin NCF → métier (pour la roadmap)
  - Requêtes analytiques du marché du travail

Ces requêtes sont utilisées par le module 05 (GraphRAG) et le module 06 (FastAPI).
===========================================================================
"""

# ─────────────────────────────────────────────────────────────────────────
# REQUÊTES DE VALIDATION
# ─────────────────────────────────────────────────────────────────────────

Q_COUNT_ALL_NODES = """
CALL apoc.meta.stats() YIELD labels
RETURN labels
"""

Q_SCHEMA_OVERVIEW = """
CALL db.schema.visualization()
"""

Q_COUNT_NODE = """
MATCH (n:{label}) RETURN count(n) AS total
"""

Q_SAMPLE_OFFRE = """
MATCH (o:OffreEmploi)
RETURN o.id, o.titre_poste, o.employeur, o.ville_principale,
       o.secteur_principal, o.ncf_niveau_code, o.type_contrat
LIMIT 5
"""

Q_SAMPLE_CANDIDAT = """
MATCH (c:Candidat)
RETURN c.id, c.metier_vise, c.secteur_metier, c.ncf_niveau_final,
       c.filiere_specialite, c.mobilite_geo_bool
LIMIT 5
"""

Q_VERIFY_ESCO_LINKS = """
MATCH (m:Métier)-[:NECESSITE]->(s:Compétence)
RETURN m.preferredLabel AS metier,
       count(s) AS n_competences
ORDER BY n_competences DESC
LIMIT 10
"""

Q_VERIFY_MEPC_HIERARCHY = """
MATCH path = (g:GrandGroupeMEPC)-[:CONTIENT]->(s:SousGroupeMEPC)
              -[:CONTIENT]->(b:GroupeBaseMEPC)
RETURN g.code AS grand, g.intitule AS grand_label,
       s.code AS sous, count(b) AS n_base
ORDER BY grand, sous
LIMIT 15
"""

Q_VERIFY_NCF_HIERARCHY = """
MATCH path = (g:GrandDomaineNCF)-[:CONTIENT*1..2]->(d:DomaineDétailléNCF)
RETURN g.code, g.intitule, count(d) AS n_details
ORDER BY n_details DESC LIMIT 10
"""


# ─────────────────────────────────────────────────────────────────────────
# SKILL GAP — CALCUL D'ÉCART DE COMPÉTENCES
# ─────────────────────────────────────────────────────────────────────────

Q_SKILL_GAP_EXACT = """
// Skill gap exact : compétences requises par l'offre vs possédées par le candidat
MATCH (c:Candidat   {id: $candidat_id})-[:POSSEDE]->(sc:Compétence)
MATCH (o:OffreEmploi{id: $offre_id   })-[r:REQUIERT]->(sr:Compétence)
WITH collect(DISTINCT sc.conceptUri) AS cand_skills,
     collect(DISTINCT sr.conceptUri) AS offre_skills,
     collect(DISTINCT CASE WHEN r.relationType = 'essential'
             THEN sr.conceptUri END) AS essential_skills,
     collect(DISTINCT {uri: sr.conceptUri, label: sr.preferredLabel,
             type: r.relationType}) AS offre_detail
RETURN
  [x IN offre_skills WHERE x IN cand_skills] AS acquises,
  [x IN offre_skills WHERE NOT x IN cand_skills] AS manquantes,
  [x IN essential_skills WHERE NOT x IN cand_skills] AS essentielles_manquantes,
  toFloat(size([x IN offre_skills WHERE x IN cand_skills])) /
    CASE WHEN size(offre_skills) > 0 THEN size(offre_skills) ELSE 1 END AS taux_matching,
  size(offre_skills) AS n_requises,
  size(essential_skills) AS n_essentielles
"""

Q_SKILL_GAP_HIERARCHIQUE = """
// Skill gap hiérarchique : compétences parentes possédées (PLUS_LARGE_QUE)
MATCH (c:Candidat   {id: $candidat_id})-[:POSSEDE]->(sc:Compétence)
MATCH (o:OffreEmploi{id: $offre_id   })-[:REQUIERT]->(sr:Compétence)
WHERE NOT EXISTS {
    MATCH (c)-[:POSSEDE]->(sr)
}
WITH sc, sr
MATCH path = (sc)-[:PLUS_LARGE_QUE*1..3]->(sr)
RETURN sc.preferredLabel AS comp_candidat,
       sr.preferredLabel AS comp_requise,
       length(path)      AS distance_hierarchique
ORDER BY distance_hierarchique
LIMIT 20
"""

Q_SKILL_GAP_FULL = """
// Skill gap complet : exact + hiérarchique + métadonnées
MATCH (c:Candidat   {id: $candidat_id})-[:POSSEDE]->(sc:Compétence)
MATCH (o:OffreEmploi{id: $offre_id   })-[r:REQUIERT]->(sr:Compétence)
WITH c, o,
     collect(DISTINCT {uri:sc.conceptUri, label:sc.preferredLabel}) AS cand_skills,
     collect(DISTINCT {uri:sr.conceptUri, label:sr.preferredLabel,
             type:r.relationType, skillType:r.skillType}) AS offre_skills
WITH c, o, cand_skills, offre_skills,
     [x IN offre_skills WHERE x.uri IN [y IN cand_skills | y.uri]] AS acquises,
     [x IN offre_skills WHERE NOT x.uri IN [y IN cand_skills | y.uri]] AS manquantes
RETURN
  o.titre_poste                                          AS titre_offre,
  o.employeur                                            AS employeur,
  o.secteur_principal                                    AS secteur,
  o.ville_principale                                     AS ville,
  acquises                                               AS competences_acquises,
  manquantes                                             AS competences_manquantes,
  [x IN manquantes WHERE x.type = 'essential'] AS essentielles_manquantes,
  toFloat(size(acquises)) / size(offre_skills) AS taux_matching,
  size(offre_skills)                           AS n_total_requises,
  size(acquises)                               AS n_acquises,
  size(manquantes)                             AS n_manquantes
"""


# ─────────────────────────────────────────────────────────────────────────
# RECOMMANDATION — FILTRAGE CONTEXTUEL (PRÉ-FILTRE AVANT pgvector)
# ─────────────────────────────────────────────────────────────────────────

Q_OFFRES_COMPATIBLES = """
// Offres compatibles avec un candidat (filtre dur sur NCF + secteur + mobilité)
MATCH (c:Candidat {id: $candidat_id})
MATCH (o:OffreEmploi)
WHERE
  // Compatibilité niveau d'études (offre requiert NCF <= candidat)
  (o.ncf_niveau_code IS NULL OR
   c.ncf_niveau_final IS NULL OR
   o.ncf_niveau_code <= c.ncf_niveau_final)
  // Compatibilité secteur (si candidat a exprimé une préférence)
  AND (c.secteur_demande IS NULL OR
       o.secteur_principal = c.secteur_demande OR
       c.secteur_demande CONTAINS o.secteur_principal)
  // Compatibilité géographique (si candidat non mobile → même ville)
  AND (c.mobilite_geo_bool IS NULL OR
       c.mobilite_geo_bool = true OR
       o.ville_principale IS NULL OR
       o.ville_principale = 'Cameroun (ville non précisée)')
RETURN o.id           AS offre_id,
       o.titre_poste  AS titre,
       o.employeur    AS employeur,
       o.secteur_principal AS secteur,
       o.ville_principale  AS ville,
       o.ncf_niveau_code   AS niveau_requis
ORDER BY o.ncf_niveau_code DESC
LIMIT $limit
"""

Q_SCORING_GRAPHE = """
// Score graphe pour une paire (candidat, offre)
// Calcule : taux matching exact + bonus hiérarchique
MATCH (c:Candidat   {id: $candidat_id})-[:POSSEDE]->(sc:Compétence)
MATCH (o:OffreEmploi{id: $offre_id   })-[r:REQUIERT]->(sr:Compétence)
WITH collect(DISTINCT sc.conceptUri) AS cand_uris,
     collect(DISTINCT sr.conceptUri) AS offre_uris,
     collect(DISTINCT CASE WHEN r.relationType='essential'
             THEN sr.conceptUri END) AS ess_uris,
     count(DISTINCT sr) AS n_total
WITH cand_uris, offre_uris, ess_uris, n_total,
     [x IN offre_uris WHERE x IN cand_uris] AS communs,
     [x IN ess_uris WHERE NOT x IN cand_uris] AS ess_manquantes
WITH cand_uris, communs, ess_manquantes, n_total,
     toFloat(size(communs)) / CASE WHEN n_total > 0 THEN n_total ELSE 1 END AS taux_exact,
     toFloat(size(ess_manquantes)) / CASE WHEN size(ess_uris) > 0
             THEN size(ess_uris) ELSE 1 END AS taux_ess_manquantes
RETURN
  taux_exact AS score_matching_exact,
  (1.0 - taux_ess_manquantes) * 0.8 AS score_essentielles,
  taux_exact * 0.7 + (1.0 - taux_ess_manquantes) * 0.3 AS score_graphe,
  size(communs) AS n_communs,
  size(ess_manquantes) AS n_essentielles_manquantes
"""


# ─────────────────────────────────────────────────────────────────────────
# CHEMIN DE FORMATION (pour la génération de roadmap)
# ─────────────────────────────────────────────────────────────────────────

Q_CHEMIN_FORMATION = """
// Chemin de formation NCF vers le métier cible de l'offre
MATCH (c:Candidat {id: $candidat_id})-[:A_NIVEAU]->(n:NiveauFormationNCF)
MATCH (o:OffreEmploi {id: $offre_id})-[:CORRESPOND_METIER]->(m:Métier)
OPTIONAL MATCH path = (d:DomaineDétailléNCF)-[:PREPARE_POUR]->(m)
RETURN
  n.code       AS niveau_candidat,
  n.intitule   AS niveau_label,
  m.preferredLabel AS metier_cible,
  m.conceptUri     AS metier_uri,
  collect(DISTINCT d.intitule) AS formations_menant_au_metier,
  collect(DISTINCT d.code)     AS codes_ncf_formations
LIMIT 5
"""

Q_COMPETENCES_A_ACQUERIR = """
// Liste ordonnée des compétences manquantes avec contexte pour la roadmap
MATCH (o:OffreEmploi{id: $offre_id})-[r:REQUIERT]->(sr:Compétence)
WHERE NOT EXISTS {
    MATCH (c:Candidat {id: $candidat_id})-[:POSSEDE]->(sr)
}
RETURN sr.conceptUri    AS uri,
       sr.preferredLabel AS label,
       sr.skillType     AS type_competence,
       sr.description   AS description,
       sr.isDigital     AS is_digital,
       sr.isGreen       AS is_green,
       r.relationType   AS importance,
       CASE r.relationType
         WHEN 'essential' THEN 1
         ELSE 2 END       AS priorite
ORDER BY priorite, sr.skillType
"""

Q_COMPETENCES_PROCHES = """
// Compétences proches de celles manquantes (pour suggestions partielles)
MATCH (o:OffreEmploi{id: $offre_id})-[:REQUIERT]->(sr:Compétence)
WHERE NOT EXISTS { MATCH (c:Candidat {id: $candidat_id})-[:POSSEDE]->(sr) }
MATCH (c:Candidat {id: $candidat_id})-[:POSSEDE]->(sc:Compétence)
MATCH (sc)-[:PLUS_LARGE_QUE*1..2]->(proche:Compétence)
WHERE proche.conceptUri = sr.conceptUri
RETURN sc.preferredLabel AS comp_possedee,
       sr.preferredLabel AS comp_requise,
       'partial_match'   AS type_match
LIMIT 20
"""


# ─────────────────────────────────────────────────────────────────────────
# ANALYSE DU MARCHÉ DU TRAVAIL (requêtes analytiques)
# ─────────────────────────────────────────────────────────────────────────

Q_TOP_COMPETENCES_OFFRES = """
// Top 20 compétences les plus demandées dans les offres
MATCH (o:OffreEmploi)-[:REQUIERT]->(s:Compétence)
RETURN s.preferredLabel AS competence,
       s.skillType      AS type,
       count(o)         AS n_offres
ORDER BY n_offres DESC
LIMIT 20
"""

Q_COMPETENCES_PAR_SECTEUR = """
// Compétences les plus demandées par secteur
MATCH (o:OffreEmploi)-[:DANS_SECTEUR]->(sect:Secteur)
MATCH (o)-[:REQUIERT]->(s:Compétence)
WHERE sect.label = $secteur
RETURN s.preferredLabel AS competence,
       count(o) AS n_offres
ORDER BY n_offres DESC LIMIT 15
"""

Q_METIERS_PAR_SECTEUR = """
// Distribution des métiers ESCO demandés par secteur
MATCH (o:OffreEmploi)-[:DANS_SECTEUR]->(sect:Secteur)
MATCH (o)-[:CORRESPOND_METIER]->(m:Métier)
RETURN sect.label AS secteur,
       m.preferredLabel AS metier,
       count(o) AS n_offres
ORDER BY secteur, n_offres DESC
"""

Q_GAPS_FREQUENTS = """
// Compétences les plus souvent manquantes (tous candidats confondus)
MATCH (o:OffreEmploi)-[:REQUIERT]->(sr:Compétence)
WHERE NOT EXISTS {
    MATCH (:Candidat)-[:POSSEDE]->(sr)
}
RETURN sr.preferredLabel AS competence_manquante,
       sr.skillType      AS type,
       count(o)          AS n_offres_affectees
ORDER BY n_offres_affectees DESC
LIMIT 20
"""

Q_PROFIL_CANDIDATS = """
// Distribution des niveaux NCF dans la base candidats
MATCH (c:Candidat)-[:A_NIVEAU]->(n:NiveauFormationNCF)
RETURN n.code    AS code_ncf,
       n.intitule AS niveau,
       count(c)  AS n_candidats
ORDER BY code_ncf
"""


# ─────────────────────────────────────────────────────────────────────────
# FILTRAGE COLLABORATIF (similarité entre candidats)
# ─────────────────────────────────────────────────────────────────────────

Q_CANDIDATS_SIMILAIRES = """
// Candidats partageant le plus de compétences (pour le filtrage collaboratif)
MATCH (c1:Candidat {id: $candidat_id})-[:POSSEDE]->(s:Compétence)
MATCH (c2:Candidat)-[:POSSEDE]->(s)
WHERE c2.id <> $candidat_id
WITH c2, count(s) AS n_commun
MATCH (c1:Candidat {id: $candidat_id})
OPTIONAL MATCH (c1)-[:POSSEDE]->(s1:Compétence)
WITH c2, n_commun, count(DISTINCT s1) AS n_c1
OPTIONAL MATCH (c2)-[:POSSEDE]->(s2:Compétence)
WITH c2, n_commun, n_c1, count(DISTINCT s2) AS n_c2
RETURN c2.id AS candidat_similaire,
       n_commun AS skills_communes,
       toFloat(n_commun) / (n_c1 + n_c2 - n_commun) AS jaccard_score
ORDER BY jaccard_score DESC
LIMIT $top_k
"""

Q_OFFRES_APRECIES_PAR_SIMILAIRES = """
// Offres appréciées par des candidats similaires (filtrage collaboratif)
MATCH (c1:Candidat {id: $candidat_id})-[:POSSEDE]->(s:Compétence)
MATCH (c2:Candidat)-[:POSSEDE]->(s)
WHERE c2.id <> $candidat_id
WITH c2, count(s) AS score ORDER BY score DESC LIMIT 10
MATCH (c2)-[p:POSTULE]->(o:OffreEmploi)
WHERE p.score_hybride >= 0.6
RETURN o.id AS offre_id,
       o.titre_poste AS titre,
       avg(p.score_hybride) AS score_moyen,
       count(c2) AS n_candidats_similaires
ORDER BY score_moyen DESC
LIMIT 20
"""
