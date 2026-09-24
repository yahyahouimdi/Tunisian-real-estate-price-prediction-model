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
### 2b) Prix Tayara re-parsés après le titre : 663/776 trouvés, 134 modifiés (dont 61 écrits en milliers x1000, 1 milliers rejetés)
### 3) Prix existants hors bornes [50,000 ; 10,000,000] TND : 9 invalidés
### 4) Prix récupérés via 'TND' : 376/564
### 5) Prix récupérés via 'DT' : 0/188

Prix manquants au final : 188 / 1318 (14.3%)

### 6) Gouvernorats normalisés. Non résolus : 0

### 7a) Ville Mubawab récupérée depuis la page : 261/446

### 7) Ville récupérée depuis titre/description : 76/195 comblées
Villes toujours manquantes : 119
### 7b) Orthographe des villes normalisée : 191 -> 178 villes distinctes
### 7c) Conflits ville/gouvernorat corrigés : 4
### 7d) Villes rares (< 5) regroupées : 287 lignes -> 63 catégories de ville
### Gouvernorats rares (< 10) regroupés par région : 34 lignes (Gabès, Gafsa, Jendouba, Kairouan, Kasserine, Le Kef, Monastir, Médenine, Sidi Bouzid, Siliana, Tataouine)
### Petits groupes de villes fusionnés par région : 25 lignes -> 59 catégories de ville

### 8) Surfaces hors bornes [30 ; 2500] m² : 12 invalidées

### 9a) nb_salles_bain : 837 manquantes/aberrantes, 647 récupérées
### 9b) nb_chambres depuis titre S+N : 741
### 9b) nb_chambres depuis scraper S+N : 147
### 9b) nb_chambres depuis texte 'X chambres' : 392
### nb_chambres final : 1280/1318 renseignés (nb_pieces retiré des features : doublon de nb_chambres)
### Bornes nb_chambres [0 ; 10] : 0 invalidées
### Bornes nb_salles_bain [0 ; 8] : 0 invalidées
### Boolean ascenseur : 0 inconnues
### Boolean parking : 0 inconnues
### Boolean piscine : 0 inconnues
### Boolean climatisation : 0 inconnues
### Boolean chauffage_central : 0 inconnues
### Boolean meuble : 0 inconnues
### 13b) ascenseur (Tayara/Tecnocasa, texte libre) : 106 oui, 14 non, 752 non mentionné
### 13b) parking (Tayara/Tecnocasa, texte libre) : 350 oui, 1 non, 521 non mentionné
### 13b) piscine (Tayara/Tecnocasa, texte libre) : 101 oui, 0 non, 771 non mentionné
### 13b) climatisation (Tayara/Tecnocasa, texte libre) : 167 oui, 0 non, 705 non mentionné
### 13b) chauffage_central (Tayara/Tecnocasa, texte libre) : 201 oui, 0 non, 671 non mentionné
### 13b) meuble (Tayara/Tecnocasa, texte libre) : 84 oui, 1 non, 787 non mentionné

### Étage numérique (etage_num) : 340/1318 connus

### 12) prix_m2 hors bornes [300 ; 15000] : 3 valeurs (1 trop bas, 2 trop hauts)
### 12b) Prix factices (1 111 000, 1 234 567...) : 4 invalidés
### 13) Outliers statistiques prix_m2 (IQR x2.5) détectés : 5

### 14) Prix hors bornes finales [50,000 ; 10,000,000] : 0

### 15) Doublons de contenu potentiels : 8 lignes
### Doublons de contenu supprimés : 4
### 15b) Même bien (gouvernorat+type+prix+surface, chambres/ville compatibles) : 27 doublons supprimés (dont 7 inter-sites)
### Groupes 'groupe_bien' partagés (unités d'un même projet) : 28 lignes, 13 groupes

### Train-ready : 1093/1287 lignes avec prix_dt valide

## Dataset final : 1287 lignes (54.0% du brut original)

### Valeurs manquantes restantes :
id                       0.0
groupe_bien              0.0
source                   0.0
type_transaction         0.0
type_bien                0.0
region                   0.0
gouvernorat              0.0
ville_original           8.7
ville                    9.2
prix_dt_original        46.4
prix_dt                 15.1
prix_m2                 34.1
outlier_prix_m2          0.0
surface_m2              23.1
nb_pieces_original      33.3
nb_chambres_original     3.7
nb_chambres              3.0
nb_salles_bain          14.4
etage_original          71.5
etage                    0.0
etage_num               73.8
ascenseur               57.6
parking                 39.8
piscine                 58.7
climatisation           53.9
chauffage_central       51.3
meuble                  60.1

### Features utilisées pour le modèle :
- type_bien
- region
- gouvernorat
- ville
- surface_m2
- nb_chambres
- nb_salles_bain
- etage_num
- ascenseur
- parking
- piscine
- climatisation
- chauffage_central

### Target : prix_dt

### IMPORTANT : prix_m2 est conservé pour l'audit/outlier detection mais exclu des features du modèle pour éviter le data leakage.