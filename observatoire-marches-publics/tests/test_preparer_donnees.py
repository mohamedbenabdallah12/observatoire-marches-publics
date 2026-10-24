"""Tests de l'étape 1 sur un petit jeu de données fictif au format DECP."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from preparer_donnees import preparer  # noqa: E402


def ligne(uid, titulaire, montant=100_000, region="11", date="2024-03-15",
          actuelle=True, publication="2024-03-20", anomalie=None, cpv="72000000-5", offres=3):
    return {
        "uid": uid, "acheteur_id": "A1", "acheteur_nom": "Ville de Test",
        "acheteur_categorie": "Commune", "acheteur_commune_nom": "Cergy",
        "acheteur_departement_code": "95", "acheteur_departement_nom": "Val-d'Oise",
        "acheteur_region_code": region, "acheteur_latitude": 49.03, "acheteur_longitude": 2.06,
        "titulaire_id": titulaire, "titulaire_nom": f"Entreprise {titulaire}",
        "titulaire_categorie": "PME", "titulaire_activite_libelle": "Programmation informatique",
        "titulaire_departement_nom": "Paris", "titulaire_region_nom": "Île-de-France",
        "titulaire_distance": 30, "objet": "Maintenance applicative", "nature": "Marché",
        "procedure": "Appel d'offres ouvert", "codeCPV": cpv, "montant": montant,
        "dureeMois": 12, "offresRecues": offres,
        "dateNotification": pd.Timestamp(date).date(),
        "datePublicationDonnees": pd.Timestamp(publication).date(),
        "donneesActuelles": actuelle, "montant_anomalie": anomalie,
    }


@pytest.fixture
def resultat(tmp_path):
    lignes = [
        ligne("M1", "T1"),                                      # cas normal
        ligne("M2", "T2", montant=300_000),                     # co-titulaires
        ligne("M2", "T3", montant=300_000),
        ligne("M3", "T1", publication="2024-03-20"),            # doublon (2 sources)
        ligne("M3", "T1", publication="2024-04-01"),
        ligne("M4", "T1", region="84"),                         # hors Île-de-France
        ligne("M5", "T1", date="2019-06-01"),                   # hors période
        ligne("M6", "T1", actuelle=False),                      # ancienne version
        ligne("M7", "T1", montant=9e12),                        # montant aberrant
        ligne("M8", "T1", anomalie="montant trop élevé"),       # anomalie signalée
        ligne("M9", "T1", cpv=None, offres=1),                  # CPV absent, offre unique
    ]
    source = tmp_path / "decp.parquet"
    pd.DataFrame(lignes).to_parquet(source)
    sortie = tmp_path / "out"
    stats = preparer(source, sortie, region="11", debut="2022-01-01", fin="2026-12-31")
    fait = pd.read_csv(sortie / "fait_attributions.csv", dtype={"division_cpv": str})
    return stats, fait, sortie


def test_filtres_region_periode_version(resultat):
    _, fait, _ = resultat
    assert set(fait.id_marche) == {"M1", "M2", "M3", "M7", "M8", "M9"}


def test_doublons_supprimes(resultat):
    stats, fait, _ = resultat
    assert (fait.id_marche == "M3").sum() == 1
    assert stats["doublons_supprimes"] == 1


def test_montant_reparti_entre_cotitulaires(resultat):
    _, fait, _ = resultat
    m2 = fait[fait.id_marche == "M2"]
    assert len(m2) == 2
    assert m2.montant_part.sum() == pytest.approx(300_000)


def test_montants_douteux_marques_mais_conserves(resultat):
    _, fait, _ = resultat
    fiables = dict(zip(fait.id_marche, fait.montant_fiable))
    assert not fiables["M7"] and not fiables["M8"]
    assert fiables["M1"]


def test_cpv_et_offre_unique(resultat):
    _, fait, sortie = resultat
    m1 = fait[fait.id_marche == "M1"].iloc[0]
    m9 = fait[fait.id_marche == "M9"].iloc[0]
    assert m1.division_cpv == "72"
    assert m9.offre_unique
    categories = pd.read_csv(sortie / "dim_categorie.csv", dtype=str).fillna("")
    # Toute division présente dans les faits existe dans la dimension (intégrité du modèle)
    assert set(fait.division_cpv.fillna("")) <= set(categories.division_cpv)


def test_fichiers_produits(resultat):
    _, _, sortie = resultat
    for nom in ["fait_attributions.csv", "dim_acheteur.csv", "dim_titulaire.csv",
                "dim_categorie.csv", "rapport_qualite.md"]:
        assert (sortie / nom).exists()
