"""Clean Tunisian real-estate listings for price-regression modelling.

The pipeline corrects known scraping issues, standardizes governorates, filters
outliers, removes duplicates, and exports cleaned and training-ready datasets.
"""
import re
from collections import Counter

import numpy as np
import pandas as pd

IN_PATH = "/mnt/user-data/uploads/dataset_immo_tunisie.csv"
OUT_PATH = "/mnt/user-data/outputs/dataset_immo_tunisie_clean.csv"
REPORT_PATH = "/mnt/user-data/outputs/rapport_nettoyage.md"
TRAIN_READY_PATH = "/mnt/user-data/outputs/dataset_immo_tunisie_train_ready.csv"

log = []  # Store report messages while the pipeline runs.


def note(message):
    """Print a message and add it to the generated Markdown report."""
    print(message)
    log.append(message)


def extract_price_candidates_tnd(text):
    """Return all values written as an integer followed by ``TND``."""
    if not isinstance(text, str):
        return []
    matches = re.findall(r"(\d{1,3}(?:[\s\u202f]\d{3}){0,3})\s*TND\b", text)
    return [int(number) for match in matches
            if (number := re.sub(r"[\s\u202f]", "", match)).isdigit()]


def best_price_tnd(text):
    """Choose the most repeated price, then the smallest value on a tie."""
    candidates = extract_price_candidates_tnd(text)
    if not candidates:
        return None
    counts = Counter(candidates)
    maximum = max(counts.values())
    return sorted(value for value, count in counts.items() if count == maximum)[0]


def extract_tecnocasa_price(text):
    """Extract Tecnocasa's actual price instead of its monthly loan instalment.

    The actual price follows the area in the summary text, e.g. ``112 m²
    135 000 DT``.
    """
    if not isinstance(text, str):
        return None
    match = re.search(r"m²\s*([\d][\d\s.]{2,10})\s*DT\b", text)
    if not match:
        return None
    number = re.sub(r"[\s.]", "", match.group(1))
    return int(number) if number.isdigit() else None


# Official Tunisian governorates and common location aliases found in listings.
OFFICIAL = {
    "Tunis", "Ariana", "Ben Arous", "Manouba", "Nabeul", "Zaghouan", "Bizerte", "Béja",
    "Jendouba", "Le Kef", "Siliana", "Sousse", "Monastir", "Mahdia", "Sfax", "Kairouan",
    "Kasserine", "Sidi Bouzid", "Gabès", "Médenine", "Tataouine", "Gafsa", "Tozeur", "Kébili",
}
ALIAS = {
    "el menzah": "Tunis", "le bardo": "Tunis", "ennasr": "Ariana", "bizerte nord": "Bizerte",
    "sahloul": "Sousse", "sousse centre ville": "Sousse", "kélibia": "Nabeul", "hammamet": "Nabeul",
    "hergla": "Sousse", "akouda": "Sousse", "hammam sousse": "Sousse", "sousse riadh": "Sousse",
    "khezama": "Monastir", "kef": "Le Kef",
}


