# Rapport de nettoyage — dataset_immo_tunisie

## Dataset brut : 2385 lignes, 22 colonnes
Sources : {'tayara': np.int64(1716), 'mubawab': np.int64(573), 'tecnocasa': np.int64(96)}

### 1) type_transaction='inconnu' supprimées : 9 lignes retirées

### 2) Prix Tecnocasa corrigés (mensualité crédit -> prix réel) : 96/96
### 3) Prix Mubawab manquants comblés depuis le texte : 492/570
### 4) Prix Tayara hors bornes plausibles : 90 détectés, 1 corrigés, 89 mis à NaN (irrécupérables)

Taux de prix manquant après nettoyage : 29.3% (vs 46.2% avant)

### 5) Gouvernorats normalisés sur les 24 officiels. Non résolus (mis à NaN) : 0

### 6) Outliers prix_m2 retirés (IQR x2.5, par gouvernorat+transaction) : 29 lignes
### 7) Lignes surface_m2=0 retirées : 3

### 8) Doublons retirés (titre+gouvernorat+surface+prix+pièces identiques) : 1

## Dataset final : 2343 lignes (98.2% du brut conservé), 19 colonnes

Répartition vente/location : {'vente': np.int64(1289), 'location': np.int64(1054)}
Taux de valeurs manquantes restantes :
id                    0.0
source                0.0
type_transaction      0.0
type_bien             0.0
gouvernorat           0.0
ville                24.7
prix_dt              29.6
prix_m2              55.1
surface_m2           45.9
nb_pieces            28.1
nb_chambres           2.6
nb_salles_bain       14.3
etage                72.4
ascenseur             0.0
parking               0.0
piscine               0.0
climatisation         0.0
chauffage_central     0.0
meuble                0.0

## Sous-ensemble 'prêt pour l'entraînement' (prix_dt non-null) : 1650 lignes -> /mnt/user-data/outputs/dataset_immo_tunisie_train_ready.csv
Répartition : {'vente': np.int64(1019), 'location': np.int64(631)}