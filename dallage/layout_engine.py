"""Moteur de génération des plans de calepinage — générique.

Ce module ne connaît plus de tailles de carreaux "en dur" : il se base
entièrement sur `dallage.geometry.FORMATS`. Si vous changez les formats
disponibles dans geometry.py, ce moteur (et donc generate_all.py) s'adapte
automatiquement.

Principe général (identique pour les 4 propositions, seules les règles de
choix changent) :
  1. La hauteur totale de la pièce est découpée en "bandes" horizontales.
     La hauteur de chaque bande correspond à l'une des dimensions ("modules")
     utilisées par au moins un format (ex: 30 et 60 cm). Si la somme dépasse
     la hauteur disponible, la dernière bande est recoupée (découpe basse,
     groupée en un seul bandeau).
  2. Chaque bande a une "famille" (= sa hauteur nominale). Les carreaux
     utilisables dans cette famille sont toutes les orientations de format
     dont la hauteur correspond à cette valeur (ex : bande de hauteur 60 ->
     carreau 60x60, ou 30x60 posé Vertical).
  3. Chaque bande est remplie de gauche à droite. Un décalage (offset)
     éventuel en début de bande crée une découpe groupée à gauche, et si la
     largeur restante ne permet plus de poser un carreau entier, une
     découpe groupée est créée à droite. Les découpes sont donc toujours
     en périphérie (haut/bas, gauche/droite), jamais au milieu du dallage.

La proposition "bandes" (irrégulières) applique le même principe mais en
colonnes verticales (transposition), ce qui change l'orientation du
mouvement visuel.
"""
import random
from dataclasses import dataclass
from typing import List, Optional

from .geometry import ROOM_W, ROOM_H, families_by_height, module_sizes


@dataclass
class Tile:
    id: int
    x: float          # position (cm) coin haut-gauche
    y: float
    w: float           # largeur réellement posée (peut être < base_w si découpe)
    h: float
    fmt: str            # nom du format (clé de geometry.FORMATS)
    orientation: Optional[str]  # 'H' | 'V' | None
    base_w: float       # dimension nominale du carreau (avant découpe éventuelle)
    base_h: float
    is_cut: bool
    row: int
    col: int

    @property
    def cut_w(self):
        return round(self.base_w - self.w, 1)

    @property
    def cut_h(self):
        return round(self.base_h - self.h, 1)


def _find_piece(by_height, height, width):
    """Trouve (fmt, orientation) pour une bande de hauteur donnée et une
    largeur de carreau donnée."""
    for w, fmt, orient in by_height[height]:
        if w == width:
            return fmt, orient
    # à défaut (ne devrait pas arriver), on prend la première pièce dispo
    w, fmt, orient = by_height[height][0]
    return fmt, orient


def _make_tile(by_height, tile_id, x, y, actual_w, actual_h, base_w, base_h,
               family_h, row, col):
    fmt, orient = _find_piece(by_height, family_h, base_w)
    is_cut = (actual_w < base_w - 1e-6) or (actual_h < base_h - 1e-6)
    return Tile(tile_id, x, y, actual_w, actual_h, fmt, orient, base_w, base_h,
                is_cut, row, col)


def _closing_size(remaining, modules):
    """Choisit, parmi les tailles disponibles, celle qui minimise la chute
    pour clore une bande/ligne dont il ne reste que `remaining` cm : la plus
    petite taille >= remaining si elle existe, sinon la plus grande taille
    disponible (elle sera alors recoupée)."""
    candidates = [m for m in modules if m >= remaining - 1e-6]
    if candidates:
        return min(candidates)
    return max(modules)


def _bands_heights(pattern, rng, room_h, modules):
    """Retourne la liste des (base_h, actual_h) pour chaque bande."""
    bands = []
    y = 0.0
    idx = 0
    max_module = max(modules)
    while y < room_h - 1e-6:
        remaining = room_h - y
        if remaining <= max_module + 1e-6:
            # Bande de clôture : on choisit le module qui minimise la chute.
            base_h = _closing_size(remaining, modules)
        elif pattern == "semi":
            big = max(modules)
            rest = [m for m in modules if m != big]
            cycle = [big, big] + rest if rest else [big]
            base_h = cycle[idx % len(cycle)]
        elif pattern == "romain":
            cycle = sorted(modules, reverse=True)
            base_h = cycle[idx % len(cycle)]
        else:  # contemporain / bandes
            weights = [1.3 if m == max(modules) else 1.0 for m in modules]
            base_h = rng.choices(modules, weights=weights)[0]
        actual_h = min(base_h, remaining)
        bands.append((base_h, actual_h))
        y += actual_h
        idx += 1
    return bands


