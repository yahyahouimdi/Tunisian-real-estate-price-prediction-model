"""
Clean Tunisian real-estate listings for price-regression modelling.

Scope:
    - Vente uniquement

The pipeline:
    1. Validates identifiers and sources
    2. Keeps sale listings only
    3. Cleans and reconstructs prices
    4. Normalizes governorates and cities
    5. Cleans property size and room features
    6. Normalizes boolean features
    7. Normalizes floor information
    8. Applies explicit plausibility bounds
    9. Computes prix_m2 for auditing/outlier detection
   10. Detects statistical prix_m2 outliers
   11. Detects/removes duplicate listings safely
   12. Exports clean and training-ready datasets

IMPORTANT:
    prix_m2 is derived from prix_dt and MUST NOT be used as a
    model input feature when prix_dt is the target.
"""

import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

IN_PATH = BASE_DIR.parent / "scraper" / "dataset_immo_tunisie.csv"
OUT_PATH = BASE_DIR / "dataset_immo_tunisie_clean.csv"
REPORT_PATH = BASE_DIR / "rapport_nettoyage.md"
TRAIN_READY_PATH = BASE_DIR / "dataset_immo_tunisie_train_ready.csv"


# ============================================================
# EXPLICIT PLAUSIBILITY BOUNDS
# ============================================================

BOUNDS = {
    "prix_dt": (50_000, 10_000_000),
    "prix_m2": (300, 15_000),
    "surface_m2": (30, 2_500),
    "nb_pieces": (1, 15),
    "nb_chambres": (0, 10),
    "nb_salles_bain": (0, 8),
}

PRICE_FLOOR = BOUNDS["prix_dt"][0]
PRICE_CEIL = BOUNDS["prix_dt"][1]


# ============================================================
# LOGGING
# ============================================================

log = []


def note(msg):
    print(msg)
    log.append(msg)


# ============================================================
# LOAD DATA
# ============================================================

df = pd.read_csv(IN_PATH)

n0 = len(df)

note(f"## Dataset brut : {n0} lignes")

if "source" in df.columns:
    note(f"Sources : {dict(df['source'].value_counts(dropna=False))}")


# ============================================================
# REQUIRED COLUMNS
# ============================================================

required_columns = [
    "id",
    "source",
    "type_transaction",
    "type_bien",
    "gouvernorat",
    "ville",
    "prix_dt",
    "surface_m2",
    "nb_pieces",
    "nb_chambres",
    "nb_salles_bain",
    "etage",
    "ascenseur",
    "parking",
    "piscine",
    "climatisation",
    "chauffage_central",
    "meuble",
    "titre",
    "description_brute",
]

missing_required = [
    col for col in required_columns
    if col not in df.columns
]

if missing_required:
    raise ValueError(
        f"Colonnes obligatoires manquantes : {missing_required}"
    )


# ============================================================
# 1) NORMALIZE SOURCE
# ============================================================

df["source"] = (
    df["source"]
    .astype("string")
    .str.strip()
    .str.lower()
)

VALID_SOURCES = {
    "tayara",
    "mubawab",
    "tecnocasa",
}

invalid_source = ~df["source"].isin(VALID_SOURCES) & df["source"].notna()

note(
    f"\n### Sources invalides/inconnues : "
    f"{invalid_source.sum()} lignes"
)

df.loc[invalid_source, "source"] = pd.NA


# ============================================================
# 2) SCOPE : VENTE UNIQUEMENT
# ============================================================

df["type_transaction"] = (
    df["type_transaction"]
    .astype("string")
    .str.strip()
    .str.lower()
)

before = len(df)

df = df[df["type_transaction"] == "vente"].copy()

note(
    f"\n### 1) Filtre vente uniquement : "
    f"{before - len(df)} lignes retirées, "
    f"{len(df)} lignes vente conservées"
)


# ============================================================
# 3) VALIDATE / NORMALIZE IDS
# ============================================================

df["id"] = (
    df["id"]
    .astype("string")
    .str.strip()
)

missing_id = df["id"].isna() | (df["id"] == "")

note(
    f"\n### IDs manquants : {missing_id.sum()} lignes"
)

# Remove rows without an identifier because the ID is required
# for tracking listings and detecting duplicates.
before = len(df)

