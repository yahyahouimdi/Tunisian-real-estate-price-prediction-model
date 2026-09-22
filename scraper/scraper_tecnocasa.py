"""
scraper_tecnocasa.py
Scrape les annonces de vente (appartements + villas) de tecnocasa.tn.

Structure observée (vérifiée en octobre 2026) :
- robots.txt : tout autorisé (sauf /flush_all) et publie des sitemaps.
- Sitemap des biens résidentiels :
    https://www.tecnocasa.tn/sitemap/residentiel.xml.gz
  ~2 300 URLs, dont ~780 appartements et ~530 villas à vendre :
    https://www.tecnocasa.tn/vendre/appartement/{province}/{ville}/{id}.html
    https://www.tecnocasa.tn/vendre/villa/{province}/{ville}/{id}.html
- Chaque page d'annonce embarque l'annonce complète en JSON dans l'attribut
  Vue  :estate="{...}"  (HTML-échappé) : prix et surface numériques, pièces,
  salles de bain, étage, équipements, année de construction, etc.

=> Plus besoin de Playwright ni de scroller la grille JS : on lit le sitemap,
puis le JSON de chaque page avec requests.

On ne lit pas les champs "agency" / "agent" (coordonnées de l'agence).
"""

import gzip
import html
import json
import re

from bs4 import BeautifulSoup

from common import (
    Annonce, get_session, polite_sleep, enrich_common_fields,
    append_annonce, load_seen_ids, robots_allowed,
)

BASE = "https://www.tecnocasa.tn"
SITEMAP_URL = f"{BASE}/sitemap/residentiel.xml.gz"

# segment d'URL -> type_bien du projet
TYPES_BIEN = {
    "appartement": "appartement",
    "villa": "maison_villa",
}

ESTATE_RE = re.compile(r':estate="(.*?)"', re.S)
SALE_URL_RE = re.compile(r"^https://www\.tecnocasa\.tn/vendre/([a-z-]+)/.+/(\d+)\.html$")


def sale_urls_from_sitemap(session) -> list[tuple[str, str]]:
    """[(type_bien, url)] des appartements/villas à vendre du sitemap."""
    resp = session.get(SITEMAP_URL, timeout=30)
    resp.raise_for_status()
    content = resp.content
    try:
        content = gzip.decompress(content)
    except OSError:
        pass  # déjà décompressé par le serveur / requests

    out = []
    for url in re.findall(r"<loc>(.*?)</loc>", content.decode("utf-8", "ignore")):
        m = SALE_URL_RE.match(url.strip())
        if m and m.group(1) in TYPES_BIEN:
            out.append((TYPES_BIEN[m.group(1)], url.strip()))
    return out


def get_estate(session, url: str) -> dict:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    m = ESTATE_RE.search(resp.text)
    if not m:
        raise ValueError("JSON :estate introuvable (annonce retirée ou site modifié ?)")
    return json.loads(html.unescape(m.group(1)))


def _yes_no(value):
    """'Oui'/'Non'/True/False -> bool ; vide ou inconnu -> None."""
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"oui", "yes", "1", "true"}:
        return True
    if text in {"non", "no", "0", "false"}:
        return False
    return None


def _number(value):
    m = re.search(r"\d+(?:[.,]\d+)?", str(value or "").replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def build_annonce(estate: dict, url: str, type_bien: str) -> Annonce:
    features = estate.get("features") or {}
    titre = estate.get("title") or ""
    description = BeautifulSoup(estate.get("description") or "", "html.parser").get_text(" ", strip=True)
    data = {d.get("label"): d.get("valore") for d in estate.get("data") or []}

    a = Annonce(
        id=f"tecnocasa_{estate.get('id')}",
        source="tecnocasa",
        url=url,
        type_transaction="vente",
        type_bien=type_bien,
        titre=titre,
        description_brute=description[:3000],
        date_publication=estate.get("last_published_at"),
    )
    enrich_common_fields(a, f"{titre}\n{description}")
    a.type_transaction = "vente"

    a.prix_dt = _number(estate.get("numeric_price"))
    a.surface_m2 = _number(estate.get("numeric_surface"))
    a.gouvernorat = (estate.get("province") or {}).get("title") or a.gouvernorat
    a.ville = (estate.get("city") or {}).get("title") or None

    # Tecnocasa compte les pièces au total (salon inclus) : "4 pièces" = S+3.
    # nb_pieces suit la convention du projet (N de "S+N").
    pieces = _number(data.get("Pièces") or estate.get("rooms"))
    bedrooms = _number(features.get("bedrooms"))
    if a.nb_pieces is None and pieces:
        a.nb_pieces = int(pieces) - 1
    if bedrooms is not None:
        a.nb_chambres = int(bedrooms)
    elif a.nb_pieces is not None:
        a.nb_chambres = a.nb_pieces

    bathrooms = _number(estate.get("bathrooms"))
    if bathrooms is not None:
        a.nb_salles_bain = int(bathrooms)

    floor = str(features.get("floor") or "").strip()
    if floor:
        a.etage = f"{floor} étage" if floor.isdigit() else floor

    # Équipements structurés : connus -> True/False ; inconnus -> None
    # (le nettoyage complète les inconnus à partir de la description).
    car_places = _number(features.get("car_places"))
    a.ascenseur = _yes_no(features.get("elevator"))
    a.climatisation = _yes_no(features.get("air_conditioning"))
    a.chauffage_central = _yes_no(features.get("heating"))
    a.meuble = _yes_no(features.get("furnitured"))
    a.parking = True if car_places else _yes_no(features.get("box"))
    a.piscine = None

    return a


def run(max_annonces: int = None, out_csv: str = "annonces_tecnocasa.csv"):
    """
    max_annonces: None = tout le sitemap (collecte complète).
    Reprise automatique : les annonces déjà présentes dans out_csv sont ignorées.
    """
    session = get_session()
    seen = load_seen_ids(out_csv)
    print(f"[Tecnocasa] {len(seen)} annonces déjà collectées (reprise)")

    urls = sale_urls_from_sitemap(session)
    print(f"[Tecnocasa] {len(urls)} annonces de vente dans le sitemap")

    n_saved = 0
    for type_bien, url in urls:
        if max_annonces and n_saved >= max_annonces:
            break
        ad_id = "tecnocasa_" + SALE_URL_RE.match(url).group(2)
        if ad_id in seen or not robots_allowed(session, url):
            continue
        seen.add(ad_id)
        try:
            append_annonce(build_annonce(get_estate(session, url), url, type_bien), out_csv)
            n_saved += 1
        except Exception as e:
            print(f"    erreur détail {url} -> {e}")
        polite_sleep()

    print(f"[Tecnocasa] {n_saved} annonces ajoutées dans {out_csv}")


if __name__ == "__main__":
    run(max_annonces=5)
