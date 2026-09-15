"""
Pipeline de nettoyage — dataset_immo_tunisie.csv
=================================================
Corrige les bugs de scraping identifiés (prix Tecnocasa = mensualité crédit,
prix Mubawab quasi tous manquants, prix Tayara avec valeurs aberrantes par
concaténation), normalise les gouvernorats, dédoublonne et prépare un
dataset propre pour la modélisation (régression du prix).
"""
import pandas as pd
import numpy as np
import re
from collections import Counter

IN_PATH = "/mnt/user-data/uploads/dataset_immo_tunisie.csv"
OUT_PATH = "/mnt/user-data/outputs/dataset_immo_tunisie_clean.csv"
REPORT_PATH = "/mnt/user-data/outputs/rapport_nettoyage.md"

log = []  # collect stats for the report
def note(msg):
    print(msg)
    log.append(msg)

df = pd.read_csv(IN_PATH)
n0 = len(df)
note(f"## Dataset brut : {n0} lignes, {df.shape[1]} colonnes")
note(f"Sources : {dict(df['source'].value_counts())}")

# ---------------------------------------------------------------
# 1) Suppression des lignes 'inconnu' (annonces hors périmètre :
#    voiture, terrain nu, transaction non déterminée)
# ---------------------------------------------------------------
before = len(df)
df = df[df['type_transaction'].isin(['vente', 'location'])].copy()
note(f"\n### 1) type_transaction='inconnu' supprimées : {before - len(df)} lignes retirées")

# ---------------------------------------------------------------
# 2) Extraction robuste du prix depuis description_brute
#    (le prix apparaît en général 2x dans le texte scrapé -> on prend
#    le nombre le plus fréquent, et le plus petit en cas d'égalité,
#    pour éviter les artefacts de concaténation ex: "10 455 000" au
#    lieu de "455 000")
# ---------------------------------------------------------------
def extract_price_candidates_tnd(text):
    if not isinstance(text, str):
        return []
    matches = re.findall(r'(\d{1,3}(?:[\s\u202f]\d{3}){0,3})\s*TND\b', text)
    out = []
    for m in matches:
        num = re.sub(r'[\s\u202f]', '', m)
        if num.isdigit():
            out.append(int(num))
    return out

def best_price_tnd(text):
    cands = extract_price_candidates_tnd(text)
    if not cands:
        return None
    c = Counter(cands)
    mc = max(c.values())
    return sorted(v for v, ct in c.items() if ct == mc)[0]

def extract_tecnocasa_price(text):
    """Sur Tecnocasa le champ prix_dt scrapé = mensualité de crédit
    ('2.381 DT par mois'), pas le prix réel. Le vrai prix apparaît
    juste après la surface dans le bloc résumé ('112 m² 135 000 DT')."""
    if not isinstance(text, str):
        return None
    m = re.search(r'm²\s*([\d][\d\s.]{2,10})\s*DT\b', text)
    if m:
        num = re.sub(r'[\s.]', '', m.group(1))
        if num.isdigit():
            return int(num)
    return None

df['prix_dt_original'] = df['prix_dt']

# 2a) Tecnocasa : le prix scrapé est systématiquement faux (mensualité
#     crédit). On le remplace entièrement par le prix ré-extrait.
mask_tec = df['source'] == 'tecnocasa'
fixed = df.loc[mask_tec, 'description_brute'].apply(extract_tecnocasa_price)
n_fixed = fixed.notna().sum()
df.loc[mask_tec, 'prix_dt'] = fixed
note(f"\n### 2) Prix Tecnocasa corrigés (mensualité crédit -> prix réel) : {n_fixed}/{mask_tec.sum()}")

# 2b) Mubawab : prix_dt manquant à 99% -> extraction depuis le texte
mask_mub = (df['source'] == 'mubawab') & (df['prix_dt'].isna())
filled = df.loc[mask_mub, 'description_brute'].apply(best_price_tnd)
n_filled = filled.notna().sum()
df.loc[mask_mub, 'prix_dt'] = filled
note(f"### 3) Prix Mubawab manquants comblés depuis le texte : {n_filled}/{mask_mub.sum()}")

