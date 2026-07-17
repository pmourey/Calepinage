Dallage — éditeur de calepinage (minimal)

Installation

1. Créer et activer un environnement virtuel Python 3.11+ :
   python -m venv .venv
   source .venv/bin/activate   # macOS / Linux
   .venv\Scripts\activate     # Windows
2. Installer les dépendances :
   pip install -r requirements.txt

Commandes rapides

- Éditeur interactif : .venv/bin/python editor.py
- Génération batch : .venv/bin/python generate_all.py
- Viewer (visualiser un projet) : .venv/bin/python viewer.py

Sorties produites

- projects/<nom>/<nom>.json — données canoniques
- Exports images/texte associés : <nom>_1_plan.png, <nom>_2_pose.png, <nom>_4_decoupes.png, <nom>_5_vue3d.png, <nom>_6_fiche_carreleur.md
- generate_all.py écrit les mêmes fichiers dans output/ et crée output/description.md

Contribuer — Ajouter un format

- Modifier dallage/geometry.py : mettre à jour COLORS, FORMATS et all_pieces().
- Relancer editor.py ou generate_all.py pour voir la palette et tester.

Fichiers principaux

- editor.py, generate_all.py, viewer.py (entrypoints)
- dallage/: geometry.py, layout_engine.py, render.py, quantitatif.py

Licences / Issues

- Projet personnel. Pour bugs ou améliorations, ouvrir une issue et fournir un projet JSON de test.