def _row_offset(pattern, rng, row_idx, family_h, modules):
    """Décalage (cm) en tête de bande pour désaligner les joints verticaux."""
    small = min(modules)
    if pattern == "contemporain":
        return rng.choice([0, 0, small / 2, family_h / 2, small])
    if pattern == "semi":
        return (family_h / 2) if row_idx % 2 == 1 else 0
    if pattern == "romain":
        return rng.choice([0, small / 3, small * 2 / 3, small / 2])
    return 0


def _fill_row(tiles, tile_id, pattern, rng, row_idx, y0, base_h, actual_h,
              family_h, room_w, by_height, modules):
    x = 0.0
    col = 0
    row_is_cut_h = actual_h < base_h - 1e-6
    allowed_widths = sorted({w for w, _, _ in by_height[family_h]})

    offset = _row_offset(pattern, rng, row_idx, family_h, modules)
    offset = min(offset, room_w)
    if offset > 1e-6:
        small = min(allowed_widths)
        t = _make_tile(by_height, tile_id, 0, y0, offset, actual_h, small,
                        base_h, family_h, row_idx, col)
        t.is_cut = True
        tiles.append(t)
        tile_id += 1
        col += 1
        x = offset

    while x < room_w - 1e-6:
        remaining = room_w - x
        max_w = max(allowed_widths)

        if remaining <= max_w + 1e-6:
            # Dernier carreau de la bande : on choisit la largeur qui
            # minimise la chute (découpe groupée en bord droit).
            base_w = _closing_size(remaining, allowed_widths)
        elif pattern == "semi":
            sorted_w = sorted(allowed_widths, reverse=True)
            base_w = sorted_w[col % len(sorted_w)]
        elif pattern == "romain":
            # majorité du petit format, grand format ponctuel (esprit pierre)
            weights = [0.3 if w == max_w else 0.7 for w in allowed_widths]
            base_w = rng.choices(allowed_widths, weights=weights)[0]
        else:  # contemporain / bandes
            if col == 0 and family_h == max(modules):
                base_w = max_w  # premier carreau = "ancrage" (plus grand format)
            else:
                weights = [1.0 if w == max_w else 1.1 for w in allowed_widths]
                base_w = rng.choices(allowed_widths, weights=weights)[0]

        actual_w = min(base_w, remaining)
        t = _make_tile(by_height, tile_id, x, y0, actual_w, actual_h, base_w,
                       base_h, family_h, row_idx, col)
        if row_is_cut_h:
            t.is_cut = True
        tiles.append(t)
        tile_id += 1
        x += actual_w
        col += 1
    return tile_id


def generate_layout(pattern: str, seed: int = 0, room_w: float = ROOM_W,
                     room_h: float = ROOM_H) -> List[Tile]:
    """Génère la liste des carreaux pour l'une des 4 propositions.

    pattern in {"contemporain", "semi", "bandes", "romain"}
    """
    rng = random.Random(seed)
    by_height = families_by_height()
    modules = module_sizes()

    if pattern == "bandes":
        # Transposition : on calepine en colonnes verticales puis on
        # échange x/y, w/h pour obtenir des bandes qui "descendent"
        # (mouvement + changement d'orientation fréquent).
        transposed = generate_layout("contemporain", seed=seed, room_w=room_h,
                                      room_h=room_w)
        tiles = []
        for t in transposed:
            tiles.append(Tile(t.id, t.y, t.x, t.h, t.w, t.fmt,
                               ("H" if t.orientation == "V" else
                                "V" if t.orientation == "H" else None),
                               t.base_h, t.base_w, t.is_cut, t.col, t.row))
        return tiles

    bands = _bands_heights(pattern, rng, room_h, modules)
    tiles: List[Tile] = []
    tile_id = 1
    y = 0.0
    for row_idx, (base_h, actual_h) in enumerate(bands):
        family_h = base_h
        tile_id = _fill_row(tiles, tile_id, pattern, rng, row_idx, y, base_h,
                             actual_h, family_h, room_w, by_height, modules)
        y += actual_h
    return tiles


PATTERNS = {
    "contemporain": "Proposition 1 - Opus contemporain",
    "semi": "Proposition 2 - Opus semi-aléatoire",
    "bandes": "Proposition 3 - Bandes irrégulières contemporaines",
    "romain": "Proposition 4 - Opus romain revisité",
}

SEEDS = {
    "contemporain": 42,
    "semi": 7,
    "bandes": 123,
    "romain": 2024,
}
