# Tunisian Real Estate Price Prediction

A machine-learning project that estimates residential real-estate listing prices in Tunisia from property characteristics and location.

> **Current status: data cleaning in progress.** Data has been collected and an initial cleaning pass is available. Feature preparation, model training, and evaluation are the next stages.

## Project goals

- Collect property listings from multiple Tunisian platforms.
- Clean and standardize listing data for reliable analysis.
- Build a regression model for sale prices in Tunisian dinars (TND). Rentals are out of scope for now.
- Evaluate models with MAE, RMSE, R², and MAPE.

## Current data

The initial collection contains 2,385 listings from Tayara, Mubawab, and Tecnocasa. The cleaning pipeline keeps sale listings only and retains 1,287 listings, including 1,093 with a known target price.

| File | Purpose |
|---|---|
| `scraper/dataset_immo_tunisie.csv` | Raw unified listings collected from the sources. |
| `features collecting/dataset_immo_tunisie_clean.csv` | Cleaned listings, including records without a price. |
| `features collecting/dataset_immo_tunisie_train_ready.csv` | Model features + `prix_dt` target, plus `outlier_prix_m2` and `groupe_bien` (not features: filtering and grouped splits). |
| `features collecting/rapport_nettoyage.md` | Cleaning decisions and current results. |

Model features: `type_bien`, `region`, `gouvernorat`, `ville`, `surface_m2`, `nb_chambres` (N of S+N), `nb_salles_bain`, `etage_num`, and amenities (`ascenseur`, `parking`, `piscine`, `climatisation`, `chauffage_central`) coded 1 / 0 / missing = not mentioned.

## Repository structure

```text
scraper/                 Scrapers for Tayara, Mubawab, and Tecnocasa
features collecting/     Cleaning pipeline, report, and prepared CSV datasets
steps.txt                Project roadmap and modelling notes
```

## Data collection

Install the scraper dependencies and run a small collection first:

```bash
cd scraper
pip install -r requirements.txt
python main.py          # quick test
python main.py --full   # full collection (several hours, resumable)
```

The scrapers read the structured data each site embeds in its pages (Tayara and Tecnocasa JSON), respect `robots.txt`, and never store sellers' contact details. See [scraper/readme.md](scraper/readme.md) for source-specific details. The first collection is kept in `scraper/raw_v1/`.

## Data cleaning

`features collecting/clean_dataset.py` currently:

1. Keeps sale listings only.
2. Repairs prices: Tecnocasa credit values, Tayara prices polluted by trailing title digits (e.g. "Menzah 6" + 248 000 → 6 248 000), prices written in thousands ("280 DT"), placeholder prices.
3. Standardizes governorates and cities, fixes city/governorate conflicts, adds the 7 INS regions and groups rare categories.
4. Builds one consistent bedroom count from the S+N notation.
5. Codes amenities as 1 / 0 / unknown and handles negations ("sans ascenseur").
6. Invalidates impossible price per m² (price too high → target removed; too low → surface is land area) and flags IQR outliers.
7. Removes duplicate listings, including the same property posted on several sites, and groups units of one project (`groupe_bien`).
8. Exports cleaned and training-ready datasets and the report `rapport_nettoyage.md`.

Run it from any directory with `py "features collecting/clean_dataset.py"` (paths are relative to the script).

## Next steps

- Split with `GroupKFold` on `groupe_bien` (and check governorate balance) before imputing missing predictor values.
- Model `log(prix_dt)`: prices are strongly right-skewed.
- Encode categorical variables and create reproducible preprocessing pipelines.
- Train baseline and tree-based regression models.

## Disclaimer

The dataset and resulting predictions are exploratory. Listings may be incomplete, duplicated, or changed by source websites, so predictions should not be treated as professional property valuations.