df = df[~missing_id].copy()

note(
    f"### Lignes supprimées pour ID manquant : "
    f"{before - len(df)}"
)


# Check duplicate IDs inside each source
df["source_id"] = (
    df["source"].fillna("unknown")
    + "_"
    + df["id"]
)

duplicate_source_id = df["source_id"].duplicated(keep=False)

note(
    f"### IDs source+id dupliqués détectés : "
    f"{duplicate_source_id.sum()} lignes"
)

# Keep first occurrence
before = len(df)

df = df.drop_duplicates(
    subset=["source_id"],
    keep="first"
).copy()

note(
    f"### Doublons source+id supprimés : "
    f"{before - len(df)}"
)


# ============================================================
# 4) PRICE EXTRACTION
# ============================================================

def extract_tnd_candidates(text):
    """
    Extract prices explicitly followed by TND.

    Examples:
        450 000 TND
        450.000 TND
        450 000 TND
    """

    if not isinstance(text, str):
        return []

    out = []

    pattern = (
        r"(\d{1,3}(?:[\s\u202f.]"
        r"\d{3}){0,3})\s*TND\b"
    )

    for m in re.findall(pattern, text, flags=re.IGNORECASE):

        num = re.sub(r"[\s\u202f.]", "", m)

        if num.isdigit():
            out.append(int(num))

    return out


PHONE_CTX = re.compile(
    r"(\+216|appelez|whatsapp|afficher le numéro)",
    re.IGNORECASE
)


def extract_dt_candidates(text):
    """
    Extract values followed by DT while attempting to avoid
    phone numbers and obviously implausible small values.
    """

    if not isinstance(text, str):
        return []

    out = []

    pattern = (
        r"(\d{1,3}(?:[\s\u202f.]"
        r"\d{3}){0,3})\s*DT\b"
    )

    for m in re.finditer(
        pattern,
        text,
        flags=re.IGNORECASE
    ):

        num = re.sub(
            r"[\s\u202f.]",
            "",
            m.group(1)
        )

        if not num.isdigit():
            continue

        val = int(num)

        # Use the SAME price floor as the final bounds
        if val < PRICE_FLOOR:
            continue

        # Avoid phone-number context
        window = text[
            max(0, m.start() - 40):
            m.start()
        ]

        if PHONE_CTX.search(window):
            continue

        # Tunisian phone numbers are generally 8 digits
        if len(num) == 8:
            continue

        out.append(val)

    return out


def extract_tecnocasa_price(text):
    """
    Tecnocasa-specific correction.

    The scraped prix_dt can correspond to a credit/monthly
    value. The actual property price is searched immediately
    after the surface expression.

    Example:
        112 m² 135 000 DT
    """

    if not isinstance(text, str):
        return None

    pattern = (
        r"m²\s*"
        r"([\d][\d\s.]{2,10})"
        r"\s*DT\b"
    )

    m = re.search(
        pattern,
        text,
        flags=re.IGNORECASE
    )

    if not m:
        return None

    num = re.sub(
        r"[\s.]",
        "",
        m.group(1)
    )

    if not num.isdigit():
        return None

    value = int(num)

    if PRICE_FLOOR <= value <= PRICE_CEIL:
        return value

    return None


def best_of(
    candidates,
    floor=PRICE_FLOOR,
    ceil=PRICE_CEIL
):
    """
    Select the most frequently occurring valid candidate.

    If several candidates have the same frequency,
    choose the smallest valid candidate.
    """

    candidates = [
        c for c in candidates
        if floor <= c <= ceil
    ]

    if not candidates:
        return None

    counts = Counter(candidates)

    max_count = max(counts.values())

    return sorted(
        value
        for value, count in counts.items()
        if count == max_count
    )[0]


df["prix_dt_original"] = df["prix_dt"]


# ------------------------------------------------------------
# 4a) TECNOCASA
# ------------------------------------------------------------

mask_tec = df["source"].eq("tecnocasa")

fixed = df.loc[
    mask_tec,
    "description_brute"
].apply(extract_tecnocasa_price)

df.loc[
    mask_tec,
    "prix_dt"
] = fixed

note(
    f"\n### 2) Prix Tecnocasa corrigés : "
    f"{fixed.notna().sum()}/{mask_tec.sum()}"
)


