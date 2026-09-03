"""
scraper_tecnocasa.py
Scrape les annonces de tecnocasa.tn.

IMPORTANT — différence avec Tayara/Mubawab :
La grille d'annonces est chargée dynamiquement en JavaScript (SPA Vue.js)
après le chargement de la page -> `requests` + BeautifulSoup ne suffisent
PAS ici. Playwright est nécessaire pour exécuter le JS et récupérer le DOM
final.

Sélecteur confirmé via DevTools (clic droit sur une carte -> Inspecter) le
03/09/2026 :
    CARD_LINK_SELECTOR = "div.estates-list > div > a"
Chaque carte est un unique <a href="https://www.tecnocasa.tn/...html">
contenant directement :
    .estate-card-current-price span   -> "259 000 DT"
    .estate-card-title                -> "S+2 en vente"
    .estate-card-subtitle             -> "Ariana - Riadh Landalous"
    .estate-card-rooms span           -> "3 pièces"
    .estate-card-surface span         -> "89 m²"
=> On récupère prix / titre / gouvernorat-quartier / pièces / surface
   DIRECTEMENT sur la page de listing (fiable, structuré), et on ne va sur
   la page de détail QUE pour tenter de compléter les champs absents de la
   carte (étage, salle de bain, équipements) via les regex de common.py.

URLs de listing connues (patron NON uniforme, confirmé par observation) :
  https://www.tecnocasa.tn/vendre/appartement/nord-est-ne/grand-tunis/ariana.html
  https://www.tecnocasa.tn/vendre/appartement/nord-est-ne/bizerte.html
  https://www.tecnocasa.tn/vendre/appartement/nord-est-ne/cap-bon.html
Remarque : certains gouvernorats sont imbriqués sous "grand-tunis/", d'autres
sont directement sous le region-slug ("nord-est-ne", "centre-est-ce", ...).
Il n'existe PAS un simple gabarit {region}/{ville} valide partout -> on liste
des chemins complets ci-dessous plutôt que de les reconstruire.

TODO (Yahya) : cette liste ne couvre pas encore les 24 gouvernorats x
{vendre, louer} x {appartement, maison}. Pour la compléter, navigue le site
(filtre région/ville) et ajoute chaque URL complète trouvée dans
LISTING_URLS. Le plus rapide : ouvre chaque page région (ex. .../nord-est-ne
.html) et relève les liens vers les pages gouvernorat/ville qu'elle contient.

TODO (Yahya) : la pagination n'est PAS confirmée. Le site semble être une SPA
Vue -> probable "scroll infini" ou bouton "Voir plus". Le code ci-dessous
scrolle et clique un éventuel bouton "load more" tant que de nouvelles cartes
apparaissent, mais le sélecteur du bouton (LOAD_MORE_SELECTOR) est un
best-effort à confirmer/adapter via DevTools sur une page de listing.
"""

import re
from bs4 import BeautifulSoup

from common import Annonce, save_annonces_csv, enrich_common_fields, polite_sleep

# Confirmé via DevTools le 03/09/2026 (voir docstring ci-dessus).
CARD_SELECTOR = "div.estates-list > div > a"

# TODO: à confirmer/adapter via DevTools. Best-effort pour déclencher le
# chargement de cartes supplémentaires (bouton "Voir plus" / "Charger plus").
LOAD_MORE_SELECTOR = "button:has-text('Voir plus'), button:has-text('Charger plus')"

# Chemins complets connus (transaction, type_bien, url). À compléter (voir TODO).
LISTING_URLS = [
    ("vente", "appartement", "https://www.tecnocasa.tn/vendre/appartement/nord-est-ne/grand-tunis/ariana.html"),
    ("vente", "appartement", "https://www.tecnocasa.tn/vendre/appartement/nord-est-ne/grand-tunis/ennasr.html"),
    ("vente", "appartement", "https://www.tecnocasa.tn/vendre/appartement/nord-est-ne/grand-tunis/el-menzah.html"),
    ("vente", "appartement", "https://www.tecnocasa.tn/vendre/appartement/nord-est-ne/grand-tunis/le-bardo.html"),
    ("vente", "appartement", "https://www.tecnocasa.tn/vendre/appartement/nord-est-ne/bizerte.html"),
    ("vente", "appartement", "https://www.tecnocasa.tn/vendre/appartement/nord-est-ne/cap-bon.html"),
    ("vente", "appartement", "https://www.tecnocasa.tn/vendre/appartement/centre-est-ce/sousse.html"),
]


def _text(el, selector):
    node = el.select_one(selector)
    return node.get_text(strip=True) if node else ""


