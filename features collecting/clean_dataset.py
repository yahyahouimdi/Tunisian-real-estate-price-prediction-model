"""
Clean Tunisian real-estate listings for price-regression modelling.

Scope:
    - Vente uniquement

The pipeline:
    1. Validates identifiers and sources
    2. Keeps sale listings only
    3. Cleans and reconstructs prices (Tecnocasa fix, Tayara re-parse
       after the title, prices written in thousands)
    4. Normalizes governorates and cities, fixes city/governorate
       conflicts, adds region, groups rare categories
    5. Cleans surface and builds one bedroom feature (S+N)
    6. Normalizes amenities: 1 / 0 / unknown for free-text sources
    7. Normalizes floor information (+ numeric etage_num)
    8. Applies explicit plausibility bounds
    9. Computes prix_m2: too high -> price invalid, too low -> surface
       invalid; removes placeholder prices
   10. Flags statistical prix_m2 outliers (outlier_prix_m2)
   11. Removes duplicates, incl. the same property across sites, and
       builds groupe_bien for grouped train/test splits
   12. Exports clean and training-ready datasets

IMPORTANT:
    prix_m2 is derived from prix_dt and MUST NOT be used as a
    model input feature when prix_dt is the target.
"""

import re
import unicodedata
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

# Old scraper (raw_v1): prix_dt could be the monthly credit value and the
# real price was in the card text. The current scraper reads the numeric
# price from the page JSON: its descriptions don't match the pattern, and
# the scraped price is kept.
df.loc[
    fixed.index[fixed.notna()],
    "prix_dt"
] = fixed[fixed.notna()]

note(
    f"\n### 2) Prix Tecnocasa corrigés (format ancien scraper) : "
    f"{fixed.notna().sum()}/{mask_tec.sum()}"
)


# ------------------------------------------------------------
# 4a-bis) TAYARA
# ------------------------------------------------------------

"""
Tayara page text contains "<titre> <prix> DT". The scraper parsed
the price with a greedy regex, so trailing digits of the title were
glued onto the price:

    "MENZAH 6"  + "248 000 DT"  ->  6 248 000
    "99958728"  + "550 000 DT"  ->  728 550 000

We re-parse the number located immediately after the exact title.

Sellers also often write prices in thousands ("280 DT" = 280 000 DT).
Values in THOUSANDS_RANGE are multiplied by 1000, and kept only if the
result passes the price bounds and the prix_m2 bounds (when the surface
is known).
"""

THOUSANDS_RANGE = (30, 5_000)


def extract_tayara_price(title, text):

    if not isinstance(title, str) or not isinstance(text, str):
        return None

    title = re.sub(r"\s+", " ", title).strip()
    text = re.sub(r"\s+", " ", text)

    if not title:
        return None

    m = re.search(
        re.escape(title)
        + r" ?(\d{1,3}(?:[ . ]\d{3})*) ?DT\b",
        text
    )

    if not m:
        return None

    return int(re.sub(r"[ . ]", "", m.group(1)))


mask_tay = df["source"].eq("tayara")

tay_parsed = df.loc[mask_tay].apply(
    lambda row: extract_tayara_price(
        row["titre"],
        row["description_brute"]
    ),
    axis=1
)

tay_parsed = pd.to_numeric(tay_parsed, errors="coerce")

old_tay_price = pd.to_numeric(
    df.loc[mask_tay, "prix_dt"],
    errors="coerce"
)

# Re-parsing only applies to the old scraper (raw_v1), whose text held
# "<titre> <prix> DT". The current scraper reads the numeric price from the
# page JSON: it is kept, and only the thousands rule below applies to it.
reparsed = tay_parsed.notna()

tay_parsed = tay_parsed.fillna(old_tay_price)

tay_surface = pd.to_numeric(
    df.loc[mask_tay, "surface_m2"],
    errors="coerce"
)

# Prices written in thousands
in_thousands = tay_parsed.between(*THOUSANDS_RANGE)

scaled = tay_parsed.where(~in_thousands, tay_parsed * 1000)

scaled_m2 = scaled / tay_surface

