# Scraper immobilier Tunisie — Tayara / Mubawab / Tecnocasa

Scrape les annonces de vente/location immobilière sur 3 sites tunisiens et
produit un dataset CSV unifié pour un modèle de prédiction de prix.

## Installation

```bash
pip install -r requirements.txt --break-system-packages
playwright install chromium   # nécessaire uniquement pour scraper_tecnocasa.py
```

## Usage

```bash
# Test rapide (peu de pages, pour vérifier que tout fonctionne)
python main.py

# Collecte complète (long, à lancer une fois les sélecteurs validés)
python main.py --full
```

Chaque scraper peut aussi être lancé indépendamment :
```bash
python scraper_tayara.py
python scraper_mubawab.py
python scraper_tecnocasa.py   # nécessite Playwright installé
```

## Schéma de sortie (`common.Annonce`)

| Champ | Description |
|---|---|
| id, source, url | identifiants |
| type_transaction | vente / location |
| type_bien | appartement / maison_villa / ... |
| gouvernorat, ville | localisation |
| prix_dt | prix en dinars tunisiens |
| surface_m2 | surface habitable |
| nb_pieces, nb_chambres, nb_salles_bain | |
| etage, ascenseur, parking, piscine, climatisation, chauffage_central, meuble | |
| description_brute | texte complet (tronqué à 3000 caractères) |

## ⚠️ Points importants avant de lancer à grande échelle

1. **Vérifie robots.txt et CGU de chaque site** (`/robots.txt`) avant tout
   scraping massif, et respecte les délais entre requêtes (déjà intégrés
   dans `common.polite_sleep`, 1.5–3.5s).
2. **Tayara** : rendu HTML côté serveur (Next.js) → `requests` suffit.
   Structure des URLs vérifiée en août 2026, mais peut changer sans préavis.
3. **Mubawab** : structure la plus "propre" (caractéristiques déjà en tags).
   Le scraper par défaut ne couvre que Tunis/Ariana/Sousse pour le test —
   étends `GOUVERNORAT_SLUGS` dans `scraper_mubawab.py` pour couvrir les
   24 gouvernorats.
4. **Tecnocasa** : la grille d'annonces est chargée en JavaScript. Le script
   utilise Playwright, mais le **sélecteur CSS des liens d'annonce
   (`CARD_LINK_SELECTOR`) est à confirmer** en inspectant le site dans ton
   navigateur (F12 → clic droit sur une annonce → Inspecter). C'est marqué
   `TODO` dans le fichier.
5. **Extraction par regex sur le texte** plutôt que par classes CSS précises :
   plus robuste aux changements de design, mais peut rater des cas non
   standards (prix en lettres, formats inhabituels). Pense à valider un
   échantillon manuellement après le premier run.
6. **Dédoublonnage** : le `main.py` fait un dédoublonnage grossier
   (titre + gouvernorat + prix + surface) lors de la fusion. Vérifie la
   qualité de ce dédoublonnage sur ton dataset réel.
7. Ce code n'a **pas pu être testé en conditions réelles** dans cet
   environnement (accès réseau restreint à des domaines comme pypi/github).
   Teste-le d'abord sur un petit échantillon (`max_pages=1-2`) avant de
   lancer une collecte complète.

## Prochaine étape

Une fois `dataset_immo_tunisie.csv` généré → passage au preprocessing
(nettoyage, gestion des valeurs manquantes, encodage, split stratifié par
gouvernorat) qu'on avait détaillé juste avant.