# ------------------------------------------------------------
# 4b) CONVERT PRICE COLUMN TO NUMERIC
# ------------------------------------------------------------

df["prix_dt"] = pd.to_numeric(
    df["prix_dt"],
    errors="coerce"
)


# ------------------------------------------------------------
# 4c) INVALID ORIGINAL PRICES
# ------------------------------------------------------------

out_of_range = (
    df["prix_dt"].notna()
    & (
        (df["prix_dt"] < PRICE_FLOOR)
        | (df["prix_dt"] > PRICE_CEIL)
    )
)

note(
    f"### 3) Prix existants hors bornes "
    f"[{PRICE_FLOOR:,} ; {PRICE_CEIL:,}] TND : "
    f"{out_of_range.sum()} invalidés"
)

df.loc[
    out_of_range,
    "prix_dt"
] = np.nan


# ------------------------------------------------------------
# 4d) TND EXTRACTION
# ------------------------------------------------------------

still_missing = df["prix_dt"].isna()

tnd_fill = df.loc[
    still_missing,
    "description_brute"
].apply(
    lambda text: best_of(
        extract_tnd_candidates(text)
    )
)

df.loc[
    still_missing,
    "prix_dt"
] = tnd_fill

note(
    f"### 4) Prix récupérés via 'TND' : "
    f"{tnd_fill.notna().sum()}/{still_missing.sum()}"
)


# ------------------------------------------------------------
# 4e) DT EXTRACTION
# ------------------------------------------------------------

still_missing = df["prix_dt"].isna()

dt_fill = df.loc[
    still_missing,
    "description_brute"
].apply(
    lambda text: best_of(
        extract_dt_candidates(text)
    )
)

df.loc[
    still_missing,
    "prix_dt"
] = dt_fill

note(
    f"### 5) Prix récupérés via 'DT' : "
    f"{dt_fill.notna().sum()}/{still_missing.sum()}"
)


note(
    f"\nPrix manquants au final : "
    f"{df['prix_dt'].isna().sum()} / {len(df)} "
    f"({df['prix_dt'].isna().mean()*100:.1f}%)"
)


# ============================================================
# 5) GOUVERNORAT
# ============================================================

OFFICIAL = {
    "Tunis",
    "Ariana",
    "Ben Arous",
    "Manouba",
    "Nabeul",
    "Zaghouan",
    "Bizerte",
    "Béja",
    "Jendouba",
    "Le Kef",
    "Siliana",
    "Sousse",
    "Monastir",
    "Mahdia",
    "Sfax",
    "Kairouan",
    "Kasserine",
    "Sidi Bouzid",
    "Gabès",
    "Médenine",
    "Tataouine",
    "Gafsa",
    "Tozeur",
    "Kébili",
}


ALIAS = {
    "el menzah": "Tunis",
    "le bardo": "Tunis",
    "ennasr": "Ariana",
    "bizerte nord": "Bizerte",
    "sahloul": "Sousse",
    "sousse centre ville": "Sousse",
    "kélibia": "Nabeul",
    "hammamet": "Nabeul",
    "hergla": "Sousse",
    "akouda": "Sousse",
    "hammam sousse": "Sousse",
    "sousse riadh": "Sousse",
    "khezama": "Sousse",
    "kef": "Le Kef",
}


def normalize_gouv(value):

    if not isinstance(value, str):
        return pd.NA

    value = value.strip()

    if not value:
        return pd.NA

    if value in OFFICIAL:
        return value

    base = value.split(",")[0].strip()

    if base in OFFICIAL:
        return base

    base_lower = base.lower()

    if base_lower in ALIAS:
        return ALIAS[base_lower]

    value_lower = value.lower()

    if value_lower in ALIAS:
        return ALIAS[value_lower]

    return pd.NA


df["gouvernorat_original"] = df["gouvernorat"]

df["gouvernorat"] = (
    df["gouvernorat"]
    .apply(normalize_gouv)
)


note(
    f"\n### 6) Gouvernorats normalisés. "
    f"Non résolus : "
    f"{df['gouvernorat'].isna().sum()}"
)


# ============================================================
# 6) VILLE
# ============================================================

