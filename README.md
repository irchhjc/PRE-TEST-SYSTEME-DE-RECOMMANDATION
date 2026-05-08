# PRE-TEST-SYSTEME-DE-RECOMMANDATION

Ce depot sert a concevoir un systeme de recommandation hybride pour le
matching emploi-competences au Cameroun. L'objectif est de rapprocher des
profils, des offres d'emploi et des referentiels metiers/competences
(`ESCO`, `MEPC`, `NCF`) dans une architecture combinant embeddings
semantiques, base vectorielle et graphe de connaissances.

## Idee centrale

Le projet ne part pas d'un modele de langue entraine depuis zero. La strategie
du module 02 est plus precise : on reutilise un encodeur de phrases deja
preentraine, `sentence-transformers/all-MiniLM-L6-v2`, puis on l'adapte au
domaine local emploi-competences par fine-tuning contrastif.

Donc, par rigueur methodologique, il faut eviter d'appeler cela un
"preentrainement" au sens strict. Un vrai preentrainement consisterait a
entrainer le modele sur une tres grande masse de texte brut ou de paires
generiques, avec un cout calculatoire eleve. Ici, la strategie est une
adaptation specialisee : le modele possede deja une competence generale
d'encodage semantique, et on lui apprend a mieux aligner les metadonnees des
offres camerounaises avec leurs descriptions textuelles.

## Structure du projet

```text
PRE-TEST-SYSTEME-DE-RECOMMANDATION/
|
|-- data/
|   |-- raw/                         donnees brutes
|   |-- processed/                   donnees nettoyees et normalisees
|   `-- finetune/                    paires pour le fine-tuning ST
|       |-- pairs_train.jsonl
|       |-- pairs_val.jsonl
|       `-- pairs_test.jsonl
|
|-- src/
|   |-- 01_etl/                      normalisation et construction des paires
|   |-- 02_finetune_st/              adaptation SentenceTransformer
|   |   |-- train_sentence_transformer.py
|   |   |-- evaluate_st.py
|   |   `-- config_st.json
|   |-- 03_knowledge_graph/          graphe Neo4j
|   |-- 04_pgvector/                 embeddings et recherche vectorielle
|   |-- 05_graphrag/                 generation de recommandations augmentees
|   |-- 06_api/                      API FastAPI
|   `-- 07_evaluation/               evaluation globale
|
|-- models/
|   `-- st_finetuned/                modele adapte et metriques
|
|-- pyproject.toml
|-- poetry.lock
`-- README.md
```

## Module 02 - Strategie de preentrainement/adaptation

### 1. Modele de depart

Le module 02 charge le modele suivant :

```text
sentence-transformers/all-MiniLM-L6-v2
```

Ce modele transforme une phrase ou un court paragraphe en vecteur dense de
dimension 384. Il est adapte aux taches de similarite semantique, clustering et
recherche d'information. Dans ce projet, il sert de base pour representer les
offres, les competences et les requetes dans un meme espace vectoriel.

### 2. Donnees d'adaptation

Les donnees de fine-tuning sont stockees dans :

```text
data/finetune/pairs_train.jsonl
data/finetune/pairs_val.jsonl
data/finetune/pairs_test.jsonl
```

Chaque ligne represente une paire positive :

```json
{
  "offre_id": "identifiant_offre",
  "sentence1": "metadonnees structurees de l'offre",
  "sentence2": "description textuelle, competences et details de l'annonce"
}
```

Dans la logique du modele :

- `sentence1` joue le role d'ancre : elle resume les metadonnees structurees.
- `sentence2` joue le role de positif : elle contient le contenu textuel que
  l'ancre doit retrouver.
- `offre_id` permet de construire l'evaluation de retrieval : pour chaque
  requete, le document pertinent est celui qui partage le meme identifiant.

Cette construction est economiquement coherente avec le probleme : un recruteur,
un candidat ou un moteur de matching ne manipule pas toujours une description
longue. Il manipule souvent des attributs structures : metier vise, niveau
d'etudes, secteur, experience, competences, referentiel NCF/MEPC. Le modele doit
donc apprendre a relier ces signaux courts et structures aux descriptions
metier plus riches.

### 3. Objectif d'apprentissage

Le fine-tuning utilise `MultipleNegativesRankingLoss`.

L'idee est simple mais exigeante : dans un mini-batch, chaque paire
`(anchor, positive)` est consideree comme correcte, tandis que les autres
positifs du batch deviennent des negatifs implicites pour cette ancre.

Exemple avec un batch de 32 paires :

- 1 description est la bonne reponse pour l'ancre courante ;
- les 31 autres descriptions du batch sont traitees comme reponses incorrectes ;
- le modele apprend a donner une similarite cosine plus forte a la vraie paire.

Cette strategie est pertinente quand on dispose surtout de paires positives,
mais peu ou pas de paires negatives annotees manuellement. C'est le cas ici :
les offres et leurs descriptions fournissent naturellement des correspondances
positives, tandis que les faux appariements seraient couteux a annoter proprement.

### 4. Hyperparametres

La configuration principale est dans :

