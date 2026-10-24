"""
Étape 0 - Téléchargement des données DECP consolidées depuis data.gouv.fr

Interroge l'API de data.gouv.fr pour trouver le fichier Parquet le plus récent
du jeu "Données essentielles de la commande publique consolidées (format tabulaire)",
puis le télécharge dans data/raw/decp.parquet.

Utilisation :
    python src/telecharger_donnees.py
    python src/telecharger_donnees.py --sortie data/raw/decp.parquet
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ID_JEU_DE_DONNEES = "608c055b35eb4e6ee20eb325"
URL_API = f"https://www.data.gouv.fr/api/1/datasets/{ID_JEU_DE_DONNEES}/"


def choisir_fichier_parquet(metadonnees: dict) -> dict:
    """Retourne la ressource Parquet principale (la plus volumineuse) du jeu de données."""
    parquets = [
        r for r in metadonnees.get("resources", [])
        if (r.get("format") or "").lower() == "parquet"
        or (r.get("url") or "").lower().endswith(".parquet")
    ]
    # Le jeu contient aussi de petits fichiers Parquet de documentation :
    # le fichier de données est de loin le plus gros.
    principales = [r for r in parquets if r.get("type", "main") == "main"] or parquets
    if not principales:
        raise RuntimeError("Aucun fichier Parquet trouvé dans le jeu de données.")
    return max(principales, key=lambda r: r.get("filesize") or 0)


def telecharger(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporaire = destination.with_suffix(".part")
    with urllib.request.urlopen(url) as reponse, open(temporaire, "wb") as fichier:
        total = int(reponse.headers.get("Content-Length") or 0)
        recu = 0
        while bloc := reponse.read(1024 * 1024):
            fichier.write(bloc)
            recu += len(bloc)
            if total:
                print(f"\r  {recu / 1e6:6.0f} / {total / 1e6:.0f} Mo "
                      f"({100 * recu / total:3.0f} %)", end="", flush=True)
    print()
    temporaire.replace(destination)  # le fichier n'apparaît qu'une fois complet


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sortie", type=Path, default=Path("data/raw/decp.parquet"))
    a = p.parse_args()

    print("Recherche du fichier sur data.gouv.fr...")
    with urllib.request.urlopen(URL_API) as reponse:
        metadonnees = json.load(reponse)

    ressource = choisir_fichier_parquet(metadonnees)
    taille = (ressource.get("filesize") or 0) / 1e6
    print(f"Fichier : {ressource.get('title')} ({taille:.0f} Mo), "
          f"mis à jour le {(ressource.get('last_modified') or '')[:10]}")

    telecharger(ressource["url"], a.sortie)
    print(f"Terminé : {a.sortie}")


if __name__ == "__main__":
    try:
        main()
    except Exception as erreur:  # message clair plutôt qu'une longue trace
        sys.exit(f"Échec du téléchargement : {erreur}\n"
                 f"Tu peux aussi télécharger le fichier Parquet à la main sur "
                 f"https://www.data.gouv.fr/datasets/{ID_JEU_DE_DONNEES}")