villes_ref = sorted(
    [
        str(v)
        for v in df["ville"].dropna().unique()
        if str(v).strip()
        and str(v) not in OFFICIAL
        and str(v) != "Autres Villes"
    ],
    key=lambda x: -len(x)
)


def get_search_text(row):

    title = (
        row["titre"]
        if isinstance(row["titre"], str)
        else ""
    )

    desc = (
        row["description_brute"]
        if isinstance(row["description_brute"], str)
        else ""
    )

    idx = desc.lower().find("description")

    if idx != -1:
        body = desc[idx:idx + 500]
    else:
        body = desc[:500]

    return title + " " + body


def find_ville(row):

    current = row["ville"]

    if pd.notna(current):

        current = str(current).strip()

        if current:
            return current

    text = get_search_text(row)

    for ville in villes_ref:

        pattern = (
            r"\b"
            + re.escape(ville)
            + r"\b"
        )

        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        ):
            return ville

    return pd.NA


before_missing = df["ville"].isna().sum()

df["ville"] = df.apply(
    find_ville,
    axis=1
)

note(
    f"\n### 7) Ville récupérée depuis "
    f"titre/description : "
    f"{before_missing - df['ville'].isna().sum()}/"
    f"{before_missing} comblées"
)

note(
    f"Villes toujours manquantes : "
    f"{df['ville'].isna().sum()}"
)


# ============================================================
# 7) NUMERIC CONVERSION
# ============================================================

numeric_columns = [
    "surface_m2",
    "nb_pieces",
    "nb_chambres",
    "nb_salles_bain",
]

for col in numeric_columns:

    df[col] = pd.to_numeric(
        df[col],
        errors="coerce"
    )


# ============================================================
# 8) SURFACE CLEANING
# ============================================================

surface_lo, surface_hi = BOUNDS["surface_m2"]

invalid_surface = (
    df["surface_m2"].notna()
    & (
        (df["surface_m2"] < surface_lo)
        | (df["surface_m2"] > surface_hi)
    )
)

note(
    f"\n### 8) Surfaces hors bornes "
    f"[{surface_lo} ; {surface_hi}] m² : "
    f"{invalid_surface.sum()} invalidées"
)

df.loc[
    invalid_surface,
    "surface_m2"
] = np.nan


# ============================================================
# 9) ROOMS / BEDROOMS / BATHROOMS
# ============================================================

def extract_structured_or_prose(
    text,
    label_pattern,
    bound=(0, 20)
):

    if not isinstance(text, str):
        return None

    lo, hi = bound

    # Example:
    # "Chambres 3"
    pattern_1 = (
        label_pattern
        + r"\s+(\d{1,3})\b"
    )

    m = re.search(
        pattern_1,
        text,
        flags=re.IGNORECASE
    )

    if m:

        value = int(m.group(1))

        if lo <= value <= hi:
            return value

    # Example:
    # "3 chambres"
    pattern_2 = (
        r"(\d{1,2})\s*"
        + label_pattern
    )

    m2 = re.search(
        pattern_2,
        text,
        flags=re.IGNORECASE
    )

    if m2:

        value = int(m2.group(1))

        if lo <= value <= hi:
            return value

    return None


def fix_column(
    dataframe,
    col,
    label_pattern,
    plausible_bound
):

    lo, hi = plausible_bound

    bad = (
        dataframe[col].isna()
        | (dataframe[col] < lo)
        | (dataframe[col] > hi)
    )

    recovered = dataframe.loc[
        bad,
        "description_brute"
    ].apply(
        lambda text: extract_structured_or_prose(
            text,
            label_pattern,
            plausible_bound
        )
    )

    dataframe.loc[
        bad,
        col
    ] = recovered

    return (
        bad.sum(),
        recovered.notna().sum()
    )


# ------------------------------------------------------------
# BATHROOMS
# ------------------------------------------------------------

n_bad, n_rec = fix_column(
    df,
    "nb_salles_bain",
    r"salles?\s+de\s+bains?",
    BOUNDS["nb_salles_bain"]
)

note(
    f"\n### 9a) nb_salles_bain : "
    f"{n_bad} manquantes/aberrantes, "
    f"{n_rec} récupérées"
)


# ------------------------------------------------------------
# BEDROOMS
# ------------------------------------------------------------

