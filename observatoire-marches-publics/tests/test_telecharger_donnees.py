"""Test du choix du fichier à télécharger, sans accès réseau."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from telecharger_donnees import choisir_fichier_parquet  # noqa: E402

METADONNEES = {
    "resources": [
        {"title": "decp.csv", "format": "csv", "type": "main", "filesize": 2_400_000_000},
        {"title": "decp.parquet", "format": "parquet", "type": "main", "filesize": 236_000_000,
         "url": "https://exemple.fr/decp.parquet"},
        {"title": "statistiques.parquet", "format": "parquet", "type": "documentation",
         "filesize": 25_000},
    ]
}


def test_choisit_le_parquet_principal():
    assert choisir_fichier_parquet(METADONNEES)["title"] == "decp.parquet"


def test_erreur_si_aucun_parquet():
    with pytest.raises(RuntimeError):
        choisir_fichier_parquet({"resources": [{"format": "csv"}]})
