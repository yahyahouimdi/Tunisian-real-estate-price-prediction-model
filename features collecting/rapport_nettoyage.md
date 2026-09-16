# Rapport de nettoyage — dataset_immo_tunisie (vente uniquement)

## Dataset brut : 2385 lignes
Sources : {'tayara': np.int64(1716), 'mubawab': np.int64(573), 'tecnocasa': np.int64(96)}

### Sources invalides/inconnues : 0 lignes

### 1) Filtre vente uniquement : 1067 lignes retirées, 1318 lignes vente conservées

### IDs manquants : 0 lignes
### Lignes supprimées pour ID manquant : 0
### IDs source+id dupliqués détectés : 0 lignes
### Doublons source+id supprimés : 0

### 2) Prix Tecnocasa corrigés : 96/96
### 3) Prix existants hors bornes [50,000 ; 10,000,000] TND : 37 invalidés
### 4) Prix récupérés via 'TND' : 376/650
### 5) Prix récupérés via 'DT' : 8/274

Prix manquants au final : 266 / 1318 (20.2%)

### 6) Gouvernorats normalisés. Non résolus : 0

### 7) Ville récupérée depuis titre/description : 69/456 comblées
Villes toujours manquantes : 387

### 8) Surfaces hors bornes [30 ; 2500] m² : 12 invalidées

### 9a) nb_salles_bain : 837 manquantes/aberrantes, 647 récupérées
### 9b) nb_chambres : 78 manquantes/aberrantes, 45 récupérées

### 10) nb_pieces nettoyé : 1286/1318 lignes

### 11) Incohérences nb_chambres > nb_pieces : 83
### Bornes nb_pieces [1 ; 15] : 0 invalidées
### Bornes nb_chambres [0 ; 10] : 0 invalidées
### Bornes nb_salles_bain [0 ; 8] : 0 invalidées
### Boolean ascenseur : 0 inconnues
### Boolean parking : 0 inconnues
### Boolean piscine : 0 inconnues
### Boolean climatisation : 0 inconnues
### Boolean chauffage_central : 0 inconnues
### Boolean meuble : 0 inconnues

### 12) prix_m2 hors bornes [300 ; 15000] : 17 valeurs
### 13) Outliers statistiques prix_m2 (IQR x2.5) détectés : 7

### 14) Prix hors bornes finales [50,000 ; 10,000,000] : 0

### 15) Doublons de contenu potentiels : 8 lignes
### Doublons de contenu supprimés : 4

### Train-ready : 1048/1314 lignes avec prix_dt valide

## Dataset final : 1314 lignes (55.1% du brut original)

### Valeurs manquantes restantes :
id                     0.0
source                 0.0
type_transaction       0.0
type_bien              0.0
gouvernorat            0.0
ville                 29.5
prix_dt_original      46.7
prix_dt               20.2
prix_m2               35.8
surface_m2            22.5
nb_pieces_original    32.7
nb_pieces              2.4
nb_chambres            8.8
nb_salles_bain        14.5
etage_original        71.8
etage                  0.0
ascenseur              0.0
parking                0.0
piscine                0.0
climatisation          0.0
chauffage_central      0.0
meuble                 0.0

### Features utilisées pour le modèle :
- source
- type_bien
- gouvernorat
- ville
- surface_m2
- nb_pieces
- nb_chambres
- nb_salles_bain
- etage
- ascenseur
- parking
- piscine
- climatisation
- chauffage_central
- meuble

### Target : prix_dt

### IMPORTANT : prix_m2 est conservé pour l'audit/outlier detection mais exclu des features du modèle pour éviter le data leakage.