n_bad, n_rec = fix_column(
    df,
    "nb_chambres",
    r"chambres?",
    BOUNDS["nb_chambres"]
)

note(
    f"### 9b) nb_chambres : "
    f"{n_bad} manquantes/aberrantes, "
    f"{n_rec} récupérées"
)


# ============================================================
# 10) NB_PIECES
# ============================================================

"""
IMPORTANT:

Do NOT calculate:

    bedrooms + bathrooms + kitchens + salons

because bathrooms and kitchens are not counted as "pièces"
in the S+N convention.

Instead:

    nb_pieces ≈ nb_chambres + nb_salons

However, we only infer a salon when there is reliable evidence.

If the original nb_pieces is available and plausible, preserve it.

If nb_pieces is missing, attempt to recover it from S+N notation
or from bedrooms + explicitly detected salons.
"""


def extract_s_plus_n(text):

    if not isinstance(text, str):
        return None

    # S+2, S + 2, S+3...
    m = re.search(
        r"\bS\s*\+\s*(\d{1,2})\b",
        text,
        flags=re.IGNORECASE
    )

    if not m:
        return None

    bedrooms = int(m.group(1))

    # S+N = 1 living room + N bedrooms
    pieces = bedrooms + 1

    if BOUNDS["nb_pieces"][0] <= pieces <= BOUNDS["nb_pieces"][1]:
        return pieces

    return None


def extract_nb_salons(text):

    if not isinstance(text, str):
        return None

    text_lower = text.lower()

    if re.search(
        r"\b(?:trois|3)\s+salons?\b",
        text_lower
    ):
        return 3

    if re.search(
        r"\b(?:deux|2)\s+salons?\b",
        text_lower
    ):
        return 2

    if re.search(
        r"\bdouble\s+salon\b",
        text_lower
    ):
        return 2

    # Only return 1 if there is explicit evidence
    if re.search(
        r"\b(?:un|1)\s+salon\b",
        text_lower
    ):
        return 1

    return None


df["nb_pieces_original"] = df["nb_pieces"]

# Preserve valid original nb_pieces
pieces_lo, pieces_hi = BOUNDS["nb_pieces"]

valid_original_pieces = (
    df["nb_pieces"].notna()
    & df["nb_pieces"].between(
        pieces_lo,
        pieces_hi
    )
)

# Start with original valid values
df["nb_pieces_clean"] = np.nan

df.loc[
    valid_original_pieces,
    "nb_pieces_clean"
] = df.loc[
    valid_original_pieces,
    "nb_pieces"
]


# Recover S+N where nb_pieces is missing/invalid
needs_pieces = df["nb_pieces_clean"].isna()

s_plus_n = df.loc[
    needs_pieces,
    "description_brute"
].apply(extract_s_plus_n)

df.loc[
    needs_pieces,
    "nb_pieces_clean"
] = s_plus_n


# For remaining missing values:
# bedrooms + explicitly detected salons
needs_pieces = df["nb_pieces_clean"].isna()

explicit_salons = df.loc[
    needs_pieces,
    "description_brute"
].apply(extract_nb_salons)

can_calculate = (
    needs_pieces
    & df["nb_chambres"].notna()
)

calculated_pieces = (
    df.loc[can_calculate, "nb_chambres"]
    + explicit_salons.loc[can_calculate].fillna(1)
)

calculated_pieces = calculated_pieces.where(
    calculated_pieces.between(
        pieces_lo,
        pieces_hi
    )
)

df.loc[
    can_calculate,
    "nb_pieces_clean"
] = calculated_pieces


df["nb_pieces"] = df["nb_pieces_clean"]

df.drop(
    columns=["nb_pieces_clean"],
    inplace=True
)


note(
    f"\n### 10) nb_pieces nettoyé : "
    f"{df['nb_pieces'].notna().sum()}/"
    f"{len(df)} lignes"
)


# ============================================================
# 11) LOGICAL CONSISTENCY
# ============================================================

# Bedrooms cannot exceed total pieces
invalid_bedroom_piece = (
    df["nb_chambres"].notna()
    & df["nb_pieces"].notna()
    & (df["nb_chambres"] > df["nb_pieces"])
)

note(
    f"\n### 11) Incohérences "
    f"nb_chambres > nb_pieces : "
    f"{invalid_bedroom_piece.sum()}"
)

