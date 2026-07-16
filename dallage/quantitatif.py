"""Calculs quantitatifs (nombre de carreaux, surface, chutes, pertes)."""
from dataclasses import dataclass
from typing import List, Dict

from .geometry import ROOM_W, ROOM_H, FORMATS
from .layout_engine import Tile


@dataclass
class Quantitatif:
    counts: Dict[str, int]
    n_cuts: int
    surface_totale_m2: float
    surface_carreaux_posee_m2: float  # somme des surfaces nominales achetées
    chutes_m2: float
    taux_perte_pct: float
    a_commander: Dict[str, int]  # avec marge de sécurité


def compute_quantitatif(tiles: List[Tile], marge_pct: float = 8.0) -> Quantitatif:
    counts = {fmt: 0 for fmt in FORMATS}
    for t in tiles:
        counts[t.fmt] = counts.get(t.fmt, 0) + 1

    n_cuts = sum(1 for t in tiles if t.is_cut)
    surface_totale = (ROOM_W * ROOM_H) / 10000.0

    # Surface de carreaux réellement nécessaire en tenant compte du fait
    # qu'un carreau découpé consomme quand même un carreau entier à l'achat.
    surface_achat = sum((t.base_w * t.base_h) / 10000.0 for t in tiles)
    surface_posee = sum((t.w * t.h) / 10000.0 for t in tiles)
    chutes = surface_achat - surface_posee

    taux_perte = (chutes / surface_achat * 100.0) if surface_achat else 0.0

    a_commander = {}
    for fmt, n in counts.items():
        a_commander[fmt] = int((n * (1 + marge_pct / 100.0)) + 0.999)  # arrondi sup.

    return Quantitatif(
        counts=counts,
        n_cuts=n_cuts,
        surface_totale_m2=round(surface_totale, 2),
        surface_carreaux_posee_m2=round(surface_achat, 2),
        chutes_m2=round(chutes, 3),
        taux_perte_pct=round(taux_perte, 1),
        a_commander=a_commander,
    )
