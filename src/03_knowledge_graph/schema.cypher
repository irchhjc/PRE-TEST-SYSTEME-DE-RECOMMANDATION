// ============================================================
// schema.cypher
// Module 03 — Schéma Neo4j : contraintes et index
// Système de recommandation emploi-compétences · Cameroun
//
// Exécution :
//   cypher-shell -u neo4j -p password < schema.cypher
//   ou via Neo4j Browser / Python driver (load_neo4j.py)
// ============================================================


// ── CONTRAINTES D'UNICITÉ (garantissent l'idempotence des MERGE) ──────────

CREATE CONSTRAINT candidat_id IF NOT EXISTS
  FOR (c:Candidat)        REQUIRE c.id           IS UNIQUE;

CREATE CONSTRAINT offre_id IF NOT EXISTS
  FOR (o:OffreEmploi)     REQUIRE o.id           IS UNIQUE;

CREATE CONSTRAINT competence_uri IF NOT EXISTS
  FOR (s:Compétence)      REQUIRE s.conceptUri   IS UNIQUE;

CREATE CONSTRAINT metier_uri IF NOT EXISTS
  FOR (m:Métier)          REQUIRE m.conceptUri   IS UNIQUE;

CREATE CONSTRAINT groupe_comp_uri IF NOT EXISTS
  FOR (g:GroupeCompétences) REQUIRE g.conceptUri IS UNIQUE;

CREATE CONSTRAINT isco_code IF NOT EXISTS
  FOR (g:GroupeISCO)      REQUIRE g.code         IS UNIQUE;

CREATE CONSTRAINT mepc_grand_code IF NOT EXISTS
  FOR (g:GrandGroupeMEPC) REQUIRE g.code         IS UNIQUE;

CREATE CONSTRAINT mepc_sous_code IF NOT EXISTS
  FOR (g:SousGroupeMEPC)  REQUIRE g.code         IS UNIQUE;

CREATE CONSTRAINT mepc_base_code IF NOT EXISTS
  FOR (g:GroupeBaseMEPC)  REQUIRE g.code         IS UNIQUE;

CREATE CONSTRAINT ncf_niveau_code IF NOT EXISTS
  FOR (n:NiveauFormationNCF) REQUIRE n.code      IS UNIQUE;

CREATE CONSTRAINT ncf_grand_code IF NOT EXISTS
  FOR (d:GrandDomaineNCF)    REQUIRE d.code      IS UNIQUE;

CREATE CONSTRAINT ncf_spec_code IF NOT EXISTS
  FOR (d:DomaineSpécialiséNCF) REQUIRE d.code    IS UNIQUE;

CREATE CONSTRAINT ncf_det_code IF NOT EXISTS
  FOR (d:DomaineDétailléNCF) REQUIRE d.code      IS UNIQUE;

CREATE CONSTRAINT secteur_label IF NOT EXISTS
  FOR (s:Secteur)         REQUIRE s.label        IS UNIQUE;

CREATE CONSTRAINT employeur_nom IF NOT EXISTS
  FOR (e:Employeur)       REQUIRE e.nom          IS UNIQUE;

CREATE CONSTRAINT localisation_ville IF NOT EXISTS
  FOR (l:Localisation)    REQUIRE l.ville        IS UNIQUE;


// ── INDEX DE PERFORMANCE ─────────────────────────────────────────────────

// Index sur les propriétés fréquemment filtrées
CREATE INDEX competence_type IF NOT EXISTS
  FOR (c:Compétence) ON (c.skillType);

CREATE INDEX competence_pillar IF NOT EXISTS
  FOR (c:Compétence) ON (c.pillar);

CREATE INDEX competence_digital IF NOT EXISTS
  FOR (c:Compétence) ON (c.isDigital);

CREATE INDEX competence_green IF NOT EXISTS
  FOR (c:Compétence) ON (c.isGreen);

CREATE INDEX metier_isco IF NOT EXISTS
  FOR (m:Métier) ON (m.iscoCode);

CREATE INDEX metier_mepc IF NOT EXISTS
  FOR (m:Métier) ON (m.mepc_base);

CREATE INDEX offre_secteur IF NOT EXISTS
  FOR (o:OffreEmploi) ON (o.secteur_principal);

CREATE INDEX offre_date IF NOT EXISTS
  FOR (o:OffreEmploi) ON (o.date_publication);

CREATE INDEX offre_ncf IF NOT EXISTS
  FOR (o:OffreEmploi) ON (o.ncf_niveau_code);

CREATE INDEX offre_ville IF NOT EXISTS
  FOR (o:OffreEmploi) ON (o.ville_principale);

CREATE INDEX candidat_secteur IF NOT EXISTS
  FOR (c:Candidat) ON (c.secteur_metier);

CREATE INDEX candidat_ncf IF NOT EXISTS
  FOR (c:Candidat) ON (c.ncf_niveau_final);

CREATE INDEX candidat_mobilite IF NOT EXISTS
  FOR (c:Candidat) ON (c.mobilite_geo_bool);


// ── INDEX FULLTEXT (recherche textuelle rapide) ───────────────────────────

CREATE FULLTEXT INDEX competence_ft IF NOT EXISTS
  FOR (c:Compétence)
  ON EACH [c.preferredLabel, c.description];

CREATE FULLTEXT INDEX metier_ft IF NOT EXISTS
  FOR (m:Métier)
  ON EACH [m.preferredLabel, m.description];

CREATE FULLTEXT INDEX offre_ft IF NOT EXISTS
  FOR (o:OffreEmploi)
  ON EACH [o.titre_poste, o.details_clean];

CREATE FULLTEXT INDEX ncf_ft IF NOT EXISTS
  FOR (d:DomaineDétailléNCF)
  ON EACH [d.intitule, d.explication];