# 2c) Tayara : quelques prix aberrants par concaténation de chiffres
#     (ex: 92 948 824 320 DT). On applique un seuil de plausibilité par
#     type de transaction et on tente une ré-extraction sinon on met NaN.
def tayara_bounds(type_transaction):
    if type_transaction == 'vente':
        return 5_000, 8_000_000       # TND, prix de vente Tunisie plausible
    else:
        return 150, 20_000            # TND/mois, loyer plausible

bounds = df['type_transaction'].apply(tayara_bounds)
low = bounds.apply(lambda b: b[0])
high = bounds.apply(lambda b: b[1])
out_of_range = (df['source'] == 'tayara') & ((df['prix_dt'] < low) | (df['prix_dt'] > high))
n_outliers = out_of_range.sum()
retry = df.loc[out_of_range, 'description_brute'].apply(best_price_tnd)
df.loc[out_of_range, 'prix_dt'] = retry  # NaN si non récupérable
note(f"### 4) Prix Tayara hors bornes plausibles : {n_outliers} détectés, "
     f"{retry.notna().sum()} corrigés, {retry.isna().sum()} mis à NaN (irrécupérables)")

note(f"\nTaux de prix manquant après nettoyage : {df['prix_dt'].isna().mean()*100:.1f}% "
     f"(vs {df['prix_dt_original'].isna().mean()*100:.1f}% avant)")

# ---------------------------------------------------------------
# 3) Normalisation des gouvernorats (quartiers/délégations mal
#    étiquetés comme gouvernorat, notamment côté Tecnocasa)
# ---------------------------------------------------------------
OFFICIAL = {'Tunis','Ariana','Ben Arous','Manouba','Nabeul','Zaghouan','Bizerte','Béja','Jendouba','Le Kef',
'Siliana','Sousse','Monastir','Mahdia','Sfax','Kairouan','Kasserine','Sidi Bouzid','Gabès','Médenine',
'Tataouine','Gafsa','Tozeur','Kébili'}

ALIAS = {
    'el menzah':'Tunis', 'le bardo':'Tunis', 'ennasr':'Ariana',
    'bizerte nord':'Bizerte', 'sahloul':'Sousse', 'sousse centre ville':'Sousse',
    'kélibia':'Nabeul', 'hammamet':'Nabeul', 'hergla':'Sousse', 'akouda':'Sousse',
    'hammam sousse':'Sousse', 'sousse riadh':'Sousse', 'khezama':'Monastir', 'kef':'Le Kef',
}

def normalize_gouv(val):
    if not isinstance(val, str):
        return None
    v = val.strip()
    if v in OFFICIAL:
        return v
    base = v.split(',')[0].strip()
    if base in OFFICIAL:
        return base
    key = base.lower()
    if key in ALIAS:
        return ALIAS[key]
    if v.lower() in ALIAS:
        return ALIAS[v.lower()]
    return None

df['gouvernorat_original'] = df['gouvernorat']
df['gouvernorat'] = df['gouvernorat'].apply(normalize_gouv)
n_unresolved = df['gouvernorat'].isna().sum()
note(f"\n### 5) Gouvernorats normalisés sur les 24 officiels. Non résolus (mis à NaN) : {n_unresolved}")

# ---------------------------------------------------------------
# 4) Séparation vente / location (déjà garanti à l'étape 1, on le
#    documente juste ici en variable dérivée + prix au m²)
# ---------------------------------------------------------------
df['prix_m2'] = np.where(df['surface_m2'] > 0, df['prix_dt'] / df['surface_m2'], np.nan)

