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

Avantage Mubawab : les caractéristiques (surface, pièces, chambres,
salle de bain, équipements) sont déjà présentées sous forme de mini-tags
structurés sur la page -> extraction plus fiable qu'un texte 100% libre.
"""

import re
from bs4 import BeautifulSoup

from common import (
    Annonce, get_session, polite_sleep, save_annonces_csv, enrich_common_fields,
    GOUVERNORATS,
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

ITEM_LINK_RE = re.compile(r"^/fr/a/\d+/[^/]+$")


def get_listing_page_links(session, gouv_slug: str, type_slug: str, transaction: str, page: int) -> list[str]:
    suffix = "a-vendre" if transaction == "vente" else "a-louer"
    url = f"{BASE}/fr/st/{gouv_slug}/{type_slug}-{suffix}"
    if page > 1:
        url += f":p:{page}"
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(BASE):
            href = href[len(BASE):]
        if ITEM_LINK_RE.match(href):
            links.add(BASE + href)
    return list(links)


def scrape_detail(session, url: str, type_bien: str, gouvernorat_hint: str, transaction: str) -> Annonce:
    resp = session.get(url, timeout=15)
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
        type_transaction=transaction,
        type_bien=type_bien,
        titre=titre,
        gouvernorat=gouvernorat_hint,
        description_brute=full_text[:3000],
    )
    enrich_common_fields(a, full_text)
    if not a.gouvernorat:
        a.gouvernorat = gouvernorat_hint

    return a


def run(gouvernorats_slugs: list[str] = None, max_pages_per_combo: int = 5,
        out_csv: str = "annonces_mubawab.csv"):
    """
    gouvernorats_slugs: liste de slugs à couvrir (ex: ["tunis", "ariana", "sousse-ville"]).
    Par défaut couvre tous les gouvernorats connus (attention: ça fait BEAUCOUP
    de requêtes, commence avec un sous-ensemble pour tester).
    """
    session = get_session()
    all_annonces = []
    slugs = gouvernorats_slugs or list(GOUVERNORAT_SLUGS.keys())

    for gouv_slug in slugs:
        gouv_name = GOUVERNORAT_SLUGS.get(gouv_slug, gouv_slug)
        for type_bien, type_slug in TYPES_BIEN.items():
            for transaction in ("vente", "location"):
                print(f"[Mubawab] {gouv_name} / {type_bien} / {transaction}")
                seen_links = set()
                for page in range(1, max_pages_per_combo + 1):
                    try:
                        links = get_listing_page_links(session, gouv_slug, type_slug, transaction, page)
                    except Exception as e:
                        print(f"  page {page}: erreur listing -> {e}")
                        break
                    if not links:
                        break
                    new_links = [l for l in links if l not in seen_links]
                    seen_links.update(new_links)
                    print(f"  page {page}: {len(new_links)} nouvelles annonces")
                    polite_sleep()

                    for link in new_links:
                        try:
                            annonce = scrape_detail(session, link, type_bien, gouv_name, transaction)
                            all_annonces.append(annonce)
                        except Exception as e:
                            print(f"    erreur détail {link} -> {e}")
                        polite_sleep()

    save_annonces_csv(all_annonces, out_csv, mode="w")
    print(f"[Mubawab] {len(all_annonces)} annonces sauvegardées dans {out_csv}")
    return all_annonces


if __name__ == "__main__":
    # Exemple de démarrage restreint pour tester rapidement
    run(gouvernorats_slugs=["tunis", "ariana", "sousse-ville"], max_pages_per_combo=3)