# Do not silently delete the listing.
# Invalidate the inconsistent bedroom value.
df.loc[
    invalid_bedroom_piece,
    "nb_chambres"
] = np.nan


# ============================================================
# 12) EXPLICIT FINAL BOUNDS FOR ROOMS
# ============================================================

for col in [
    "nb_pieces",
    "nb_chambres",
    "nb_salles_bain",
]:

    lo, hi = BOUNDS[col]

    invalid = (
        df[col].notna()
        & (
            (df[col] < lo)
            | (df[col] > hi)
        )
    )

    note(
        f"### Bornes {col} "
        f"[{lo} ; {hi}] : "
        f"{invalid.sum()} invalidées"
    )

    df.loc[
        invalid,
        col
    ] = np.nan


# ============================================================
# 13) BOOLEAN NORMALIZATION
# ============================================================

BOOLEAN_COLUMNS = [
    "ascenseur",
    "parking",
    "piscine",
    "climatisation",
    "chauffage_central",
    "meuble",
]


TRUE_VALUES = {
    "true",
    "1",
    "yes",
    "oui",
    "o",
    "vrai",
    "available",
    "disponible",
    "present",
    "présent",
}

FALSE_VALUES = {
    "false",
    "0",
    "no",
    "non",
    "n",
    "faux",
    "absent",
    "non disponible",
}


def normalize_boolean(value):

    if pd.isna(value):
        return np.nan

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, (int, float)):

        if value == 1:
            return 1

        if value == 0:
            return 0

    value = str(value).strip().lower()

    if value in TRUE_VALUES:
        return 1

    if value in FALSE_VALUES:
        return 0

    return np.nan


for col in BOOLEAN_COLUMNS:

    df[col] = df[col].apply(
        normalize_boolean
    )

    df[col] = df[col].astype("Int64")

    note(
        f"### Boolean {col} : "
        f"{df[col].isna().sum()} inconnues"
    )


# ============================================================
# 14) FLOOR NORMALIZATION
# ============================================================

def normalize_floor(value):

    if pd.isna(value):
        return "unknown"

    text = str(value).strip().lower()

    if not text:
        return "unknown"

    # Ground floor
    ground_patterns = [
        r"\brdc\b",
        r"\brez[- ]?de[- ]?chauss[ée]e\b",
        r"\bground\s+floor\b",
        r"\bground\b",
        r"\b0\s*(er|ème|e)?\s*étage\b",
    ]

    for pattern in ground_patterns:

        if re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        ):
            return "ground_floor"

    # Basement
    if re.search(
        r"\bsous[- ]sol\b|\bbasement\b",
        text,
        flags=re.IGNORECASE
    ):
        return "basement"

    # Last floor
    if re.search(
        r"\bdernier\s+étage\b|\blast\s+floor\b",
        text,
        flags=re.IGNORECASE
    ):
        return "last_floor"

    # Numeric floor
    m = re.search(
        r"\b(\d{1,2})\s*(?:er|ème|eme|e)?\s*étage\b",
        text,
        flags=re.IGNORECASE
    )

    if m:
        return f"floor_{m.group(1)}"

    # "Etage 3"
    m = re.search(
        r"\bétage\s*(\d{1,2})\b",
        text,
        flags=re.IGNORECASE
    )

    if m:
        return f"floor_{m.group(1)}"

    return "unknown"


df["etage_original"] = df["etage"]

df["etage"] = df["etage"].apply(
    normalize_floor
)


# ============================================================
# 15) CALCULATE PRIX_M2
# ============================================================

# At this point surface and price have already been cleaned.

df["prix_m2"] = np.where(
    df["surface_m2"].notna()
    & df["prix_dt"].notna()
    & (df["surface_m2"] > 0),
    df["prix_dt"] / df["surface_m2"],
    np.nan
)


# ============================================================
# 16) EXPLICIT PRIX_M2 BOUNDS
# ============================================================

price_m2_lo, price_m2_hi = BOUNDS["prix_m2"]

invalid_price_m2 = (
    df["prix_m2"].notna()
    & (
        (df["prix_m2"] < price_m2_lo)
        | (df["prix_m2"] > price_m2_hi)
    )
)

