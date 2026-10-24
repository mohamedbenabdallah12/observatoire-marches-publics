"""
Étape 1 - Préparation des données (DECP consolidées -> schéma en étoile)

Lit le fichier Parquet des Données Essentielles de la Commande Publique (DECP),
filtre une région et une période, nettoie les données et produit un schéma
en étoile prêt à être importé dans Power BI :

    data/processed/
        fait_attributions.csv   une ligne par couple (marché, titulaire)
        dim_acheteur.csv        acheteurs publics
        dim_titulaire.csv       entreprises titulaires
        dim_categorie.csv       catégories d'achat (division CPV)
        rapport_qualite.md      ce qui a été filtré ou corrigé, et pourquoi

Utilisation :
    python src/preparer_donnees.py data/raw/decp.parquet
    python src/preparer_donnees.py data/raw/decp.parquet --region 11 --debut 2022-01-01
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import duckdb

# Divisions CPV (2 premiers chiffres du code CPV) -> libellé lisible
DIVISIONS_CPV = {
    "03": "Agriculture, élevage, pêche",
    "09": "Énergie et produits pétroliers",
    "14": "Produits miniers et métaux de base",
    "15": "Alimentation et boissons",
    "16": "Machines agricoles",
    "18": "Vêtements et accessoires",
    "19": "Cuir, textiles, plastiques",
    "22": "Imprimés et produits connexes",
    "24": "Produits chimiques",
    "30": "Matériel informatique et de bureau",
    "31": "Équipements électriques et éclairage",
    "32": "Équipements de télécommunication",
    "33": "Équipements médicaux et pharmaceutiques",
    "34": "Véhicules et équipements de transport",
    "35": "Sécurité, défense, incendie",
    "37": "Instruments de musique, sport, jeux",
    "38": "Équipements de laboratoire et optique",
    "39": "Mobilier et aménagement",
    "41": "Eau",
    "42": "Machines industrielles",
    "43": "Machines pour mines et construction",
    "44": "Matériaux et structures de construction",
    "45": "Travaux de construction (BTP)",
    "48": "Logiciels et systèmes d'information",
    "50": "Réparation et maintenance",
    "51": "Installation d'équipements",
    "55": "Hôtellerie, restauration",
    "60": "Transport",
    "63": "Services de transport annexes, voyages",
    "64": "Postes et télécommunications",
    "65": "Services publics (eau, énergie)",
    "66": "Services financiers et assurances",
    "70": "Services immobiliers",
    "71": "Architecture, ingénierie, contrôle",
    "72": "Services informatiques",
    "73": "Recherche et développement",
    "75": "Administration, défense, sécurité sociale",
    "76": "Services liés au pétrole et au gaz",
    "77": "Agriculture, sylviculture, espaces verts",
    "79": "Services aux entreprises (conseil, communication)",
    "80": "Enseignement et formation",
    "85": "Santé et action sociale",
    "90": "Assainissement, déchets, nettoyage",
    "92": "Loisirs, culture, sport",
    "98": "Autres services",
}

# Au-delà de ce montant pour un seul marché, on considère la valeur comme suspecte
# (souvent une erreur de saisie : centimes saisis comme euros, zéros en trop, etc.)
MONTANT_MAX_PLAUSIBLE = 500_000_000


def colonnes_disponibles(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in con.execute("DESCRIBE brut").fetchall()}


def preparer(source: Path, sortie: Path, region: str, debut: str, fin: str) -> dict:
    sortie.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    con.execute(f"CREATE VIEW brut AS SELECT * FROM read_parquet('{source.as_posix()}')")
    cols = colonnes_disponibles(con)
    stats: dict[str, int] = {}
    stats["lignes_source"] = con.execute("SELECT count(*) FROM brut").fetchone()[0]

    # Selon les versions du fichier, certaines colonnes peuvent manquer
    filtre_version = "AND donneesActuelles" if "donneesActuelles" in cols else ""
    anomalie = "montant_anomalie" if "montant_anomalie" in cols else "NULL"

    # 1. Filtre région, période et version la plus récente de chaque marché
    con.execute(f"""
        CREATE TABLE perimetre AS
        SELECT *
        FROM brut
        WHERE acheteur_region_code = '{region}'
          AND dateNotification BETWEEN DATE '{debut}' AND DATE '{fin}'
          {filtre_version}
    """)
    stats["lignes_perimetre"] = con.execute("SELECT count(*) FROM perimetre").fetchone()[0]

    # 2. Dédoublonnage : un marché peut être publié par plusieurs sources
    con.execute("""
        CREATE TABLE dedoublonne AS
        SELECT * EXCLUDE (rang) FROM (
            SELECT *,
                   row_number() OVER (
                       PARTITION BY uid, coalesce(titulaire_id, '')
                       ORDER BY datePublicationDonnees DESC NULLS LAST
                   ) AS rang
            FROM perimetre
        ) WHERE rang = 1
    """)
    stats["doublons_supprimes"] = stats["lignes_perimetre"] - con.execute(
        "SELECT count(*) FROM dedoublonne").fetchone()[0]

    # 3. Nettoyage et colonnes calculées
    con.execute(f"""
        CREATE TABLE fait AS
        WITH base AS (
            SELECT
                uid                                        AS id_marche,
                acheteur_id                                AS id_acheteur,
                coalesce(titulaire_id, 'INCONNU')          AS id_titulaire,
                CAST(dateNotification AS DATE)             AS date_notification,
                nullif(trim(objet), '')                    AS objet,
                nature,
                procedure,
                left(regexp_replace(coalesce(codeCPV, ''), '[^0-9]', '', 'g'), 2) AS division_cpv,
                CAST(montant AS DOUBLE)                    AS montant_marche,
                dureeMois                                  AS duree_mois,
                offresRecues                               AS offres_recues,
                titulaire_distance                         AS distance_km,
                {anomalie}                                 AS anomalie_source,
                count(*) OVER (PARTITION BY uid)           AS nb_titulaires
            FROM dedoublonne
        )
        SELECT
            *,
            -- Un montant est jugé fiable s'il est positif, plausible et non signalé
            (montant_marche > 0
             AND montant_marche <= {MONTANT_MAX_PLAUSIBLE}
             AND anomalie_source IS NULL)                AS montant_fiable,
            -- Avec plusieurs co-titulaires, le montant du marché est réparti
            -- pour ne pas être compté plusieurs fois dans les totaux
            CASE WHEN montant_marche > 0
                 THEN montant_marche / nb_titulaires END AS montant_part,
            -- Un seul candidat = absence de mise en concurrence effective
            (offres_recues = 1)                          AS offre_unique
        FROM base
    """)

    stats["montants_non_fiables"] = con.execute(
        "SELECT count(*) FROM fait WHERE NOT coalesce(montant_fiable, false)").fetchone()[0]
    stats["lignes_finales"] = con.execute("SELECT count(*) FROM fait").fetchone()[0]
    stats["marches_distincts"] = con.execute(
        "SELECT count(DISTINCT id_marche) FROM fait").fetchone()[0]

    # 4. Dimensions
    con.execute("""
        CREATE TABLE dim_acheteur AS
        SELECT acheteur_id AS id_acheteur,
               any_value(acheteur_nom)               AS nom_acheteur,
               any_value(acheteur_categorie)         AS categorie_acheteur,
               any_value(acheteur_commune_nom)       AS commune,
               any_value(acheteur_departement_code)  AS code_departement,
               any_value(acheteur_departement_nom)   AS departement,
               any_value(acheteur_latitude)          AS latitude,
               any_value(acheteur_longitude)         AS longitude
        FROM dedoublonne
        WHERE acheteur_id IS NOT NULL
        GROUP BY acheteur_id
    """)

    con.execute("""
        CREATE TABLE dim_titulaire AS
        SELECT coalesce(titulaire_id, 'INCONNU')     AS id_titulaire,
               any_value(titulaire_nom)              AS nom_titulaire,
               coalesce(any_value(titulaire_categorie), 'Non renseignée') AS taille_entreprise,
               any_value(titulaire_activite_libelle) AS activite,
               any_value(titulaire_departement_nom)  AS departement,
               any_value(titulaire_region_nom)       AS region
        FROM dedoublonne
        GROUP BY 1
    """)

    con.execute("CREATE TABLE dim_categorie (division_cpv VARCHAR, categorie VARCHAR)")
    con.executemany("INSERT INTO dim_categorie VALUES (?, ?)", list(DIVISIONS_CPV.items()))
    # Codes absents ou inconnus -> catégorie "Non classé" (garde le modèle cohérent)
    con.execute("""
        INSERT INTO dim_categorie
        SELECT DISTINCT f.division_cpv, 'Non classé'
        FROM fait f LEFT JOIN dim_categorie c USING (division_cpv)
        WHERE c.division_cpv IS NULL
    """)

    # 5. Export
    for table, fichier in [("fait", "fait_attributions"), ("dim_acheteur", "dim_acheteur"),
                           ("dim_titulaire", "dim_titulaire"), ("dim_categorie", "dim_categorie")]:
        con.execute(f"COPY {table} TO '{(sortie / (fichier + '.csv')).as_posix()}' "
                    "(HEADER, DELIMITER ',')")

    ecrire_rapport(sortie / "rapport_qualite.md", stats, region, debut, fin)
    con.close()
    return stats


def nombre(n: int) -> str:
    """12345 -> '12 345' (format français)."""
    return f"{n:,}".replace(",", " ")


def ecrire_rapport(chemin: Path, s: dict, region: str, debut: str, fin: str) -> None:
    pct = lambda n, d: f"{100 * n / d:.1f} %" if d else "n/a"
    f = {k: nombre(v) for k, v in s.items()}
    chemin.write_text(f"""# Rapport de qualité des données

