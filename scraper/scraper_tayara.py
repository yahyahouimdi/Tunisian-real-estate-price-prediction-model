"""
scraper_tayara.py
Scrape les annonces immobilières de tayara.tn.

Structure observée (vérifiée en août 2026) :
- Pages de catégorie : https://www.tayara.tn/listing/c/immobilier/appartements/
  (autres catégories : maisons-et-villas, terrains-et-fermes, ...)
  Pagination : ?page=2, ?page=3, ...
- Pages d'annonce : https://www.tayara.tn/item/{categorie}/{gouvernorat}/{ville}/{slug}/{id}/

NB: Tayara est en Next.js (SSR), donc requests + BeautifulSoup suffit pour
récupérer le HTML (pas besoin de Selenium a priori). Si tu constates que le
contenu est vide avec requests, bascule sur Selenium/Playwright (voir
scraper_tecnocasa.py pour un squelette Selenium en commentaire).
"""

import re
from bs4 import BeautifulSoup

from common import (
    Annonce, get_session, polite_sleep, save_annonces_csv, enrich_common_fields,
)

BASE = "https://www.tayara.tn"

# Ajoute/retire des catégories selon ce que tu veux couvrir
CATEGORIES = {
    "appartement": "/listing/c/immobilier/appartements/",
    "maison_villa": "/listing/c/immobilier/maisons-et-villas/",
}

ITEM_LINK_RE = re.compile(r"^/item/[^/]+/[^/]+/[^/]+/[^/]+/[a-f0-9]+/$")


def get_listing_page_links(session, category_path: str, page: int) -> list[str]:
    url = f"{BASE}{category_path}"
    if page > 1:
        url += f"?page={page}"
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


def scrape_detail(session, url: str, type_bien: str) -> Annonce:
    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.find("h1")
    titre = title_tag.get_text(strip=True) if title_tag else ""

    full_text = soup.get_text(separator=" ", strip=True)

    ad_id = url.rstrip("/").split("/")[-1]

    a = Annonce(
        id=f"tayara_{ad_id}",
        source="tayara",
        url=url,
        type_transaction="inconnu",
        type_bien=type_bien,
        titre=titre,
        description_brute=full_text[:3000],  # tronqué pour rester raisonnable
    )
    enrich_common_fields(a, full_text)

    # La ville/quartier apparaissent souvent dans l'URL: /item/cat/gouv/ville/slug/id/
    parts = url.replace(BASE, "").strip("/").split("/")
    if len(parts) >= 4:
        if not a.gouvernorat:
            a.gouvernorat = parts[2].replace("-", " ").title()
        a.ville = parts[3].replace("-", " ").title()

    return a


def run(max_pages_per_category: int = 5, out_csv: str = "annonces_tayara.csv"):
    session = get_session()
    all_annonces = []

    for type_bien, cat_path in CATEGORIES.items():
        print(f"[Tayara] Catégorie: {type_bien}")
        seen_links = set()
        for page in range(1, max_pages_per_category + 1):
            try:
                links = get_listing_page_links(session, cat_path, page)
            except Exception as e:
                print(f"  page {page}: erreur listing -> {e}")
                break
            if not links:
                print(f"  page {page}: aucune annonce trouvée, arrêt pagination")
                break
            new_links = [l for l in links if l not in seen_links]
            seen_links.update(new_links)
            print(f"  page {page}: {len(new_links)} nouvelles annonces")
            polite_sleep()

            for link in new_links:
                try:
                    annonce = scrape_detail(session, link, type_bien)
                    all_annonces.append(annonce)
                except Exception as e:
                    print(f"    erreur détail {link} -> {e}")
                polite_sleep()

    save_annonces_csv(all_annonces, out_csv, mode="w")
    print(f"[Tayara] {len(all_annonces)} annonces sauvegardées dans {out_csv}")
    return all_annonces


if __name__ == "__main__":
    run()
