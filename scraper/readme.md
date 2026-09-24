# Scraper immobilier Tunisie — Tayara / Mubawab / Tecnocasa

Collecte les annonces de **vente** (appartements, maisons/villas) sur 3 sites
tunisiens et produit un CSV unifié (`dataset_immo_tunisie.csv`) pour le
nettoyage (`features collecting/clean_dataset.py`).

## Installation

```bash
pip install -r requirements.txt
```

Playwright n'est plus nécessaire : les 3 sites sont lus avec `requests`.

## Usage

```bash
python main.py                # test rapide (~3 min, quelques dizaines d'annonces)
python main.py --full         # collecte complète (plusieurs heures)
python main.py --merge-only   # refait seulement la fusion des annonces_*.csv
```

Chaque annonce est écrite dans `annonces_<site>.csv` dès qu'elle est collectée.
Après une interruption (coupure réseau, Ctrl+C), relancer la même commande
reprend là où la collecte s'était arrêtée.

## Méthode par site (vérifiée en octobre 2026)

| Site | Découverte des annonces | Données lues | Volume (vente) |
|---|---|---|---|
| **Tayara** | Pages de catégorie `?page=N`, toutes les pages | JSON `__NEXT_DATA__` : prix numérique, gouvernorat, délégation, description ; `adParams` : transaction, superficie, chambres, salles de bain | ~7 700 annonces vente + location ; les locations évidentes sont ignorées sans charger leur page |
| **Mubawab** | Page 1 de chaque gouvernorat × type | Texte de la page : en-tête « ville à gouvernorat prix TND », tags surface/chambres | ~19–33 annonces par page |
| **Tecnocasa** | Sitemap `residentiel.xml.gz` | JSON `:estate` de la page : prix et surface numériques, pièces, étage, équipements | ~1 300 annonces |

## Règles respectées

- **robots.txt** : chaque URL Mubawab/Tecnocasa est vérifiée avec
  `common.robots_allowed` (gère les jokers `*`). Mubawab interdit `/*:`, donc
  sa pagination (`...:p:2`) n'est **pas** collectée : seulement la page 1.
- **Politesse** : 1,5–3,5 s entre deux requêtes (`common.polite_sleep`).
- **Données personnelles** : les champs vendeur (nom, e-mail, téléphone) ne
  sont jamais lus ; les numéros et e-mails écrits dans le texte des annonces
  sont remplacés par `[tel]` / `[email]` à l'enregistrement.

## Données de la première collecte

`raw_v1/` contient les CSV bruts de la première version des scrapers
(août–septembre 2026). Ils sont conservés tels quels pour la traçabilité. Les
prix Tayara y sont pollués par les chiffres de fin de titre, et la partie
Mubawab provient de pages paginées que robots.txt interdit.

## Schéma de sortie (`common.Annonce`)

| Champ | Description |
|---|---|
| id, source, url | identifiants |
| type_transaction | vente / location |
| type_bien | appartement / maison_villa |
| gouvernorat, ville | localisation |
| prix_dt | prix en dinars tunisiens |
| surface_m2 | surface habitable |
| nb_pieces | N de « S+N » (nombre de chambres) |
| nb_chambres, nb_salles_bain | |
| etage, ascenseur, parking, piscine, climatisation, chauffage_central, meuble | |
| description_brute | texte de l'annonce (tronqué à 3000 caractères, contacts masqués) |
| date_scraping, date_publication | dates de collecte et de publication |
