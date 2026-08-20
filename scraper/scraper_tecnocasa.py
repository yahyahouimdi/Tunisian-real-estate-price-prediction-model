"""
scraper_tecnocasa.py
Scrape les annonces de tecnocasa.tn.

IMPORTANT — différence avec Tayara/Mubawab :
En inspectant https://www.tecnocasa.tn/vendre/appartement/centre-est-ce/sousse.html
avec une requête HTTP simple, le HTML retourné ne contient QUE le header/footer :
la grille d'annonces est chargée dynamiquement en JavaScript après le chargement
de la page (probablement via un appel AJAX/XHR vers une API interne).
=> `requests` + BeautifulSoup ne suffiront PAS ici. Il faut soit :
   (a) Playwright/Selenium pour exécuter le JS et récupérer le DOM final, soit
   (b) trouver l'appel API sous-jacent (ouvrir l'onglet Réseau des DevTools sur
       une page de listing, filtrer par "Fetch/XHR", et regarder quelle requête
       renvoie le JSON des annonces — souvent bien plus rapide et robuste que (a)).

Ce script utilise Playwright (option a) car je ne peux pas confirmer l'URL de
l'API interne sans exécuter de JS, ce que mon environnement actuel ne permet
pas de vérifier. AVANT de lancer ce script :
  1. pip install playwright --break-system-packages && playwright install chromium
  2. Ouvre une page de listing dans ton navigateur, clic droit sur une annonce
     -> Inspecter, et vérifie/adapte le sélecteur CSS `CARD_LINK_SELECTOR`
     ci-dessous si besoin (il est à confirmer, indiqué par un commentaire TODO).

URLs de listing connues (par région/ville) :
  https://www.tecnocasa.tn/vendre/appartement/{region-slug}/{ville-slug}.html
  https://www.tecnocasa.tn/louer/appartement/{region-slug}/{ville-slug}.html
Exemples de region-slug observés : "centre-est-ce", "nord-est-ne"
"""

import re
from bs4 import BeautifulSoup

from common import Annonce, save_annonces_csv, enrich_common_fields, polite_sleep

# TODO: confirme ce sélecteur via l'inspecteur du navigateur (clic droit sur une
# carte d'annonce -> Inspecter). Il cible les liens vers les pages de détail.
CARD_LINK_SELECTOR = "a[href*='/dettaglio'], a[href*='/detail'], a[href*='.html'][href*='vendre']"

# Liste de pages de listing à couvrir. Ajoute autant de (region_slug, ville_slug)
# que nécessaire pour couvrir la Tunisie -- je n'ai pas pu confirmer la liste
# exhaustive des slugs de région, à compléter en naviguant le site.
LISTINGS_A_COUVRIR = [
    ("vendre", "centre-est-ce", "sousse"),
    ("vendre", "nord-est-ne", "grand-tunis"),
    ("vendre", "nord-est-ne", "nabeul"),
    ("vendre", "nord-est-ne", "cap-bon/nabeul"),
]


def scrape_with_playwright(out_csv: str = "annonces_tecnocasa.csv"):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Playwright n'est pas installé. Lance:\n"
            "  pip install playwright --break-system-packages\n"
            "  playwright install chromium"
        )

    all_annonces = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))

        detail_links = set()
        for transaction, region, ville in LISTINGS_A_COUVRIR:
            url = f"https://www.tecnocasa.tn/{transaction}/appartement/{region}/{ville}.html"
            print(f"[Tecnocasa] Chargement listing: {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception as e:
                print(f"  erreur chargement -> {e}")
                continue

            # Laisse une marge pour les appels JS tardifs
            page.wait_for_timeout(2000)
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            found = soup.select(CARD_LINK_SELECTOR)
            print(f"  {len(found)} liens trouvés avec le sélecteur actuel")
            for a in found:
                href = a.get("href", "")
                if href.startswith("/"):
                    href = "https://www.tecnocasa.tn" + href
                if href.startswith("https://www.tecnocasa.tn"):
                    detail_links.add(href)
            polite_sleep()

        print(f"[Tecnocasa] Total {len(detail_links)} annonces détectées, scraping des détails...")
        for link in detail_links:
            try:
                page.goto(link, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(1000)
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")
                title_tag = soup.find("h1")
                titre = title_tag.get_text(strip=True) if title_tag else ""
                full_text = soup.get_text(separator=" ", strip=True)

                ad_id = re.sub(r"\W+", "_", link.rstrip("/").split("/")[-1])[:60]
                a = Annonce(
                    id=f"tecnocasa_{ad_id}",
                    source="tecnocasa",
                    url=link,
                    type_transaction="inconnu",
                    type_bien="appartement",  # à affiner si tu scrapes aussi maisons/villas
                    titre=titre,
                    description_brute=full_text[:3000],
                )
                enrich_common_fields(a, full_text)
                all_annonces.append(a)
            except Exception as e:
                print(f"  erreur détail {link} -> {e}")
            polite_sleep()

        browser.close()

    save_annonces_csv(all_annonces, out_csv, mode="w")
    print(f"[Tecnocasa] {len(all_annonces)} annonces sauvegardées dans {out_csv}")
    return all_annonces


if __name__ == "__main__":
    scrape_with_playwright()