def _parse_card(a_tag) -> dict:
    """Extrait les champs directement visibles sur la carte de listing."""
    href = a_tag.get("href", "")
    prix_txt = _text(a_tag, ".estate-card-current-price span")
    titre = _text(a_tag, ".estate-card-title")
    subtitle = _text(a_tag, ".estate-card-subtitle")  # "Ariana - Riadh Landalous"
    pieces_txt = _text(a_tag, ".estate-card-rooms span")
    surface_txt = _text(a_tag, ".estate-card-surface span")

    gouvernorat, quartier = None, None
    if " - " in subtitle:
        gouvernorat, quartier = [p.strip() for p in subtitle.split(" - ", 1)]
    elif subtitle:
        gouvernorat = subtitle.strip()

    return {
        "href": href,
        "prix_txt": prix_txt,
        "titre": titre,
        "gouvernorat": gouvernorat,
        "quartier": quartier,
        "pieces_txt": pieces_txt,
        "surface_txt": surface_txt,
    }


def scrape_with_playwright(out_csv: str = "annonces_tecnocasa.csv"):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Playwright n'est pas installé. Lance:\n"
            "  pip install playwright --break-system-packages\n"
            "  playwright install chromium"
        )

    # href -> (transaction, type_bien, card_data)
    cards_by_href = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))

        for transaction, type_bien, url in LISTING_URLS:
            print(f"[Tecnocasa] Chargement listing: {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception as e:
                print(f"  erreur chargement -> {e}")
                continue

            page.wait_for_timeout(2000)

            # Best-effort: scroll + clic "voir plus" tant que le nombre de
            # cartes augmente (SPA -> pagination probable par scroll infini).
            # TODO: confirmer ce comportement, adapter si c'est en réalité
            # une pagination classique par numéro de page (?page=2 etc.)
            previous_count = -1
            stable_rounds = 0
            for _ in range(30):  # garde-fou anti-boucle infinie
                current_count = page.locator(CARD_SELECTOR).count()
                if current_count == previous_count:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        break
                else:
                    stable_rounds = 0
                previous_count = current_count

                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(800)
                try:
                    btn = page.locator(LOAD_MORE_SELECTOR).first
                    if btn.is_visible(timeout=500):
                        btn.click(timeout=500)
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            found = soup.select(CARD_SELECTOR)
            print(f"  {len(found)} cartes trouvées")

            for a_tag in found:
                card = _parse_card(a_tag)
                href = card["href"]
                if not href.startswith("https://www.tecnocasa.tn"):
                    continue
                cards_by_href[href] = (transaction, type_bien, card)

            polite_sleep()

        print(f"[Tecnocasa] Total {len(cards_by_href)} annonces détectées, scraping des détails...")
        all_annonces = []
        for href, (transaction, type_bien, card) in cards_by_href.items():
            full_text = ""
            try:
                page.goto(href, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(1000)
                html = page.content()
                detail_soup = BeautifulSoup(html, "html.parser")
                full_text = detail_soup.get_text(separator=" ", strip=True)
            except Exception as e:
                print(f"  erreur détail {href} -> {e}")

            # Texte enrichi: on préfixe avec les champs fiables de la carte
            # pour que les regex de common.py les retrouvent même si la
            # page de détail a une mise en page différente ou n'a pas pu
            # être chargée.
            card_summary = (
                f"{card['titre']} {card['prix_txt']} {card['gouvernorat'] or ''} "
                f"{card['quartier'] or ''} {card['pieces_txt']} {card['surface_txt']}"
            )
            combined_text = card_summary + " " + full_text

            ad_id = re.sub(r"\W+", "_", href.rstrip("/").split("/")[-1])[:60]
            a = Annonce(
                id=f"tecnocasa_{ad_id}",
                source="tecnocasa",
                url=href,
                type_transaction=transaction,
                type_bien=type_bien,
                titre=card["titre"],
                description_brute=full_text[:3000],
            )
            enrich_common_fields(a, combined_text)
            # La carte donne le gouvernorat de façon plus fiable que la regex
            # sur texte libre -> on la privilégie si elle a trouvé quelque chose.
            if card["gouvernorat"]:
                a.gouvernorat = card["gouvernorat"]
            if card["quartier"]:
                a.ville = card["quartier"]
            all_annonces.append(a)
            polite_sleep()

        browser.close()

    save_annonces_csv(all_annonces, out_csv, mode="w")
    print(f"[Tecnocasa] {len(all_annonces)} annonces sauvegardées dans {out_csv}")
    return all_annonces


if __name__ == "__main__":
    scrape_with_playwright()