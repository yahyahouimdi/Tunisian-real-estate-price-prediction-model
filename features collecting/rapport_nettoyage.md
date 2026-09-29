# Rapport de nettoyage — dataset_immo_tunisie (vente uniquement)

## Dataset brut : 5490 lignes
Sources : {'tayara': np.int64(3857), 'tecnocasa': np.int64(1176), 'mubawab': np.int64(457)}

### Sources invalides/inconnues : 0 lignes

### 1) Filtre vente uniquement : 413 lignes retirées, 5077 lignes vente conservées

### IDs manquants : 0 lignes
### Lignes supprimées pour ID manquant : 0
### IDs source+id dupliqués détectés : 0 lignes
### Doublons source+id supprimés : 0

### 2) Prix Tecnocasa corrigés (format ancien scraper) : 0/1176
### 2b) Prix Tayara : 2/3444 re-parsés après le titre (ancien scraper), 449 modifiés (dont 406 écrits en milliers x1000, 42 milliers rejetés)
### 3) Prix existants hors bornes [50,000 ; 10,000,000] TND : 567 invalidés
### 4) Prix récupérés via 'TND' : 0/609
### 5) Prix récupérés via 'DT' : 13/609

Prix manquants au final : 743 / 5077 (14.6%)

### 6) Gouvernorats normalisés. Non résolus : 585
### 6b) Gouvernorat déduit de la ville : 23/585

### 7a) Ville Mubawab récupérée depuis la page : 1/147

### 7) Ville récupérée depuis titre/description : 117/146 comblées
Villes toujours manquantes : 29
### 7b) Orthographe des villes normalisée : 299 -> 276 villes distinctes
### 7c) Conflits ville/gouvernorat corrigés : 504
### 7d) Villes rares (< 5) regroupées : 329 lignes -> 173 catégories de ville
### Gouvernorats rares (< 10) regroupés par région : 104 lignes (Béja, Gabès, Gafsa, Kasserine, Le Kef, Sidi Bouzid, Siliana, Tataouine, Tozeur, Zaghouan)
### Petits groupes de villes fusionnés par région : 39 lignes -> 169 catégories de ville

### 8) Surfaces hors bornes [30 ; 2500] m² : 90 invalidées

### 9a) nb_salles_bain : 1445 manquantes/aberrantes, 2 récupérées
### 9b) nb_chambres depuis titre S+N : 2207
### 9b) nb_chambres depuis scraper S+N : 2321
### 9b) nb_chambres depuis texte 'X chambres' : 210
### nb_chambres final : 4738/5077 renseignés (nb_pieces retiré des features : doublon de nb_chambres)
### Bornes nb_chambres [0 ; 10] : 0 invalidées
### Bornes nb_salles_bain [0 ; 8] : 0 invalidées
### Boolean ascenseur : 1073 inconnues
### Boolean parking : 1176 inconnues
### Boolean piscine : 1176 inconnues
### Boolean climatisation : 1176 inconnues
### Boolean chauffage_central : 1176 inconnues
### Boolean meuble : 1176 inconnues
### 13b) ascenseur (Tayara/Tecnocasa, texte libre) : 493 oui, 83 non, 3941 non mentionné
### 13b) parking (Tayara/Tecnocasa, texte libre) : 1854 oui, 8 non, 2758 non mentionné
### 13b) piscine (Tayara/Tecnocasa, texte libre) : 511 oui, 1 non, 4108 non mentionné
### 13b) climatisation (Tayara/Tecnocasa, texte libre) : 984 oui, 0 non, 3636 non mentionné
### 13b) chauffage_central (Tayara/Tecnocasa, texte libre) : 1052 oui, 0 non, 3568 non mentionné
### 13b) meuble (Tayara/Tecnocasa, texte libre) : 419 oui, 3 non, 4198 non mentionné

### Étage numérique (etage_num) : 1309/5077 connus

### 12) prix_m2 hors bornes [300 ; 15000] : 23 valeurs (20 trop bas, 3 trop hauts)
### 12b) Prix factices (1 111 000, 1 234 567...) : 10 invalidés
### 13) Outliers statistiques prix_m2 (IQR x2.5) détectés : 25

### 14) Prix hors bornes finales [50,000 ; 10,000,000] : 0

### 15) Doublons de contenu potentiels : 221 lignes
### Doublons de contenu supprimés : 126
### 15b) Même bien (gouvernorat+type+prix+surface, chambres/ville compatibles) : 107 doublons supprimés (dont 41 inter-sites)
### Groupes 'groupe_bien' partagés (unités d'un même projet) : 336 lignes, 163 groupes

### Train-ready : 4102/4844 lignes avec prix_dt valide

## Dataset final : 4844 lignes (88.2% du brut original)

### Valeurs manquantes restantes :
id                       0.0
groupe_bien              0.0
source                   0.0
type_transaction         0.0
type_bien                0.0
region                   0.0
gouvernorat              1.2
ville_original           0.6
ville                    1.3
prix_dt_original         3.0
prix_dt                 15.3
prix_m2                 19.3
outlier_prix_m2          0.0
surface_m2               5.5
nb_pieces_original      10.1
nb_chambres_original     6.0
nb_chambres              6.9
nb_salles_bain          28.8
etage_original          55.5
etage                    0.0
etage_num               73.6
ascenseur               77.3
parking                 54.5
piscine                 80.4
climatisation           71.2
chauffage_central       69.5
meuble                  82.6

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