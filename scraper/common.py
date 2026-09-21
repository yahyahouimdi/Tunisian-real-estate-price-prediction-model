"""
common.py
Fonctions partagées par les 3 scrapers (Tayara, Mubawab, Tecnocasa) :
- liste des gouvernorats tunisiens (pour matcher la localisation dans le texte)
- extracteurs regex robustes (prix, surface, pièces, chambres, étage, salle de bain)
- sauvegarde en CSV avec un schéma unique
- session HTTP polie (headers + délai entre requêtes)

Approche : plutôt que de dépendre de classes CSS exactes (qui changent souvent
et que je n'ai pas pu inspecter avec certitude via DevTools), on extrait les
infos par regex sur le TEXTE VISIBLE de la page. C'est plus robuste aux
changements de design, tant que le site garde les mêmes formulations
("XXX DT", "XXX m²", "S+3", nom du gouvernorat...).
"""

import csv
import random
import re
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional

import requests

# ----------------------------------------------------------------------
# Config générale
# ----------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

MIN_DELAY = 1.5   # secondes minimum entre 2 requêtes (politesse / anti-ban)
MAX_DELAY = 3.5

GOUVERNORATS = [
    "Tunis", "Ariana", "Ben Arous", "Manouba", "Nabeul", "Zaghouan", "Bizerte",
    "Béja", "Beja", "Jendouba", "Kef", "Le Kef", "Siliana", "Sousse", "Monastir",
    "Mahdia", "Sfax", "Kairouan", "Kasserine", "Sidi Bouzid", "Gabès", "Gabes",
    "Médenine", "Medenine", "Tataouine", "Gafsa", "Tozeur", "Kébili", "Kebili",
    "La Marsa", "La Soukra",  # zones souvent citées seules (Grand Tunis)
]


def get_session() -> requests.Session:
    """Session requests avec un User-Agent réaliste."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.8",
    })
    return s


def polite_sleep():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


# ----------------------------------------------------------------------
# Schéma de sortie unique pour les 3 sites
# ----------------------------------------------------------------------

@dataclass
class Annonce:
    id: str
    source: str                 # "tayara" | "mubawab" | "tecnocasa"
    url: str
    type_transaction: str       # "vente" | "location" | "inconnu"
    type_bien: str              # "appartement" | "maison" | "villa" | "terrain" | ...
    titre: str = ""
    gouvernorat: Optional[str] = None
    ville: Optional[str] = None
    prix_dt: Optional[float] = None
    surface_m2: Optional[float] = None
    nb_pieces: Optional[int] = None      # ex: S+3 -> 3
    nb_chambres: Optional[int] = None
    nb_salles_bain: Optional[int] = None
    etage: Optional[str] = None
    ascenseur: Optional[bool] = None
    parking: Optional[bool] = None
    piscine: Optional[bool] = None
    climatisation: Optional[bool] = None
    chauffage_central: Optional[bool] = None
    meuble: Optional[bool] = None
    description_brute: str = ""
    date_scraping: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    date_publication: Optional[str] = None


FIELDNAMES = list(Annonce.__dataclass_fields__.keys())


# ----------------------------------------------------------------------
# robots.txt (avec jokers * et $, que urllib.robotparser ne gère pas)
# ----------------------------------------------------------------------

_ROBOTS_CACHE: dict[str, list[tuple[bool, re.Pattern]]] = {}


def _load_robots_rules(session: requests.Session, base: str) -> list[tuple[bool, re.Pattern]]:
    """Règles Allow/Disallow du groupe 'User-agent: *' de base/robots.txt."""
    try:
        text = session.get(f"{base}/robots.txt", timeout=15).text
    except requests.RequestException:
        return []

    rules, in_star_group = [], False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (p.strip() for p in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            in_star_group = value == "*"
        elif in_star_group and key in ("allow", "disallow") and value:
            pattern = re.escape(value).replace(r"\*", ".*")
            if pattern.endswith(r"\$"):
                pattern = pattern[:-2] + "$"
            rules.append((key == "allow", re.compile(pattern)))
    return rules


def robots_allowed(session: requests.Session, url: str) -> bool:
    """True si l'URL est autorisée pour 'User-agent: *' (règle la plus longue gagne)."""
    m = re.match(r"(https?://[^/]+)(.*)", url)
    base, path = m.group(1), m.group(2) or "/"
    if base not in _ROBOTS_CACHE:
        _ROBOTS_CACHE[base] = _load_robots_rules(session, base)

    best_len, allowed = -1, True
    for is_allow, pattern in _ROBOTS_CACHE[base]:
        if pattern.match(path) and len(pattern.pattern) > best_len:
            best_len, allowed = len(pattern.pattern), is_allow
    return allowed


# ----------------------------------------------------------------------
# Sauvegarde incrémentale + reprise après interruption
# ----------------------------------------------------------------------

def load_seen_ids(path: str) -> set[str]:
    """IDs déjà présents dans le CSV (pour reprendre une collecte interrompue)."""
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return {row["id"] for row in csv.DictReader(f)}
    except FileNotFoundError:
        return set()


def append_annonce(a: Annonce, path: str):
    """Ajoute UNE annonce au CSV immédiatement (rien n'est perdu en cas de crash)."""
    save_annonces_csv([a], path, mode="a")


