"""
main.py
Lance les 3 scrapers et fusionne les CSV individuels en un seul dataset
prêt pour la phase de preprocessing / modélisation.

Usage:
    python main.py                # lance tout avec des paramètres restreints (test)
    python main.py --full         # lance avec une couverture plus large (production)
"""

import argparse
import glob
import pandas as pd

import scraper_tayara
import scraper_mubawab
import scraper_tecnocasa
from common import FIELDNAMES


def merge_all(pattern: str = "annonces_*.csv", out_path: str = "dataset_immo_tunisie.csv"):
    frames = []
    for f in glob.glob(pattern):
        try:
            df = pd.read_csv(f)
            frames.append(df)
            print(f"  {f}: {len(df)} lignes")
        except Exception as e:
            print(f"  {f}: erreur lecture -> {e}")

    if not frames:
        print("Aucun fichier trouvé à fusionner.")
        return

    merged = pd.concat(frames, ignore_index=True)
    # dédoublonnage grossier: même titre + même gouvernorat + même prix + même surface
    merged.drop_duplicates(subset=["titre", "gouvernorat", "prix_dt", "surface_m2"], inplace=True)
    merged.to_csv(out_path, index=False)
    print(f"\nDataset fusionné: {len(merged)} annonces uniques -> {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Couverture large (plus long)")
    args = parser.parse_args()

    if args.full:
        scraper_tayara.run(max_pages_per_category=30)
        scraper_mubawab.run(gouvernorats_slugs=None, max_pages_per_combo=15)
        scraper_tecnocasa.scrape_with_playwright()
    else:
        print("Mode TEST (couverture restreinte). Utilise --full pour la collecte complète.\n")
        scraper_tayara.run(max_pages_per_category=2)
        scraper_mubawab.run(gouvernorats_slugs=["tunis", "ariana"], max_pages_per_combo=2)
        # Tecnocasa nécessite Playwright installé -> commenté par défaut en mode test
        # scraper_tecnocasa.scrape_with_playwright()

    print("\nFusion des fichiers CSV...")
    merge_all()


if __name__ == "__main__":
    main()
