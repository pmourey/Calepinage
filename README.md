Dallage — Éditeur de carreaux

Résumé

Dallage est un petit éditeur de tuiles (carreaux) basé sur Pygame permettant de créer, charger, modifier et exporter des projets de dalles. Les projets sont stockés dans le répertoire projects/ sous la forme canonique projects/<nom>/<nom>.json et projects/<nom>/<nom>_1_plan.png (plusieurs exports associés). 

Structure des sorties

- Canonical project data: projects/<nom>/<nom>.json (source unique de vérité pour l'éditeur)
- Exports produits lors de la sauvegarde ou de l'export :
  - <nom>_1_plan.png — plan de pose visuel
  - <nom>_2_pose.png — tableau / aperçu de pose
  - <nom>_4_decoupes.png — vues des découpes
  - <nom>_5_vue3d.png — rendu 3D simplifié
  - <nom>_6_fiche_carreleur.md — fiche carreleur et quantitatif

generate_all.py

- Génère plusieurs propositions automatiques de calepinage dans output/. Pour chaque motif (clé):
  - {key}_1_plan.png, {key}_2_pose.png, {key}_4_decoupes.png, {key}_5_vue3d.png, {key}_6_fiche_carreleur.md
  - {key}.json — données canoniques réutilisables
  - output/description.md — description des motifs générés

Notes

- Le format CSV n'est plus utilisé pour la persistance des projets. Le JSON canonique est le seul format de données.
- Pour signaler un bug ou demander une fonctionnalité, ouvrir une issue en joignant un exemple de projet JSON et les logs d'exécution.

---

Programmes et rôle

- generate_all.py : génération batch de propositions automatiques. Produit pour chaque motif dans output/ :
  - {key}_1_plan.png, {key}_2_pose.png, {key}_4_decoupes.png, {key}_5_vue3d.png, {key}_6_fiche_carreleur.md, {key}.json
  - output/description.md décrit les motifs générés.

- editor.py : interface Pygame pour créer/éditer manuellement des projets. La sauvegarde produit les fichiers standards dans projects/<nom>/ :
  - <nom>_1_plan.png, <nom>_2_pose.png, <nom>_4_decoupes.png, <nom>_5_vue3d.png, <nom>_6_fiche_carreleur.md, <nom>.json

Structure technique

Racine du projet (principaux éléments) :
- editor.py, generate_all.py — points d'entrée
- dallage/ — bibliothèque principale
  - geometry.py — définitions des formats, dimensions, palette (all_pieces)
  - layout_engine.py — algorithmes de génération automatique (PATTERNS, SEEDS)
  - render.py — fonctions de rendu : render_plan, render_cuts, render_pose_table_png, render_3d
  - quantitatif.py — calculs de quantités et métriques
- projects/ — projets utilisateur (projects/<nom>/...)
- output/ — sortie globale (generate_all, export sans projet)

Modifier geometry.py — ajouter/éditer des formats

Les éléments importants à définir dans geometry.py pour ajouter un nouveau format :
- FORMATS (optionnel) : liste des formats utilisés par les algos
- COLORS : mapping format -> couleur (hex) pour le rendu
- JOINT_MM, ROOM_W, ROOM_H : paramètres pièce/globaux
- all_pieces() : doit retourner la palette utilisée par l'éditeur ; format suggéré :
  [(fmt_name, width_cm, height_cm, default_orientation, color), ...]

Exemple minimal (à coller/modifier dans dallage/geometry.py) :

ROOM_W = 283.0
ROOM_H = 295.0
JOINT_MM = 5
FORMATS = [30, 50, 60]
COLORS = {30: "#f8f4e6", 50: "#e6e2d0", 60: "#dcd6c3"}

def all_pieces():
    return [
        ("30x30", 30, 30, "H", COLORS[30]),
        ("30x50", 30, 50, "H", COLORS[50]),
        ("60x60", 60, 60, "H", COLORS[60]),
    ]

Contribuer — Ajouter un format (pas-à-pas)

1. Ouvrir dallage/geometry.py
2. Ajouter la ligne correspondante dans the COLORS et/ou FORMATS si nécessaire.
3. Mettre à jour la fonction all_pieces() pour inclure un tuple pour le nouveau format, par exemple ("40x40", 40, 40, "H", COLORS[40]).
4. Si nécessaire, adapter layout_engine.PATTERNS ou ajouter un nouveau motif pour tirer parti du format.
5. Relancer :
   - Pour développement interactif : .venv/bin/python editor.py
   - Pour génération de propositions : .venv/bin/python generate_all.py
6. Vérifier la palette dans l'éditeur (colonne droite) et tester la sauvegarde/export.

Bonnes pratiques

- Garder les noms de formats cohérents (ex: "30x50"), et ne pas réutiliser la même clé de couleur pour deux formats différents.
- Faire une sauvegarde d'un projet test et vérifier projects/<nom>/<nom>.json et les exports générés.

---

Fin de la documentation d'introduction.

Fonctions principales

- Nouveau (Nouveau projet)
  - Crée un nouveau projet vide ; demande un nom et évite d'écraser sans confirmation.
- Ouvrir
  - Liste les projets existants (détecte les sous-dossiers contenant le fichier <nom>.json) et charge un projet.
  - Si le projet est modifié (dirty), propose de sauvegarder avant d'ouvrir un autre projet.
- Sauvegarder
  - Enregistre l'état du projet (JSON) dans projects/<nom>/<nom>.json et marque le projet comme non-modifié.
  - L'export (CSV/PNG) écrit désormais dans le dossier du projet si un projet est ouvert.
- Quitter
  - Propose de sauvegarder si des modifications non enregistrées existent.

Chargement JSON

- Le projet est chargé depuis le fichier JSON canonique projects/<nom>/<nom>.json.

Export

- Les images PNG générées vont dans projects/<nom>/ quand un projet ouvert est renseigné. Sinon, elles vont dans output/.
- Le fichier de données canonique est projects/<nom>/<nom>.json (ou output/<key>.json pour generate_all). Aucune sortie *_pose.json n'est produite.
- L'export marque le projet comme sauvegardé (dirty=False).

Interface & Raccourcis

- Menu vertical (dans la fenêtre Pygame) aligné à gauche, ordre vertical : Nouveau, Ouvrir, Sauvegarder, Quitter.
- Raccourcis clavier :
  - Nouveau: Cmd/Ctrl+N
  - Ouvrir: Cmd/Ctrl+O
  - Sauvegarder: Cmd/Ctrl+S
  - Quitter: Cmd/Ctrl+Q (ou Esc)

Notes techniques et limites

- Les menus natifs (Tkinter) ne sont pas utilisés. Une tentative d'exécuter Tkinter en arrière-plan a causé des crashs sur macOS; l'éditeur utilise donc le menu intégré Pygame. Pour un menu natif sûr, exécuter la partie UI native dans le thread principal ou via un processus séparé.
- Certains prints de debug ([DEBUG], [FRAME]) subsistent et peuvent être nettoyés avant publication.

Contribution

- Pour signaler un bug ou demander une fonctionnalité, ouvrir une issue avec un exemple de fichier CSV/JSON et les logs d'exécution.

Licence

- Projet personnel — adapter la licence selon vos besoins.