```text
src/02_finetune_st/config_st.json
```

Parametres actuels :

```text
modele_base      = sentence-transformers/all-MiniLM-L6-v2
dimension        = 384
epochs           = 5
batch_size       = 32
learning_rate    = 2e-5
warmup_steps     = 100
weight_decay     = 0.01
max_grad_norm    = 1.0
loss             = MultipleNegativesRankingLoss
similarite       = cosine
```

Le batch size n'est pas un detail secondaire. Avec
`MultipleNegativesRankingLoss`, un batch de 32 cree 31 negatifs implicites par
exemple. Si le batch est trop petit, le signal contrastif est plus pauvre. Si le
batch est trop grand pour la machine, l'entrainement devient lent ou instable.

### 5. Evaluation

Le module evalue deux dimensions :

1. Similarite d'embeddings

   On compare les vecteurs de `sentence1` et `sentence2` pour verifier si les
   paires positives deviennent proches dans l'espace vectoriel.

2. Recherche d'information

   On utilise les metadonnees comme requetes et les descriptions comme corpus.
   Les metriques suivies sont :

   - `Recall@1`, `Recall@5`, `Recall@10`
   - `MRR@1`, `MRR@5`, `MRR@10`
   - `NDCG@1`, `NDCG@5`, `NDCG@10`
   - `Precision@1`, `Precision@5`, `Precision@10`

Attention : une bonne metrique sur un petit split ne prouve pas encore que le
systeme generalise. Si les textes partagent beaucoup de mots explicites, le
retrieval peut etre facile. Il faut donc comparer le modele fine-tune au
baseline et regarder les erreurs qualitatives, pas seulement un score global.

## Commandes d'execution

Depuis la racine du projet :

```powershell
cd "D:\DATA SCIENCES\PRE-TEST-SYSTEME-DE-RECOMMANDATION"
```

Entrainement complet :

```powershell
poetry run python src/02_finetune_st/train_sentence_transformer.py
```

Test rapide sur une epoch :

```powershell
poetry run python src/02_finetune_st/train_sentence_transformer.py --epochs 1 --batch 8
```

Evaluation du modele fine-tune :

```powershell
poetry run python src/02_finetune_st/evaluate_st.py
```

Evaluation sans baseline :

```powershell
poetry run python src/02_finetune_st/evaluate_st.py --no-baseline
```

Si le modele Hugging Face est deja en cache et que l'on veut eviter les appels
reseau :

```powershell
$env:HF_HUB_OFFLINE = "1"
poetry run python src/02_finetune_st/train_sentence_transformer.py
```

## Sorties attendues

Apres entrainement, les artefacts sont ecrits dans :

```text
models/st_finetuned/
```

Sorties principales :

```text
models/st_finetuned/final/
models/st_finetuned/checkpoints/
models/st_finetuned/evaluation_metrics.json
models/st_finetuned/eval_test/
```

Le dossier `final/` contient le modele SentenceTransformer adapte. Il doit etre
utilise ensuite pour encoder les offres, candidats et competences dans les
modules vectoriels ou hybrides.

## Limites methodologiques

Cette strategie est pragmatique, mais elle impose plusieurs garde-fous :

- Les paires positives ne suffisent pas a prouver une vraie comprehension du
  marche du travail. Elles apprennent surtout une geometrie d'appariement.
- Les negatifs implicites du batch peuvent contenir de faux negatifs : deux
  offres proches peuvent etre traitees comme negatives alors qu'elles sont
  semantiquement compatibles.
- L'evaluation doit rester separee de l'entrainement. Les fichiers
  `pairs_train.jsonl`, `pairs_val.jsonl` et `pairs_test.jsonl` ne doivent pas
  etre melanges.
- Les gains doivent etre compares au modele baseline. Un score absolu eleve ne
  suffit pas.
- Le modele encode la similarite semantique, pas l'equivalence institutionnelle.
  Les correspondances `ESCO`, `MEPC` et `NCF` doivent rester explicites dans le
  graphe et les tables de reference.

## Role dans l'architecture globale

Le module 02 produit un encodeur specialise. Cet encodeur alimente ensuite :

- la recherche vectorielle dans `pgvector` ;
- le rapprochement candidat-offre ;
- la selection de contextes pour le GraphRAG ;
- l'analyse de skill gap ;
- les recommandations de formation ou de transition metier.

Le modele fine-tune n'est donc pas la recommandation finale. Il est une brique
de representation. La decision finale doit combiner :

- similarite semantique ;
- contraintes de diplome et niveau NCF ;
- proximite MEPC/ESCO ;
- experience ;
- localisation ;
- relations du graphe de connaissances ;
- logique economique du marche du travail camerounais.

## Sources

- Sentence Transformers, documentation de `MultipleNegativesRankingLoss` :
  https://www.sbert.net/docs/package_reference/sentence_transformer/losses.html
- Sentence Transformers, documentation des evaluateurs :
  https://www.sbert.net/docs/package_reference/sentence_transformer/evaluation.html
- Hugging Face, fiche modele `sentence-transformers/all-MiniLM-L6-v2` :
  https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