scaled_ok = (
    scaled.between(PRICE_FLOOR, PRICE_CEIL)
    & (
        tay_surface.isna()
        | scaled_m2.between(*BOUNDS["prix_m2"])
    )
)

# Thousands values that fail the checks become missing
tay_parsed = scaled.where(~in_thousands | scaled_ok)

matched = tay_parsed.notna() | (in_thousands & ~scaled_ok)

changed = matched & (tay_parsed != old_tay_price)

df.loc[
    tay_parsed.index[matched],
    "prix_dt"
] = tay_parsed[matched]

note(
    f"### 2b) Prix Tayara : {reparsed.sum()}/{mask_tay.sum()} re-parsés "
    f"après le titre (ancien scraper), "
    f"{changed.sum()} modifiés "
    f"(dont {(in_thousands & scaled_ok).sum()} écrits en milliers x1000, "
    f"{(in_thousands & ~scaled_ok).sum()} milliers rejetés)"
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

# Mubawab is excluded: a page without price ("Prix à consulter") still
# shows the prices of OTHER listings (similar ads), which would be
# picked up here.
can_recover = df["source"].ne("mubawab")

still_missing = df["prix_dt"].isna() & can_recover

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
] = pd.to_numeric(tnd_fill, errors="coerce")

note(
    f"### 4) Prix récupérés via 'TND' : "
    f"{tnd_fill.notna().sum()}/{still_missing.sum()}"
)


# ------------------------------------------------------------
# 4e) DT EXTRACTION
# ------------------------------------------------------------

still_missing = df["prix_dt"].isna() & can_recover

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
] = pd.to_numeric(dt_fill, errors="coerce")

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


def _strip_accents(text):

    text = unicodedata.normalize("NFKD", text)

    return "".join(c for c in text if not unicodedata.combining(c))