Généré le {dt.date.today():%d/%m/%Y} - région {region}, du {debut} au {fin}.

| Étape | Lignes |
|---|---|
| Fichier source | {f['lignes_source']} |
| Après filtre région, période et version actuelle | {f['lignes_perimetre']} |
| Doublons supprimés | {f['doublons_supprimes']} |
| **Lignes finales (marché × titulaire)** | **{f['lignes_finales']}** |
| Marchés distincts | {f['marches_distincts']} |
| Montants non fiables (nuls, négatifs, > {nombre(MONTANT_MAX_PLAUSIBLE)} EUR ou signalés) | {f['montants_non_fiables']} ({pct(s['montants_non_fiables'], s['lignes_finales'])}) |

## Règles appliquées

- Seule la version la plus récente de chaque marché est conservée (modifications).
- Un même couple marché-titulaire publié par plusieurs sources n'est gardé qu'une fois.
- Les montants douteux ne sont pas supprimés : ils sont marqués `montant_fiable = false`,
  et les mesures Power BI les excluent. On garde ainsi la trace du nombre de marchés.
- Pour un marché à plusieurs co-titulaires, `montant_part` répartit le montant
  à parts égales afin de ne pas le compter plusieurs fois.
""", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", type=Path, help="fichier Parquet DECP consolidé")
    p.add_argument("--sortie", type=Path, default=Path("data/processed"))
    p.add_argument("--region", default="11", help="code région de l'acheteur (11 = Île-de-France)")
    p.add_argument("--debut", default="2022-01-01")
    p.add_argument("--fin", default=dt.date.today().isoformat())
    a = p.parse_args()

    stats = preparer(a.source, a.sortie, a.region, a.debut, a.fin)
    print(f"{nombre(stats['lignes_finales'])} lignes, "
          f"{nombre(stats['marches_distincts'])} marchés -> {a.sortie}/")


if __name__ == "__main__":
    main()