note(
    f"\n### 12) prix_m2 hors bornes "
    f"[{price_m2_lo} ; {price_m2_hi}] : "
    f"{invalid_price_m2.sum()} valeurs"
)

# IMPORTANT:
# prix_m2 is mainly an audit feature.
# Do not automatically delete these listings here.
#
# We mark invalid prix_m2 as NaN rather than immediately
# deleting the entire property listing.

df.loc[
    invalid_price_m2,
    "prix_m2"
] = np.nan


# ============================================================
# 17) STATISTICAL OUTLIER DETECTION
# ============================================================

"""
Use IQR only as a SECONDARY outlier detector.

The explicit bounds above are the hard rules.

For IQR:
    - group by governorate
    - preserve NaN governorates
    - don't delete listings just because prix_m2 is statistically
      unusual
    - mark extreme prix_m2 as NaN

This avoids accidentally deleting legitimate expensive properties.
"""


def iqr_outlier_mask(
    series,
    k=2.5
):

    valid = series.dropna()

    if len(valid) < 10:
        return pd.Series(
            False,
            index=series.index
        )

    q1 = valid.quantile(0.25)
    q3 = valid.quantile(0.75)

    iqr = q3 - q1

    if pd.isna(iqr) or iqr == 0:
        return pd.Series(
            False,
            index=series.index
        )

    lower = q1 - k * iqr
    upper = q3 + k * iqr

    return (
        (series < lower)
        | (series > upper)
    ).fillna(False)


# Keep rows with unknown governorate.
iqr_flags = (
    df.groupby(
        "gouvernorat",
        dropna=False,
        group_keys=False
    )["prix_m2"]
    .apply(iqr_outlier_mask)
)

# Align index safely
iqr_flags = iqr_flags.reindex(
    df.index,
    fill_value=False
)

note(
    f"### 13) Outliers statistiques prix_m2 "
    f"(IQR x2.5) détectés : "
    f"{iqr_flags.sum()}"
)

# IMPORTANT:
# We do NOT delete the listing.
# We only invalidate prix_m2.
#
# The target prix_dt remains untouched.
#
df.loc[
    iqr_flags,
    "prix_m2"
] = np.nan


# ============================================================
# 18) FINAL PRICE BOUNDS
# ============================================================

price_lo, price_hi = BOUNDS["prix_dt"]

invalid_price = (
    df["prix_dt"].notna()
    & (
        (df["prix_dt"] < price_lo)
        | (df["prix_dt"] > price_hi)
    )
)

note(
    f"\n### 14) Prix hors bornes finales "
    f"[{price_lo:,} ; {price_hi:,}] : "
    f"{invalid_price.sum()}"
)

df.loc[
    invalid_price,
    "prix_dt"
] = np.nan


# ============================================================
# 19) SAFE DUPLICATE DETECTION
# ============================================================

"""
Do not use only:
    titre + gouvernorat + surface + prix + chambres

because two genuinely different properties can have exactly
the same values.

We already removed exact source+id duplicates.

Now detect strong content duplicates using a larger combination.
"""

duplicate_cols = [
    "source",
    "titre",
    "gouvernorat",
    "ville",
    "surface_m2",
    "prix_dt",
    "nb_chambres",
    "nb_salles_bain",
]

# Normalize title before duplicate detection
df["_titre_normalized"] = (
    df["titre"]
    .fillna("")
    .astype(str)
    .str.lower()
    .str.strip()
    .str.replace(
        r"\s+",
        " ",
        regex=True
    )
)

duplicate_cols_for_check = [
    "source",
    "_titre_normalized",
    "gouvernorat",
    "ville",
    "surface_m2",
    "prix_dt",
    "nb_chambres",
    "nb_salles_bain",
]

duplicate_content = df.duplicated(
    subset=duplicate_cols_for_check,
    keep=False
)

note(
    f"\n### 15) Doublons de contenu potentiels : "
    f"{duplicate_content.sum()} lignes"
)

# Remove exact content duplicates.
before = len(df)

df = df.drop_duplicates(
    subset=duplicate_cols_for_check,
    keep="first"
).copy()

note(
    f"### Doublons de contenu supprimés : "
    f"{before - len(df)}"
)

df.drop(
    columns=["_titre_normalized"],
    inplace=True
)