OFFICIAL_BY_KEY = {
    _strip_accents(g.lower()): g
    for g in OFFICIAL
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

    # "tunis", "Gabes", "Medenine"... -> official spelling
    base_key = _strip_accents(base_lower)

    if base_key in OFFICIAL_BY_KEY:
        return OFFICIAL_BY_KEY[base_key]

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

# Mubawab pages show the city before the governorate and the price:
#   "... 2 Salles de bains El Aouina à Tunis 455 000 TND"
MUBAWAB_VILLE = re.compile(
    r"(?:m²|Pièces?|Chambres?|Salles? de bains?|Contacter)\s+"
    r"([^\d\n]{2,40}?)\s+à\s+(?:"
    + "|".join(re.escape(g) for g in OFFICIAL | {"Kef"})
    + r")\s+\d"
)


def extract_mubawab_ville(text):

    if not isinstance(text, str):
        return pd.NA

    m = MUBAWAB_VILLE.search(text)

    return m.group(1).strip() if m else pd.NA


mask_mub_ville = df["source"].eq("mubawab") & df["ville"].isna()

mub_ville = df.loc[mask_mub_ville, "description_brute"].apply(
    extract_mubawab_ville
)

df.loc[mask_mub_ville, "ville"] = mub_ville

note(
    f"\n### 7a) Ville Mubawab récupérée depuis la page : "
    f"{mub_ville.notna().sum()}/{mask_mub_ville.sum()}"
)

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


# ------------------------------------------------------------
# 7b) NORMALIZE CITY SPELLING
# ------------------------------------------------------------

"""
The same place is written many ways:
    "Cité Ennasr 2" / "cit ennasr 2" / "Ennasr 2"
    "El Aouina" / "L Aouina" / "Laouina"
    "Ariana Ville" / "Nabeul centre-ville"

We lowercase, strip accents and punctuation, remove "cité",
leading articles and "ville / centre-ville" suffixes.
"""


def normalize_ville(value):

    if pd.isna(value):
        return pd.NA

    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[’'`\-_,./()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if text in {"", "autres villes", "autre", "autres"}:
        return pd.NA

    text = re.sub(r"\b(?:cite|cit)\b", " ", text)
    text = re.sub(r"\bcentre ville\b|\bville\b", " ", text)
    text = re.sub(r"^(?:el|l|la|le|les)\s+", "", text.strip())
    text = re.sub(r"^laouina$", "aouina", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text if text else pd.NA


n_raw_villes = df["ville"].dropna().nunique()

df["ville_original"] = df["ville"]
df["ville"] = df["ville"].apply(normalize_ville)

note(
    f"### 7b) Orthographe des villes normalisée : "
    f"{n_raw_villes} -> {df['ville'].dropna().nunique()} villes distinctes"
)


# ------------------------------------------------------------
# 7c) CITY / GOVERNORATE CONFLICTS
# ------------------------------------------------------------

"""
A well-known city (>= 3 listings, >= 80% in one governorate) fixes the
governorate of the rare rows that disagree, e.g. "Hammamet" labelled
"Tunis" -> "Nabeul".
"""

ville_gouv = (
    df.dropna(subset=["ville", "gouvernorat"])
    .groupby("ville")["gouvernorat"]
    .agg(
        dominant=lambda s: s.mode().iloc[0],
        share=lambda s: s.value_counts(normalize=True).iloc[0],
        n="size",
    )
)

reliable = ville_gouv[(ville_gouv["n"] >= 3) & (ville_gouv["share"] >= 0.8)]

expected_gouv = df["ville"].map(reliable["dominant"])

gouv_conflict = expected_gouv.notna() & (df["gouvernorat"] != expected_gouv)

note(
    f"### 7c) Conflits ville/gouvernorat corrigés : {gouv_conflict.sum()}"
)

df.loc[gouv_conflict, "gouvernorat"] = expected_gouv[gouv_conflict]


# ------------------------------------------------------------
# 7d) REGION + RARE CATEGORIES
# ------------------------------------------------------------

"""
Rare categories cannot be learned and make a grouped/stratified split
fail. Counts use listings with a known price (the rows the model
learns from); only the presence of the target is used, not its value.

    region      : the 7 official INS regions of Tunisia (new feature)
    gouvernorat : < MIN_GOUV listings  -> "Autre_<region>"
    ville       : < MIN_VILLE listings -> "autre_<gouvernorat>"
"""

REGIONS = {
    "Grand Tunis": ["Tunis", "Ariana", "Ben Arous", "Manouba"],
    "Nord-Est": ["Nabeul", "Zaghouan", "Bizerte"],
    "Nord-Ouest": ["Béja", "Jendouba", "Le Kef", "Siliana"],
    "Centre-Est": ["Sousse", "Monastir", "Mahdia", "Sfax"],
    "Centre-Ouest": ["Kairouan", "Kasserine", "Sidi Bouzid"],
    "Sud-Est": ["Gabès", "Médenine", "Tataouine"],
    "Sud-Ouest": ["Gafsa", "Tozeur", "Kébili"],
}

GOUV_TO_REGION = {
    gouv: region
    for region, gouvs in REGIONS.items()
    for gouv in gouvs
}

MIN_GOUV = 10
MIN_VILLE = 5

df["region"] = df["gouvernorat"].map(GOUV_TO_REGION)

# Rare cities first, while the governorate name is still precise
priced = df["prix_dt"].notna()

ville_counts = df["ville"].map(
    df.loc[priced, "ville"].value_counts()
).fillna(0)

rare_ville = df["ville"].notna() & (ville_counts < MIN_VILLE)

df.loc[rare_ville, "ville"] = (
    "autre_" + df.loc[rare_ville, "gouvernorat"].astype(str).str.lower()
)

gouv_counts = df["gouvernorat"].map(
    df.loc[priced, "gouvernorat"].value_counts()
).fillna(0)

rare_gouv = df["gouvernorat"].notna() & (gouv_counts < MIN_GOUV)

note(
    f"### 7d) Villes rares (< {MIN_VILLE}) regroupées : {rare_ville.sum()} lignes "
    f"-> {df['ville'].dropna().nunique()} catégories de ville\n"
    f"### Gouvernorats rares (< {MIN_GOUV}) regroupés par région : "
    f"{rare_gouv.sum()} lignes "
    f"({', '.join(sorted(df.loc[rare_gouv, 'gouvernorat'].unique()))})"
)

df.loc[rare_gouv, "gouvernorat"] = "Autre_" + df.loc[rare_gouv, "region"]

# City buckets still too small (e.g. "autre_gafsa") -> "autre_<region>"
ville_counts = df["ville"].map(
    df.loc[priced, "ville"].value_counts()
).fillna(0)

still_rare = df["ville"].notna() & (ville_counts < MIN_VILLE)

df.loc[still_rare, "ville"] = (
    "autre_" + df.loc[still_rare, "region"].str.lower()
)

note(
    f"### Petits groupes de villes fusionnés par région : {still_rare.sum()} lignes "
    f"-> {df['ville'].dropna().nunique()} catégories de ville"
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

    recovered = pd.to_numeric(recovered, errors="coerce")

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
# BEDROOMS (single consistent feature: N of "S+N")
# ------------------------------------------------------------

"""
Tunisian listings describe size as "S+N" where N = number of bedrooms.

The scraper stored this N in nb_pieces (common.extract_pieces), and
filled nb_chambres with "X chambres" from the text OR a copy of
nb_pieces. The two columns were therefore mostly the same value, and
a mix of conventions produced fake "nb_chambres > nb_pieces" conflicts.

We build ONE feature, nb_chambres = N, by priority:
    1. S+N in the title
    2. scraper nb_pieces (S+N found in the page text)
    3. "X chambres" / "Chambres X" in the description

nb_pieces is kept only as nb_pieces_original for auditing and is NOT
a model feature (it would just be nb_chambres + 1).
"""

S_PLUS_N = re.compile(r"\bS\s*\+?\s*(\d{1,2})\b", re.IGNORECASE)


def extract_s_plus_n(text):

    if not isinstance(text, str):
        return np.nan

    m = S_PLUS_N.search(text)

    return int(m.group(1)) if m else np.nan


chambres_lo, chambres_hi = BOUNDS["nb_chambres"]

df["nb_pieces_original"] = df["nb_pieces"]
df["nb_chambres_original"] = df["nb_chambres"]

from_title = df["titre"].apply(extract_s_plus_n)

from_scraper = df["nb_pieces"]

from_text = df["description_brute"].apply(
    lambda text: extract_structured_or_prose(
        text,
        r"chambres?",
        BOUNDS["nb_chambres"]
    )
)
from_text = pd.to_numeric(from_text, errors="coerce")

chambres_sources = {
    "titre S+N": from_title,
    "scraper S+N": from_scraper,
    "texte 'X chambres'": from_text,
}

df["nb_chambres"] = np.nan

for label, values in chambres_sources.items():

    usable = (
        df["nb_chambres"].isna()
        & values.between(chambres_lo, chambres_hi)
    )

    df.loc[usable, "nb_chambres"] = values[usable]

    note(
        f"### 9b) nb_chambres depuis {label} : {usable.sum()}"
    )

note(
    f"### nb_chambres final : "
    f"{df['nb_chambres'].notna().sum()}/{len(df)} renseignés "
    f"(nb_pieces retiré des features : doublon de nb_chambres)"
)



# ============================================================
# 12) EXPLICIT FINAL BOUNDS FOR ROOMS
# ============================================================

for col in [
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


# ------------------------------------------------------------
# 13b) AMENITIES FROM FREE TEXT : 1 / 0 / UNKNOWN
# ------------------------------------------------------------

"""
Mubawab amenities come from structured equipment tags: 1/0 is kept.

Tayara and Tecnocasa amenities were set by the scraper to 1 if the
keyword appeared ANYWHERE in the text, else 0. So:
    - 0 meant "not mentioned", not "absent" (source bias: lift is 67%
      on Mubawab vs 11% on Tayara)
    - "sans ascenseur" was counted as 1

For these sources we re-extract from the description:
    1   -> mentioned positively
    0   -> explicitly negated ("sans ascenseur", "non meublé")
    NaN -> not mentioned (unknown; tree models handle missing values)
"""

FREE_TEXT_SOURCES = {"tayara", "tecnocasa"}

AMENITY_PATTERNS = {
    "ascenseur": r"ascenseur|مصعد",
    "parking": r"parking|garage|stationnement|مستودع|مأوى",
    "piscine": r"piscine|مسبح",
    "climatisation": r"climatis\w*|clim\b|climatiseurs?|مكيف\w*",
    "chauffage_central": r"chauffage\s+central\w*|تدفئة\s+مركزية",
    "meuble": r"meubl[ée]e?s?|مفروش\w*",
}

NEGATION = re.compile(
    r"(?:\bsans|\bpas\s+(?:de|d'|du)|\bnon|\bni|\baucun\w*|بدون|دون)"
    r"[\s\w'’,/-]{0,15}$",
    re.IGNORECASE
)


def extract_amenity(text, pattern):

    if not isinstance(text, str):
        return np.nan

    found = np.nan

    for m in re.finditer(pattern, text, flags=re.IGNORECASE):

        before = text[max(0, m.start() - 20):m.start()]

        if NEGATION.search(before):
            found = 0
        else:
            return 1

    return found


mask_free_text = df["source"].isin(FREE_TEXT_SOURCES)

amenity_text = (
    df["titre"].fillna("").astype(str)
    + " "
    + df["description_brute"].fillna("").astype(str)
)

for col, pattern in AMENITY_PATTERNS.items():

    # Tayara: scraper values are keyword-based (0 = not mentioned), always
    # re-extracted. Tecnocasa: the current scraper reads structured
    # equipment (True/False/unknown): text only fills the unknowns.
    to_fill = mask_free_text & (
        df["source"].eq("tayara") | df[col].isna()
    )

    values = amenity_text[to_fill].apply(
        lambda text: extract_amenity(text, pattern)
    )

    df.loc[to_fill, col] = pd.array(values, dtype="Int64")

    note(
        f"### 13b) {col} (Tayara/Tecnocasa, texte libre) : "
        f"{(values == 1).sum()} oui, {(values == 0).sum()} non, "
        f"{values.isna().sum()} non mentionné"
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

# Numeric floor for the model: 9 sparse categories -> 1 ordered value.
#   ground_floor -> 0, floor_n -> n, basement -> -1,
#   last_floor / unknown -> missing (number of the floor not known)


def floor_to_number(value):

    if value == "ground_floor":
        return 0

    if value == "basement":
        return -1

    m = re.fullmatch(r"floor_(\d{1,2})", str(value))

    return int(m.group(1)) if m else np.nan


df["etage_num"] = df["etage"].apply(floor_to_number).astype("Int64")

note(
    f"\n### Étage numérique (etage_num) : "
    f"{df['etage_num'].notna().sum()}/{len(df)} connus"
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

too_low_m2 = invalid_price_m2 & (df["prix_m2"] < price_m2_lo)
too_high_m2 = invalid_price_m2 & (df["prix_m2"] > price_m2_hi)

note(
    f"\n### 12) prix_m2 hors bornes "
    f"[{price_m2_lo} ; {price_m2_hi}] : "
    f"{invalid_price_m2.sum()} valeurs "
    f"({too_low_m2.sum()} trop bas, {too_high_m2.sum()} trop hauts)"
)

# The listing is kept, but the unreliable value is invalidated:
#   - too low  -> surface is most likely the land area, not the
#                 living area: surface_m2 is set missing
#   - too high -> the price itself is implausible: prix_dt is set
#                 missing, so the row is excluded from training

df.loc[too_low_m2, "surface_m2"] = np.nan
df.loc[too_high_m2, "prix_dt"] = np.nan

df.loc[
    invalid_price_m2,
    "prix_m2"
] = np.nan


# Placeholder prices (1 111 000, 111 111, 1 234 567, ...)
def is_placeholder_price(value):

    if pd.isna(value):
        return False

    digits = str(int(value)).rstrip("0")

    return len(digits) >= 4 and (
        len(set(digits)) == 1
        or digits in "123456789"
        or digits in "987654321"
    )


placeholder_price = df["prix_dt"].apply(is_placeholder_price)

note(
    f"### 12b) Prix factices (1 111 000, 1 234 567...) : "
    f"{placeholder_price.sum()} invalidés"
)

df.loc[placeholder_price, ["prix_dt", "prix_m2"]] = np.nan


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
# We only invalidate prix_m2 and flag the row.
#
# The target prix_dt remains untouched. The flag lets the modelling
# step compare results with / without these listings. It is derived
# from the target, so it must NOT be used as a model feature.
#
df["outlier_prix_m2"] = iqr_flags.astype("Int64")

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


# ------------------------------------------------------------
# 19b) SAME PROPERTY, DIFFERENT TITLE / DIFFERENT SITE
# ------------------------------------------------------------

"""
The same property is often reposted with a new title, or posted on
both Tayara and Mubawab. Candidates share:

    gouvernorat + type_bien + prix_dt + surface_m2

Within a candidate group, two rows are the SAME property when their
nb_chambres and ville are compatible (equal, or one is missing).
We keep the most complete row and drop the others.

Rows of a group that are NOT the same property (e.g. different units
of one promoter project) are kept, but share a 'groupe_bien' id so the
train/test split keeps them together (GroupKFold). Every other row
gets its own id as group. groupe_bien is NOT a model feature.
"""

property_key = ["gouvernorat", "type_bien", "prix_dt", "surface_m2"]

completeness = df[
    ["ville", "surface_m2", "nb_chambres", "nb_salles_bain"]
].notna().sum(axis=1) + df["etage"].ne("unknown")


def compatible(a, b):

    if pd.notna(a) and pd.notna(b):
        return str(a).strip().lower() == str(b).strip().lower()

    return True


has_key = df[property_key].notna().all(axis=1)

key_id = (
    df.loc[has_key]
    .groupby(property_key)
    .ngroup()
)

group_size = key_id.map(key_id.value_counts())

df["groupe_bien"] = df["source_id"]

drop_ids = []
n_cross_site = 0

for gid, members in key_id[group_size > 1].groupby(key_id):

    rows = df.loc[members.index].assign(
        _completeness=completeness.loc[members.index]
    ).sort_values("_completeness", ascending=False)

    kept = []

    for idx, row in rows.iterrows():

        same_as = next(
            (
                k for k in kept
                if compatible(row["nb_chambres"], df.at[k, "nb_chambres"])
                and compatible(row["ville"], df.at[k, "ville"])
            ),
            None
        )

        if same_as is None:
            kept.append(idx)
        else:
            drop_ids.append(idx)
            n_cross_site += row["source"] != df.at[same_as, "source"]

    if len(kept) > 1:
        df.loc[kept, "groupe_bien"] = f"bien_{gid}"

note(
    f"### 15b) Même bien (gouvernorat+type+prix+surface, "
    f"chambres/ville compatibles) : {len(drop_ids)} doublons supprimés "
    f"(dont {n_cross_site} inter-sites)"
)

df = df.drop(index=drop_ids).copy()

note(
    f"### Groupes 'groupe_bien' partagés (unités d'un même projet) : "
    f"{df['groupe_bien'].str.startswith('bien_').sum()} lignes, "
    f"{df.loc[df['groupe_bien'].str.startswith('bien_'), 'groupe_bien'].nunique()} groupes"
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
    "groupe_bien",
    "source",
    "type_transaction",
    "type_bien",
    "region",
    "gouvernorat",
    "ville_original",
    "ville",
    "prix_dt_original",
    "prix_dt",
    "prix_m2",
    "outlier_prix_m2",
    "surface_m2",
    "nb_pieces_original",
    "nb_chambres_original",
    "nb_chambres",
    "nb_salles_bain",
    "etage_original",
    "etage",
    "etage_num",
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

Feature selection (kept in the clean/audit file, excluded from X):
    - source   : unknown when a user enters their own property;
                 weak signal (median prices 310k-360k for all sites)
    - meuble   : almost no relation to price, 61% unknown
    - nb_pieces: duplicate of nb_chambres (S+N)
    - etage    : replaced by the numeric etage_num
"""

model_features = [
    "type_bien",
    "region",
    "gouvernorat",
    "ville",
    "surface_m2",
    "nb_chambres",
    "nb_salles_bain",
    "etage_num",
    "ascenseur",
    "parking",
    "piscine",
    "climatisation",
    "chauffage_central",
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

# Training-ready dataset contains model features + target, plus
# columns that are NOT features:
#   - outlier_prix_m2 : filtering experiments (derived from target)
#   - groupe_bien     : groups for GroupKFold / grouped train-test split
train_columns = model_features + [target, "outlier_prix_m2", "groupe_bien"]

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