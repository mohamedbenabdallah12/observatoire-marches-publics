# Observatoire des marchés publics d'Île-de-France

Analyse des marchés publics attribués en Île-de-France depuis 2022, à partir des
Données Essentielles de la Commande Publique (DECP), publiées en open data.

**Questions étudiées**
- Combien les acheteurs publics franciliens dépensent-ils, pour quoi, et comment cela évolue-t-il ?
- Les marchés sont-ils concentrés sur quelques fournisseurs ?
- Quelle part revient aux PME ? Combien de marchés n'ont reçu qu'une seule offre ?

**Stack** : Python, DuckDB, Power BI (Power Query, DAX), pytest

## Architecture

```
DECP consolidées (Parquet, ~230 Mo, France entière)
        │  src/preparer_donnees.py  (DuckDB)
        ▼
Schéma en étoile (CSV)                        ┌── dim_acheteur
   fait_attributions ─────────────────────────┼── dim_titulaire
   (une ligne par marché × titulaire)         └── dim_categorie (division CPV)
        │
        ▼
Rapport Power BI (Power Query + mesures DAX)
```

## Lancer le projet

1. Installer les dépendances :
   ```
   pip install -r requirements.txt
   ```
2. Télécharger les données (environ 230 Mo) :
   ```
   python src/telecharger_donnees.py
   ```
   Le script trouve le fichier Parquet le plus récent via l'API de data.gouv.fr
   et l'enregistre dans `data/raw/decp.parquet`. Sinon, le télécharger à la main depuis
   [data.gouv.fr - DECP consolidées (format tabulaire)](https://www.data.gouv.fr/datasets/donnees-essentielles-de-la-commande-publique-consolidees-format-tabulaire).
3. Préparer les données :
   ```
   python src/preparer_donnees.py data/raw/decp.parquet
   ```
   Les tables sont créées dans `data/processed/`, avec un `rapport_qualite.md`
   qui détaille chaque étape de nettoyage.
4. Lancer les tests :
   ```
   pytest
   ```

Options utiles : `--region 84` (autre région), `--debut 2023-01-01`, `--fin 2025-12-31`.

## Choix de nettoyage

| Problème dans les données | Traitement |
|---|---|
| Un marché modifié apparaît en plusieurs versions | Seule la version actuelle est gardée |
| Un marché publié par plusieurs sources | Dédoublonnage par marché et titulaire |
| Montants nuls, négatifs ou aberrants (erreurs de saisie) | Marqués `montant_fiable = false`, exclus des totaux mais comptés |
| Marchés à plusieurs co-titulaires | Montant réparti (`montant_part`) pour éviter les doubles comptes |
| Code CPV détaillé (8 chiffres) peu lisible | Regroupé en ~45 catégories d'achat |

## Résultats

_À compléter après l'étape 2 (rapport Power BI) : captures et 3 à 5 constats chiffrés._

## Source des données

Données Essentielles de la Commande Publique, consolidées par Colin Maudry
([decp-processing](https://github.com/ColinMaudry/decp-processing)), publiées sur data.gouv.fr.
