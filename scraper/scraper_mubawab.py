"""
scraper_mubawab.py
Scrape les annonces immobilières de mubawab.tn.

Structure observée (vérifiée en août 2026) :
- Listing par gouvernorat + type de bien :
    https://www.mubawab.tn/fr/st/{gouvernorat-slug}/appartements-a-vendre
    https://www.mubawab.tn/fr/st/{gouvernorat-slug}/maisons-a-vendre
    (remplacer 'a-vendre' par 'a-louer' pour la location)
- Listing national par type :
    https://www.mubawab.tn/fr/sc/appartements-a-vendre
- Pages d'annonce : https://www.mubawab.tn/fr/a/{id}/{slug}

ROBOTS.TXT (vérifié en octobre 2026) : "Disallow: /*:" pour tous les robots.
La pagination du site (".../appartements-a-vendre:p:2") est donc INTERDITE :
on ne collecte que la page 1 de chaque listing (gouvernorat x type), et
chaque URL est vérifiée avec common.robots_allowed avant la requête.
Les anciennes données Mubawab (raw_v1/) avaient été collectées via ces pages
paginées ; la nouvelle collecte respecte robots.txt.

Avantage Mubawab : les caractéristiques (surface, pièces, chambres,
salle de bain, équipements) sont déjà présentées sous forme de mini-tags
structurés sur la page -> extraction plus fiable qu'un texte 100% libre.
"""

import re
from bs4 import BeautifulSoup

from common import (
    Annonce, get_session, polite_sleep, enrich_common_fields,
    append_annonce, load_seen_ids, robots_allowed,
)

BASE = "https://www.mubawab.tn"

# gouvernorat_slug -> nom affiché (à étendre selon tes besoins ; les slugs
# suivent le pattern "nom-en-minuscules-avec-tirets")
GOUVERNORAT_SLUGS = {
    "tunis": "Tunis", "ariana": "Ariana", "ben-arous": "Ben Arous",
    "la-manouba": "Manouba", "nabeul": "Nabeul", "zaghouan": "Zaghouan",
    "bizerte": "Bizerte", "beja": "Béja", "jendouba": "Jendouba",
    "le-kef": "Le Kef", "siliana": "Siliana", "sousse-ville": "Sousse",
    "monastir": "Monastir", "mahdia": "Mahdia", "sfax-ville": "Sfax",
    "kairouan": "Kairouan", "kasserine": "Kasserine",
    "sidi-bouzid": "Sidi Bouzid", "gabes": "Gabès", "medenine": "Médenine",
    "tataouine": "Tataouine", "gafsa": "Gafsa", "tozeur": "Tozeur",
    "kebili": "Kébili",
}

TYPES_BIEN = {
    "appartement": "appartements",
    "maison_villa": "maisons",
}

ITEM_LINK_RE = re.compile(r"^/fr/a/\d+/[^/:]+$")

# En-tête de la page : "... 2 Salles de bains El Aouina à Tunis 455 000 TND"
# -> ville + prix. On n'utilise PAS le premier prix de la page, précédé du
# nombre de photos ("El Aouina 10 455 000 TND" -> 10 455 000).
_GOUV_NAMES = "|".join(sorted({re.escape(g) for g in GOUVERNORAT_SLUGS.values()} | {"Kef"}, key=len, reverse=True))
HEADER_RE = re.compile(
    r"(?:m²|Pièces?|Ch\.|Chambres?|Salles? de bains?)\s+"
    r"([^\d\n][^\n]{1,40}?)\s+à[\s\xa0]+(?:" + _GOUV_NAMES + r")\s+"
    r"(\d{1,3}(?:[\s\u202f\xa0.]\d{3})*)\s*TND"
)


def listing_urls(gouvernorats_slugs: list[str]) -> list[tuple[str, str, str]]:
    """(type_bien, gouvernorat, url) : page 1 uniquement (pagination interdite)."""
    out = []
    for gouv_slug in gouvernorats_slugs:
        gouv_name = GOUVERNORAT_SLUGS.get(gouv_slug, gouv_slug)
        for type_bien, type_slug in TYPES_BIEN.items():
            out.append((type_bien, gouv_name, f"{BASE}/fr/st/{gouv_slug}/{type_slug}-a-vendre"))
    return out


def get_listing_page_links(session, url: str) -> list[str]:
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(BASE):
            href = href[len(BASE):]
        href = href.split("?")[0]
        if ITEM_LINK_RE.match(href):
            links.add(BASE + href)
    return sorted(links)


def scrape_detail(session, url: str, type_bien: str, gouvernorat_hint: str) -> Annonce:
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.find("h1")
    titre = title_tag.get_text(strip=True) if title_tag else ""

    full_text = soup.get_text(separator=" ", strip=True)

    m = re.search(r"/fr/a/(\d+)/", url)
    ad_id = m.group(1) if m else url.rstrip("/").split("/")[-1]

    a = Annonce(
        id=f"mubawab_{ad_id}",
        source="mubawab",
        url=url,
        type_transaction="vente",
        type_bien=type_bien,
        titre=titre,
        gouvernorat=gouvernorat_hint,
        description_brute=full_text[:3000],
    )
    enrich_common_fields(a, full_text)
    # Le gouvernorat de l'URL de listing est plus fiable que la regex
    a.gouvernorat = gouvernorat_hint

    header = HEADER_RE.search(full_text)
    if header:
        a.ville = header.group(1).strip()
        a.prix_dt = float(re.sub(r"[\s\u202f\xa0.]", "", header.group(2)))
    else:
        a.prix_dt = None  # "Prix à consulter" : pas de prix affiché
    a.type_transaction = "vente"

    return a


def run(gouvernorats_slugs: list[str] = None, out_csv: str = "annonces_mubawab.csv"):
    """
    Vente uniquement, page 1 de chaque (gouvernorat x type) : ~19 annonces par page.
    Reprise automatique : les annonces déjà présentes dans out_csv sont ignorées.
    """
    session = get_session()
    seen = load_seen_ids(out_csv)
    slugs = gouvernorats_slugs or list(GOUVERNORAT_SLUGS.keys())
    n_saved = 0
    print(f"[Mubawab] {len(seen)} annonces déjà collectées (reprise)")

    for type_bien, gouv_name, url in listing_urls(slugs):
        if not robots_allowed(session, url):
            print(f"  interdit par robots.txt, ignoré: {url}")
            continue
        try:
            links = get_listing_page_links(session, url)
        except Exception as e:
            print(f"  erreur listing {url} -> {e}")
            continue
        print(f"[Mubawab] {gouv_name} / {type_bien}: {len(links)} annonces")
        polite_sleep()

        for link in links:
            ad_id = "mubawab_" + re.search(r"/fr/a/(\d+)/", link).group(1)
            if ad_id in seen or not robots_allowed(session, link):
                continue
            seen.add(ad_id)
            try:
                append_annonce(scrape_detail(session, link, type_bien, gouv_name), out_csv)
                n_saved += 1
            except Exception as e:
                print(f"    erreur détail {link} -> {e}")
            polite_sleep()

    print(f"[Mubawab] {n_saved} annonces ajoutées dans {out_csv}")


if __name__ == "__main__":
    run(gouvernorats_slugs=["tunis"])