def save_annonces_csv(annonces: list[Annonce], path: str, mode: str = "a"):
    """Ajoute (mode='a') ou écrase (mode='w') les annonces dans un CSV."""
    write_header = mode == "w"
    if not write_header:
        try:
            with open(path, "r", encoding="utf-8") as f:
                write_header = not f.read(1)
        except FileNotFoundError:
            write_header = True

    with open(path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        for a in annonces:
            row = asdict(a)
            row["titre"] = mask_contacts(row["titre"])
            row["description_brute"] = mask_contacts(row["description_brute"])
            writer.writerow(row)


# Données personnelles écrites par les vendeurs dans le texte libre.
# Numéros tunisiens à 8 chiffres (avec ou sans +216 / espaces), sauf s'ils
# sont suivis d'une devise (c'est alors un prix).
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(
    r"(?<!\d)(?:(?:\+|00)\s?216[\s.-]?)?[2-9](?:[\s.-]?\d){7}(?!\d)"
    r"(?!\s*(?:DT|TND|dinars?|mill)\b)",
    re.I,
)


def mask_contacts(text):
    if not isinstance(text, str):
        return text
    return PHONE_RE.sub("[tel]", EMAIL_RE.sub("[email]", text))


# ----------------------------------------------------------------------
# Extracteurs regex (appliqués sur le texte brut de la page/annonce)
# ----------------------------------------------------------------------

def extract_prix(text: str) -> Optional[float]:
    """
    Capture des formats du type: '255000DT', '255 000 DT', '255.000 DT',
    '255 000 TND', '1 350 000 TND'. Ignore 'Sur demande' / 'Prix à consulter'.
    """
    if re.search(r"sur\s+demande|prix\s+à\s+consulter|non\s+communiqu", text, re.I):
        return None
    m = re.search(r"([\d]{1,3}(?:[.\s]\d{3})+|\d{4,7})\s*(?:DT|TND|Dinars?)", text, re.I)
    if not m:
        return None
    raw = m.group(1).replace(" ", "").replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def extract_surface(text: str) -> Optional[float]:
    """Capture 'Superficie : 112m²', '112 m2', '800 m²' etc."""
    m = re.search(r"(\d{2,4}(?:[.,]\d+)?)\s*m[²2]", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def extract_pieces(text: str) -> Optional[int]:
    """Capture le format tunisien 'S+3', 'S+1', 'S3'."""
    m = re.search(r"\bS\s*\+?\s*(\d)\b", text, re.I)
    if m:
        return int(m.group(1))
    return None


def extract_chambres(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*chambres?", text, re.I)
    if m:
        return int(m.group(1))
    return None


def extract_salles_bain(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*salles?\s+de\s+bains?", text, re.I)
    if m:
        return int(m.group(1))
    return None


def extract_etage(text: str) -> Optional[str]:
    m = re.search(r"(rez[- ]de[- ]chauss[ée]e|RDC|\d+(?:er|ème|éme|e)\s+étage)", text, re.I)
    return m.group(1) if m else None


def extract_gouvernorat(text: str) -> Optional[str]:
    """
    Cherche le nom d'un gouvernorat dans le texte. Attention aux faux positifs :
    des quartiers du Grand Tunis contiennent le nom d'un gouvernorat sans en
    faire partie (ex: 'Ain Zaghouan' à Tunis n'est PAS le gouvernorat de
    Zaghouan). On exclut donc les correspondances précédées d'un mot qui
    forme un nom de quartier composé connu.
    FAUX_AMIS: motif -> gouvernorat qu'il ne faut PAS matcher à cause de lui
    """
    FAUX_AMIS = {
        "Zaghouan": [r"Ain\s+Zaghouan"],
    }
    for g in GOUVERNORATS:
        pattern = rf"\b{re.escape(g)}\b"
        for match in re.finditer(pattern, text, re.I):
            excluded = False
            for faux_pattern in FAUX_AMIS.get(g, []):
                # si le match fait partie d'un des faux-amis, on l'ignore
                if re.search(faux_pattern, text[max(0, match.start() - 10):match.end() + 10], re.I):
                    excluded = True
                    break
            if not excluded:
                return g
    return None


def extract_bool_keyword(text: str, *keywords: str) -> bool:
    return any(re.search(rf"\b{re.escape(k)}\b", text, re.I) for k in keywords)


def detect_type_transaction(text: str) -> str:
    if re.search(r"\bà\s+louer\b|\blocation\b|\bloyer\b|/mois\b", text, re.I):
        return "location"
    if re.search(r"\bà\s+vendre\b|\bvente\b|\bprix\s+de\s+vente\b", text, re.I):
        return "vente"
    return "inconnu"


def enrich_common_fields(a: Annonce, full_text: str):
    """Remplit les champs communs à partir du texte complet de l'annonce."""
    a.prix_dt = extract_prix(full_text)
    a.surface_m2 = extract_surface(full_text)
    a.nb_pieces = extract_pieces(full_text)
    a.nb_chambres = extract_chambres(full_text) or a.nb_pieces
    a.nb_salles_bain = extract_salles_bain(full_text)
    a.etage = extract_etage(full_text)
    a.gouvernorat = extract_gouvernorat(full_text)
    a.ascenseur = extract_bool_keyword(full_text, "ascenseur")
    a.parking = extract_bool_keyword(full_text, "parking", "garage")
    a.piscine = extract_bool_keyword(full_text, "piscine")
    a.climatisation = extract_bool_keyword(full_text, "climatisation", "climatiseur", "clim")
    a.chauffage_central = extract_bool_keyword(full_text, "chauffage central")
    a.meuble = extract_bool_keyword(full_text, "meublé", "meuble")
    if a.type_transaction == "inconnu":
        a.type_transaction = detect_type_transaction(full_text)
