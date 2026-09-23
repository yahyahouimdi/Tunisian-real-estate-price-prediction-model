"""
main.py
Lance les 3 scrapers (vente uniquement) et fusionne les CSV individuels en
un seul dataset prêt pour le nettoyage (features collecting/clean_dataset.py).

Usage:
    python main.py                # test rapide (peu de pages)
    python main.py --full         # collecte complète (plusieurs heures)
    python main.py --merge-only   # refait seulement la fusion des CSV

Chaque scraper sauvegarde au fil de l'eau et reprend là où il s'est arrêté :
relancer la même commande après une interruption ne recollecte pas les
annonces déjà présentes dans annonces_*.csv.
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
    for f in sorted(glob.glob(pattern)):
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
    merged = merged.reindex(columns=FIELDNAMES)
    # Même annonce collectée deux fois -> même id. Les doublons de contenu
    # (même bien sur plusieurs sites) sont traités dans le nettoyage.
    merged = merged.drop_duplicates(subset=["id"], keep="last")
    merged.to_csv(out_path, index=False)
    print(f"\nDataset fusionné: {len(merged)} annonces uniques -> {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Collecte complète (plusieurs heures)")
    parser.add_argument("--merge-only", action="store_true", help="Fusionne seulement les CSV existants")
    args = parser.parse_args()

    if args.merge_only:
        pass
    elif args.full:
        scraper_tecnocasa.run(max_annonces=None)
        scraper_mubawab.run(gouvernorats_slugs=None)
        scraper_tayara.run(max_pages_per_category=None)
    else:
        print("Mode TEST (couverture restreinte). Utilise --full pour la collecte complète.\n")
        scraper_tecnocasa.run(max_annonces=3)
        scraper_mubawab.run(gouvernorats_slugs=["tunis"])
        scraper_tayara.run(max_pages_per_category=1)

    print("\nFusion des fichiers CSV...")
    merge_all()


if __name__ == "__main__":
    main()
