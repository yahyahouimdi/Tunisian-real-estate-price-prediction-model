"""
scraper_tayara.py
Scrape les annonces immobilières (vente) de tayara.tn.

Structure observée (vérifiée en octobre 2026) :
- Pages de catégorie : https://www.tayara.tn/listing/c/immobilier/appartements/?page=N
  (30 annonces par page ; ~4 800 appartements et ~2 800 maisons, vente + location)
- Pages d'annonce : https://www.tayara.tn/item/{categorie}/{gouv}/{ville}/{slug}/{id}/
- robots.txt : tout est autorisé.

Tayara est en Next.js : chaque page embarque ses données dans
<script id="__NEXT_DATA__"> (JSON). On lit ce JSON au lieu de deviner par
regex sur le texte visible :
- page de listing -> props.pageProps.searchedListingsAction.newHits
  (id, titre, description complète, prix numérique, gouvernorat, délégation)
- page d'annonce  -> props.pageProps.adDetails.adParams
  (Type de transaction, Superficie, Chambres, Salles de bains)

L'ancienne extraction par regex collait les chiffres de fin de titre au prix
("MENZAH 6" + "248 000 DT" -> 6 248 000) : ce problème disparaît ici.

DONNÉES PERSONNELLES : le JSON contient aussi le nom, l'e-mail et le
téléphone du vendeur (adUserData, phone, publisher). On ne lit JAMAIS ces
champs : seuls les champs de l'annonce sont conservés.

Les locations évidentes (titre/description "à louer", "loyer", "/mois"...)
sont ignorées dès la page de listing pour ne pas charger leur page de détail
(le projet ne modélise que la vente pour l'instant).
"""

import json
import re

from bs4 import BeautifulSoup

from common import (
    Annonce, get_session, polite_sleep, enrich_common_fields,
    append_annonce, load_seen_ids,
)

BASE = "https://www.tayara.tn"

CATEGORIES = {
    "appartement": "appartements",
    "maison_villa": "maisons-et-villas",
}

HITS_PER_PAGE = 30

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S
)

RENT_RE = re.compile(
    r"\bà\s*louer\b|\ba\s+louer\b|\blocation\b|\bloyer\b|/\s*mois\b|"
    r"\bpar\s+mois\b|للكراء|كراء",
    re.I,
)
SALE_RE = re.compile(r"\bà\s*vendre\b|\ba\s+vendre\b|\bvente\b|للبيع|بيع", re.I)


def _next_data(html: str) -> dict:
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("__NEXT_DATA__ introuvable (structure du site modifiée ?)")
    return json.loads(m.group(1))["props"]["pageProps"]


def is_obvious_rental(hit: dict) -> bool:
    text = f"{hit.get('title', '')} {hit.get('description', '')}"
    return bool(RENT_RE.search(text)) and not SALE_RE.search(text)


def get_listing_page(session, category_slug: str, page: int):
    """Retourne (hits, total, {id: url}) pour une page de listing."""
    url = f"{BASE}/listing/c/immobilier/{category_slug}/"
    if page > 1:
        url += f"?page={page}"
    resp = session.get(url, timeout=20)
    resp.raise_for_status()

    action = _next_data(resp.text)["searchedListingsAction"]
    hits = action.get("newHits") or []
    total = action.get("totalHitsCount") or 0

    # URL réelle de chaque annonce (pour la colonne url)
    urls = {}
    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        m = re.search(r"/item/.+/([a-f0-9]{24})/?$", a["href"])
        if m:
            href = a["href"]
            urls[m.group(1)] = href if href.startswith("http") else BASE + href
    return hits, total, urls


def get_ad_params(session, url: str) -> dict:
    """{label: value} de adParams (Superficie, Chambres, ...) ; rien d'autre."""
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    ad = _next_data(resp.text).get("adDetails") or {}
    return {
        p.get("label"): p.get("value")
        for p in ad.get("adParams") or []
        if p.get("label")
    }


def _to_number(value):
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def build_annonce(hit: dict, params: dict, url: str, type_bien: str) -> Annonce:
    titre = hit.get("title") or ""
    description = hit.get("description") or ""
    location = hit.get("location") or {}

    transaction = (params.get("Type de transaction") or "").lower()
    if "vendre" in transaction or "vente" in transaction:
        transaction = "vente"
    elif "louer" in transaction or "location" in transaction:
        transaction = "location"
    else:
        transaction = "inconnu"

    a = Annonce(
        id=f"tayara_{hit['id']}",
        source="tayara",
        url=url,
        type_transaction=transaction,
        type_bien=type_bien,
        titre=titre,
        description_brute=description[:3000],
        date_publication=(hit.get("metadata") or {}).get("publishedOn"),
    )

    # Équipements, étage, S+N : regex sur le VRAI texte de l'annonce
    # (titre + description), sans le menu/pied de page du site.
    enrich_common_fields(a, f"{titre}\n{description}")

    # Champs structurés : prioritaires sur les regex
    a.prix_dt = _to_number(hit.get("price"))
    a.gouvernorat = location.get("governorate") or a.gouvernorat
    a.ville = location.get("delegation") or None

    surface = _to_number(params.get("Superficie"))
    chambres = _to_number(params.get("Chambres"))
    bains = _to_number(params.get("Salles de bains"))

    if surface:
        a.surface_m2 = surface
    if chambres is not None:
        a.nb_chambres = int(chambres)
        # nb_pieces = N de "S+N" (convention du projet) : S+N du texte
        # si présent, sinon le nombre de chambres structuré.
        if a.nb_pieces is None:
            a.nb_pieces = int(chambres)
    if bains is not None:
        a.nb_salles_bain = int(bains)

    return a


def run(max_pages_per_category: int = None, out_csv: str = "annonces_tayara.csv"):
    """
    max_pages_per_category: None = toutes les pages (collecte complète).
    Reprise automatique : les annonces déjà présentes dans out_csv sont ignorées.
    """
    session = get_session()
    seen = load_seen_ids(out_csv)
    n_saved = n_rentals = 0
    print(f"[Tayara] {len(seen)} annonces déjà collectées (reprise)")

    for type_bien, category_slug in CATEGORIES.items():
        page, last_page = 1, None
        while True:
            if max_pages_per_category and page > max_pages_per_category:
                break
            if last_page and page > last_page:
                break
            try:
                hits, total, urls = get_listing_page(session, category_slug, page)
            except Exception as e:
                print(f"  [{type_bien}] page {page}: erreur listing -> {e}")
                break
            if not hits:
                break
            last_page = -(-total // HITS_PER_PAGE)
            print(f"[Tayara] {type_bien} page {page}/{last_page} ({total} annonces)")
            polite_sleep()

            for hit in hits:
                ad_id = f"tayara_{hit['id']}"
                if ad_id in seen:
                    continue
                seen.add(ad_id)
                if is_obvious_rental(hit):
                    n_rentals += 1
                    continue

                url = urls.get(hit["id"]) or f"{BASE}/item/{category_slug}/x/x/x/{hit['id']}/"
                try:
                    params = get_ad_params(session, url)
                except Exception as e:
                    print(f"    erreur détail {url} -> {e}")
                    params = {}
                append_annonce(build_annonce(hit, params, url, type_bien), out_csv)
                n_saved += 1
                polite_sleep()

            page += 1

    print(f"[Tayara] {n_saved} annonces ajoutées dans {out_csv} "
          f"({n_rentals} locations évidentes ignorées)")


if __name__ == "__main__":
    run(max_pages_per_category=1)
