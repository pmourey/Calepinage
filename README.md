Dallage — Éditeur de carreaux

Résumé

Dallage est un petit éditeur de tuiles (carreaux) basé sur Pygame permettant de créer, charger, modifier et exporter des projets de dalles. Les projets sont stockés dans le répertoire projects/ sous la forme canonique projects/<nom>/<nom>.json (et .png). L'ancien agencement flat projects/<nom>.json n'est plus pris en charge.

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