def normalize_gouv(value):
    """Map a listing location to an official governorate, or return missing."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    base = value.split(",")[0].strip()
    if value in OFFICIAL:
        return value
    if base in OFFICIAL:
        return base
    return ALIAS.get(base.lower(), ALIAS.get(value.lower()))


def tayara_bounds(transaction_type):
    """Return plausible TND bounds for a Tayara listing price."""
    return (5_000, 8_000_000) if transaction_type == "vente" else (150, 20_000)


def iqr_mask(group, column, k=2.5):
    """Keep non-outliers in one regional transaction group; retain missing values."""
    q1, q3 = group[column].quantile([0.25, 0.75])
    iqr = q3 - q1
    if iqr == 0 or pd.isna(iqr):
        return pd.Series(True, index=group.index)
    return group[column].between(q1 - k * iqr, q3 + k * iqr) | group[column].isna()


df = pd.read_csv(IN_PATH)
n0 = len(df)
note(f"## Raw dataset: {n0} rows, {df.shape[1]} columns")
note(f"Sources: {dict(df['source'].value_counts())}")

# Remove listings that are not confirmed sales or rentals.
before = len(df)
df = df[df["type_transaction"].isin(["vente", "location"])].copy()
note(f"\n### 1. Removed unknown transaction types: {before - len(df)} rows")

# Recover prices from descriptions where source-specific scraped price fields fail.
df["prix_dt_original"] = df["prix_dt"]
mask_tec = df["source"] == "tecnocasa"
fixed = df.loc[mask_tec, "description_brute"].apply(extract_tecnocasa_price)
df.loc[mask_tec, "prix_dt"] = fixed
note(f"\n### 2. Corrected Tecnocasa prices: {fixed.notna().sum()}/{mask_tec.sum()}")

mask_mub = (df["source"] == "mubawab") & df["prix_dt"].isna()
filled = df.loc[mask_mub, "description_brute"].apply(best_price_tnd)
df.loc[mask_mub, "prix_dt"] = filled
note(f"### 3. Filled missing Mubawab prices: {filled.notna().sum()}/{mask_mub.sum()}")

bounds = df["type_transaction"].apply(tayara_bounds)
outliers = (df["source"] == "tayara") & (
    (df["prix_dt"] < bounds.apply(lambda item: item[0])) |
    (df["prix_dt"] > bounds.apply(lambda item: item[1]))
)
recovered = df.loc[outliers, "description_brute"].apply(best_price_tnd)
df.loc[outliers, "prix_dt"] = recovered
note(f"### 4. Implausible Tayara prices: {outliers.sum()} detected, {recovered.notna().sum()} recovered")

# Standardize locations, then calculate price per square metre for filtering.
df["gouvernorat_original"] = df["gouvernorat"]
df["gouvernorat"] = df["gouvernorat"].apply(normalize_gouv)
note(f"\n### 5. Unresolved governorates set to missing: {df['gouvernorat'].isna().sum()}")
df["prix_m2"] = np.where(df["surface_m2"] > 0, df["prix_dt"] / df["surface_m2"], np.nan)

# Filter regional price-per-square-metre outliers and nonsensical zero-area rows.
before = len(df)
df = df.reset_index(drop=True)
keep = df.groupby(["gouvernorat", "type_transaction"], group_keys=False).apply(
    lambda group: iqr_mask(group, "prix_m2")
).reindex(df.index)
df = df[keep].copy()
note(f"\n### 6. Removed price-per-m² outliers: {before - len(df)} rows")
before = len(df)
df = df[df["surface_m2"] != 0]
note(f"### 7. Removed zero-area listings: {before - len(df)} rows")

# Remove likely reposts or cross-posted listings using their key shared fields.
before = len(df)
df = df.drop_duplicates(subset=["titre", "gouvernorat", "surface_m2", "prix_dt", "nb_pieces"])
note(f"\n### 8. Removed duplicate listings: {before - len(df)} rows")

# Retain only columns used for modelling and export both output datasets.
model_cols = ["id", "source", "type_transaction", "type_bien", "gouvernorat", "ville", "prix_dt", "prix_m2",
              "surface_m2", "nb_pieces", "nb_chambres", "nb_salles_bain", "etage", "ascenseur", "parking",
              "piscine", "climatisation", "chauffage_central", "meuble"]
df_final = df[model_cols].reset_index(drop=True)
df_final.to_csv(OUT_PATH, index=False)
df_train_ready = df_final.dropna(subset=["prix_dt"]).reset_index(drop=True)
df_train_ready.to_csv(TRAIN_READY_PATH, index=False)

note(f"\n## Final dataset: {len(df_final)} rows ({len(df_final) / n0 * 100:.1f}% retained)")
note(f"Training-ready subset (non-null prix_dt): {len(df_train_ready)} rows")
with open(REPORT_PATH, "w", encoding="utf-8") as file:
    file.write("# Cleaning Report — dataset_immo_tunisie\n\n" + "\n".join(log))