# ---------------------------------------------------------------
# 5) Filtrage des outliers restants (IQR sur prix_m2, PAR gouvernorat
#    ET type_transaction, car les échelles varient énormément selon
#    la région -> un prix "normal" à Tunis ne l'est pas à Kasserine)
# ---------------------------------------------------------------
def iqr_mask(group, col, k=2.5):
    q1, q3 = group[col].quantile([0.25, 0.75])
    iqr = q3 - q1
    if iqr == 0 or pd.isna(iqr):
        return pd.Series(True, index=group.index)
    lo, hi = q1 - k*iqr, q3 + k*iqr
    return group[col].between(lo, hi) | group[col].isna()

before = len(df)
df = df.reset_index(drop=True)
keep = df.groupby(['gouvernorat', 'type_transaction'], group_keys=False).apply(
    lambda g: iqr_mask(g, 'prix_m2')
).reindex(df.index)
df = df[keep].copy()
note(f"\n### 6) Outliers prix_m2 retirés (IQR x2.5, par gouvernorat+transaction) : {before - len(df)} lignes")

# also drop rows where surface_m2 == 0 (nonsensical) and prix_dt <= 0
before = len(df)
df = df[~((df['surface_m2'] == 0))]
note(f"### 7) Lignes surface_m2=0 retirées : {before - len(df)}")

# ---------------------------------------------------------------
# 6) Déduplication (même annonce republiée / reprise sur plusieurs
#    sites) : titre + gouvernorat + surface + prix + nb_pieces
#    identiques => quasi certainement la même annonce
# ---------------------------------------------------------------
before = len(df)
dedup_cols = ['titre', 'gouvernorat', 'surface_m2', 'prix_dt', 'nb_pieces']
df = df.drop_duplicates(subset=dedup_cols, keep='first')
note(f"\n### 8) Doublons retirés (titre+gouvernorat+surface+prix+pièces identiques) : {before - len(df)}")

# ---------------------------------------------------------------
# 7) Colonnes finales pour la modélisation
# ---------------------------------------------------------------
model_cols = ['id', 'source', 'type_transaction', 'type_bien', 'gouvernorat', 'ville',
              'prix_dt', 'prix_m2', 'surface_m2', 'nb_pieces', 'nb_chambres', 'nb_salles_bain',
              'etage', 'ascenseur', 'parking', 'piscine', 'climatisation', 'chauffage_central', 'meuble']
df_final = df[model_cols].reset_index(drop=True)

note(f"\n## Dataset final : {len(df_final)} lignes ({len(df_final)/n0*100:.1f}% du brut conservé), "
     f"{df_final.shape[1]} colonnes")
note(f"\nRépartition vente/location : {dict(df_final['type_transaction'].value_counts())}")
note(f"Taux de valeurs manquantes restantes :\n{(df_final.isna().mean()*100).round(1).to_string()}")

df_final.to_csv(OUT_PATH, index=False)

# Sous-ensemble directement exploitable pour l'entraînement : la cible
# (prix_dt) doit être renseignée, le reste (surface, pièces, etc.) sera
# imputé PLUS TARD, séparément sur train et test, pour éviter toute fuite.
TRAIN_READY_PATH = "/mnt/user-data/outputs/dataset_immo_tunisie_train_ready.csv"
df_train_ready = df_final.dropna(subset=['prix_dt']).reset_index(drop=True)
df_train_ready.to_csv(TRAIN_READY_PATH, index=False)
note(f"\n## Sous-ensemble 'prêt pour l'entraînement' (prix_dt non-null) : "
     f"{len(df_train_ready)} lignes -> {TRAIN_READY_PATH}")
note(f"Répartition : {dict(df_train_ready['type_transaction'].value_counts())}")

with open(REPORT_PATH, "w", encoding="utf-8") as f:
    f.write("# Rapport de nettoyage — dataset_immo_tunisie\n\n")
    f.write("\n".join(log))

print("\n\nSaved:", OUT_PATH)
print("Saved:", REPORT_PATH)
