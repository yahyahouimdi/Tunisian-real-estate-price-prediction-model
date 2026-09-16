# Tunisian Real Estate Price Prediction

A machine-learning project that estimates residential real-estate listing prices in Tunisia from property characteristics and location.

> **Current status: data cleaning in progress.** Data has been collected and an initial cleaning pass is available. Feature preparation, model training, and evaluation are the next stages.

## Project goals

- Collect property listings from multiple Tunisian platforms.
- Clean and standardize listing data for reliable analysis.
- Build separate regression models for sale and rental prices in Tunisian dinars (TND).
- Evaluate models with MAE, RMSE, R², and MAPE.

## Current data

The initial collection contains 2,385 listings from Tayara, Mubawab, and Tecnocasa. The cleaning pipeline retains 2,343 listings, including a 1,650-row subset with a known target price.

| File | Purpose |
|---|---|
| `scraper/dataset_immo_tunisie.csv` | Raw unified listings collected from the sources. |
| `features collecting/dataset_immo_tunisie_clean.csv` | Cleaned listings, including records without a price. |
| `features collecting/dataset_immo_tunisie_train_ready.csv` | Cleaned records with a known `prix_dt` target price. |
| `features collecting/rapport_nettoyage.md` | Cleaning decisions and current results. |

Available features include transaction type, property type, governorate, city, price, price per square metre, area, room counts, floor, and amenity indicators.

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
playwright install chromium
python main.py
```

Use `python main.py --full` only after validating the selectors and checking each platform’s terms of service and `robots.txt`. Tecnocasa requires Playwright; see `scraper/README.md` for source-specific details.

## Data cleaning

`features collecting/clean_dataset.py` currently:

1. Removes listings outside the sale/rental scope.
2. Corrects unreliable scraped prices and recovers missing prices from descriptions.
3. Standardizes governorates to Tunisia’s 24 official governorates.
4. Calculates price per square metre and filters regional outliers.
5. Removes zero-area rows and likely duplicate listings.
6. Exports cleaned and training-ready datasets.

Before running the script locally, update its input and output path constants, which currently target the environment used for the cleaning run.

## Next steps

- Split the data before imputing missing predictor values to avoid data leakage.
- Encode categorical variables and create reproducible preprocessing pipelines.
- Train baseline and tree-based regression models.
- Evaluate sales and rentals separately because their price scales differ substantially.

## Disclaimer

The dataset and resulting predictions are exploratory. Listings may be incomplete, duplicated, or changed by source websites, so predictions should not be treated as professional property valuations.
