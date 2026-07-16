"""Constantes géométriques du projet de dallage.

Ce fichier est la source centrale de configuration : ajouter, retirer ou
modifier un format dans FORMATS (et éventuellement sa couleur dans COLORS)
suffit pour que le moteur de calepinage (layout_engine.py / generate_all.py)
et l'éditeur interactif (editor.py) prennent en compte les nouveaux carreaux,
sans aucune autre modification de code.
"""

ROOM_W = 283.0   # largeur (cm)
ROOM_H = 295.0   # longueur (cm)

JOINT_MM = 6  # largeur de joint recommandée (mm)

# Formats de carreaux disponibles (cm) : {nom: (dimension_a, dimension_b)}
FORMATS = {
    "50x50": (50, 50),
    "30x50": (30, 50),
    "30x30": (30, 30),
}

_DEFAULT_PALETTE_COLORS = [
    "#d8c9a3", "#e9dcc0", "#c9b98f", "#b9a97e", "#eadfc4", "#cdbf9d",
]

COLORS = {
    "50x50": "#d8c9a3",   # beige soutenu (ancrage)
    "30x50": "#e9dcc0",   # beige clair
    "30x30": "#c9b98f",   # beige gris
    "cut": "#f2a6a6",     # rose : signalement d'une découpe
}


# Complète automatiquement les couleurs manquantes si un format est ajouté à
# FORMATS sans couleur dédiée dans COLORS.
for _i, _fmt in enumerate(FORMATS):
    COLORS.setdefault(_fmt, _DEFAULT_PALETTE_COLORS[_i % len(_DEFAULT_PALETTE_COLORS)])


def orientations_for(fmt):
    """Retourne les orientations valides d'un format sous la forme
    [(largeur, hauteur, orientation), ...].

    - Format carré (a == a)      -> une seule orientation, orientation=None.
    - Format rectangulaire (a!=b) -> deux orientations :
        'H' (à plat : la plus grande dimension est horizontale)
        'V' (debout : la plus grande dimension est verticale)
    """
    a, b = FORMATS[fmt]
    if a == b:
        return [(a, b, None)]
    long_side, short_side = max(a, b), min(a, b)
    return [(long_side, short_side, "H"), (short_side, long_side, "V")]


def all_pieces():
    """Retourne la liste de toutes les pièces posables (palette) :
    [(fmt, largeur, hauteur, orientation, couleur), ...]."""
    pieces = []
    for fmt in FORMATS:
        for w, h, orient in orientations_for(fmt):
            pieces.append((fmt, w, h, orient, COLORS[fmt]))
    return pieces


def families_by_height():
    """Regroupe les orientations par hauteur de bande, pour le moteur de
    calepinage : {hauteur: [(largeur, fmt, orientation), ...]}."""
    by_height = {}
    for fmt in FORMATS:
        for w, h, orient in orientations_for(fmt):
            by_height.setdefault(h, []).append((w, fmt, orient))
    return by_height


def module_sizes():
    """Ensemble trié des dimensions (cm) utilisées par au moins un format,
    c'est-à-dire les hauteurs de bandes possibles du moteur de calepinage."""
    return sorted(families_by_height().keys())

