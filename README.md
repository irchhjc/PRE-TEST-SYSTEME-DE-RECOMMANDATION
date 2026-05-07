# PRE-TEST-SYSTEME-DE-RECOMMANDATION
Ce repos est dédié pour la conception d'un système de recommandation hybride pour le matching emploi-competence au Cameroun.


## Introduction

## Structure du projet

```text
PRE-TEST-SYSTEME-DE-RECOMMANDATION/
|
|-- data/
|   |-- raw/                         sources brutes, ne jamais modifier
|   |   |-- offres_emploi.csv        Source, Titre, Employeur, Secteur, Details...
|   |   |-- candidats.csv            Objectif, Diplome, NCF, MEPC, Metier_vise...
|   |   |-- esco/                    18 CSV ESCO v1.2 FR
|   |   |-- NCF_Nomenclature.xlsx    4 feuilles : Niveaux, GrandDom, Spec, Det
|   |   `-- MEPC_Nomenclature.xlsx   3 feuilles : GrandGroupe, Sous, Base
|   |
|   |-- processed/
|   |   |-- offres_normalized.parquet
|   |   |-- candidats_normalized.parquet
|   |   `-- mapping_isco_mepc_esco.parquet
|   |
|   `-- finetune/                    paires pour SentenceTransformer
|       |-- pairs_train.jsonl         {sentence1: metadata, sentence2: description}
|       |-- pairs_val.jsonl
|       `-- pairs_test.jsonl
|
|-- src/
|   |-- 01_etl/
|   |   |-- normalize_offres.py       nettoyage, deduplication, mapping NCF
|   |   |-- normalize_candidats.py
|   |   |-- align_esco_mepc.py        jointures ISCO-08 MEPC <-> ESCO
|   |   `-- build_pairs.py           genere les paires metadata -> description
|   |
|   |-- 02_finetune_st/              LLM 1
|   |   |-- train_sentence_transformer.py
|   |   |-- evaluate_st.py
|   |   `-- config_st.json
|   |
|   |-- 03_knowledge_graph/
|   |   |-- load_neo4j.py             scripts Cypher : noeuds + relations
|   |   |-- schema.cypher             contraintes, index fulltext, HNSW Neo4j
|   |   `-- enrich_with_llm.py        extraction competences implicites -> :REQUIERT
|   |
|   |-- 04_pgvector/
|   |   |-- embed_all_entities.py     encode offres, candidats et ESCO
|   |   |-- schema_pgvector.sql       table embeddings 384d + index HNSW
|   |   `-- ann_search.py            fonction de recherche top-k
|   |
|   |-- 05_graphrag/                 LLM 2
|   |   |-- context_builder.py        assemble contexte Neo4j + pgvector
|   |   |-- prompt_templates.py       templates Mistral + GPT-4o
|   |   |-- recommendation_engine.py  pipeline complet end-to-end
|   |   `-- roadmap_generator.py      generation roadmap NCF en francais
|   |
|   |-- 06_api/                      nouveau dossier
|   |   |-- main.py                   app FastAPI + routes
|   |   |-- schemas.py                modeles Pydantic, entrees et sorties
|   |   |-- dependencies.py           connexions Neo4j + pgvector + ST
|   |   `-- routers/
|   |       |-- recommend.py
|   |       |-- skill_gap.py
|   |       `-- embed.py
|   |
|   `-- 07_evaluation/
|       |-- eval_embedding.py         Spearman, MRR@10, NDCG@10
|       |-- eval_retrieval.py         Precision@K, Recall@K, NDCG@K
|       |-- eval_faithfulness.py      detection hallucinations LLM 2
|       `-- llm_as_judge.py           GPT-4o evalue la qualite roadmap
|
|-- models/
|   `-- st_finetuned/
|       |-- config.json
|       |-- pytorch_model.bin
|       `-- tokenizer/
|
|-- notebooks/                       exploration + visualisation resultats
|-- requirements.txt
`-- README.md
```