# ============================================================
# 20) REMOVE INVALID TARGET ROWS FOR TRAINING
# ============================================================

"""
A regression model cannot train without a target.

Therefore:
    clean dataset:
        can contain listings with missing prix_dt

    train-ready dataset:
        prix_dt MUST be present and valid
"""

df_final = df.copy()


# ============================================================
# 21) FINAL COLUMN ORGANIZATION
# ============================================================

# Columns useful for audit / traceability
audit_columns = [
    "id",
    "source",
    "type_transaction",
    "type_bien",
    "gouvernorat",
    "ville",
    "prix_dt_original",
    "prix_dt",
    "prix_m2",
    "surface_m2",
    "nb_pieces_original",
    "nb_pieces",
    "nb_chambres",
    "nb_salles_bain",
    "etage_original",
    "etage",
    "ascenseur",
    "parking",
    "piscine",
    "climatisation",
    "chauffage_central",
    "meuble",
]

# Keep only columns that actually exist
audit_columns = [
    col
    for col in audit_columns
    if col in df_final.columns
]

df_final = df_final[
    audit_columns
].reset_index(drop=True)


# ============================================================
# 22) TRAINING FEATURES
# ============================================================

"""
IMPORTANT DATA LEAKAGE RULE:

prix_dt = TARGET

prix_m2 = prix_dt / surface_m2

Therefore prix_m2 MUST NOT be part of X.
"""

model_features = [
    "source",
    "type_bien",
    "gouvernorat",
    "ville",
    "surface_m2",
    "nb_pieces",
    "nb_chambres",
    "nb_salles_bain",
    "etage",
    "ascenseur",
    "parking",
    "piscine",
    "climatisation",
    "chauffage_central",
    "meuble",
]

target = "prix_dt"


# ============================================================
# 23) TRAIN-READY DATASET
# ============================================================

before_train = len(df_final)

df_train_ready = df_final[
    df_final["prix_dt"].notna()
].copy()

note(
    f"\n### Train-ready : "
    f"{len(df_train_ready)}/{before_train} lignes "
    f"avec prix_dt valide"
)


# ============================================================
# 24) SAVE CLEAN DATASET
# ============================================================

df_final.to_csv(
    OUT_PATH,
    index=False
)

# Training-ready dataset contains target + model features.
train_columns = model_features + [target]

df_train_model = df_train_ready[
    [
        col
        for col in train_columns
        if col in df_train_ready.columns
    ]
].copy()

df_train_model.to_csv(
    TRAIN_READY_PATH,
    index=False
)


# ============================================================
# 25) REPORT
# ============================================================

note(
    f"\n## Dataset final : "
    f"{len(df_final)} lignes "
    f"({len(df_final)/n0*100:.1f}% du brut original)"
)

note(
    "\n### Valeurs manquantes restantes :\n"
    + (
        df_final.isna()
        .mean()
        .mul(100)
        .round(1)
        .to_string()
    )
)

note(
    "\n### Features utilisées pour le modèle :\n"
    + "\n".join(
        f"- {col}"
        for col in model_features
    )
)

note(
    f"\n### Target : {target}"
)

note(
    "\n### IMPORTANT : prix_m2 est conservé pour "
    "l'audit/outlier detection mais exclu des "
    "features du modèle pour éviter le data leakage."
)


# ============================================================
# SAVE REPORT
# ============================================================

with open(
    REPORT_PATH,
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "# Rapport de nettoyage — "
        "dataset_immo_tunisie "
        "(vente uniquement)\n\n"
    )

    f.write(
        "\n".join(log)
    )


# ============================================================
# FINAL OUTPUT
# ============================================================

print("\n==============================================")
print("NETTOYAGE TERMINÉ")
print("==============================================")

print("\nSaved clean dataset:")
print(OUT_PATH)

print("\nSaved training-ready dataset:")
print(TRAIN_READY_PATH)

print("\nSaved cleaning report:")
print(REPORT_PATH)

print("\nTraining features:")
print(model_features)

print("\nTarget:")
print(target)

print("\nprix_m2:")
print("UTILISÉ POUR LE CONTRÔLE / OUTLIERS UNIQUEMENT")
print("PAS UTILISÉ COMME FEATURE DU MODÈLE")