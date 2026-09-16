# Cleaning Report — `dataset_immo_tunisie`

## Raw dataset

- Rows: 2,385
- Columns: 22
- Sources: Tayara (1,716), Mubawab (573), Tecnocasa (96)

## Cleaning results

1. Removed 9 listings with an unknown transaction type.
2. Corrected all 96 Tecnocasa prices: the scraped values were monthly loan instalments rather than actual listing prices.
3. Recovered 492 of 570 missing Mubawab prices from the raw description text.
4. Detected 90 implausible Tayara prices caused by digit concatenation; 1 was recovered and 89 were set to missing.
5. Standardized all governorates to the 24 official Tunisian governorates; no values remained unresolved.
6. Removed 29 price-per-square-metre outliers using IQR × 2.5 within each governorate and transaction type.
7. Removed 3 listings with a zero surface area.
8. Removed 1 duplicate listing based on matching title, governorate, surface, price, and room count.

The missing-price rate fell from 46.2% to 29.3% after price recovery and correction.

## Final cleaned dataset

- Rows: 2,343 (98.2% of the raw data retained)
- Columns: 19
- Transactions: 1,289 sales and 1,054 rentals

| Field | Missing values |
|---|---:|
| `ville` | 24.7% |
| `prix_dt` | 29.6% |
| `prix_m2` | 55.1% |
| `surface_m2` | 45.9% |
| `nb_pieces` | 28.1% |
| `nb_chambres` | 2.6% |
| `nb_salles_bain` | 14.3% |
| `etage` | 72.4% |

All remaining binary amenity fields and the core source, transaction, property-type, and governorate fields are complete.

## Training-ready subset

Filtering the cleaned dataset to listings with a known target price produces **1,650 rows**: 1,019 sales and 631 rentals. Missing predictor values will be imputed only after splitting the data into training and test sets, preventing data leakage.
