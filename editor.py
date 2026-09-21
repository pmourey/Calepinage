"""Éditeur interactif de calepinage — pose des carreaux au drag & drop.

Lancer avec :  .venv/bin/python editor.py

Commandes :
  Glisser un carreau depuis la palette (à droite) -> le déposer sur la
  grille (l'entrée de garage, 283 x 295 cm).
  Cliquer-glisser un carreau déjà posé -> le déplacer.
  Clic droit sur un carreau -> le supprimer.
  R          : pivoter le carreau sélectionné (utile pour les 30x50)
  Suppr/BkSp : supprimer le carreau sélectionné
  G          : activer/désactiver l'aimantation à la grille (pas de 5 cm)
  C          : tout effacer
  S          : exporter le calepinage (PNG) dans output/
  Echap      : quitter
"""
import os
import sys

import pygame
import json

from dallage.geometry import ROOM_W, ROOM_H, COLORS, all_pieces
from dallage.render import render_plan, render_cuts, render_pose_table_png, render_3d
from dallage.quantitatif import compute_quantitatif

OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUT_DIR, exist_ok=True)

# custom pygame events for menu actions
MENU_OPEN = pygame.USEREVENT + 1
MENU_NEW = pygame.USEREVENT + 2
MENU_SAVE = pygame.USEREVENT + 3
MENU_QUIT = pygame.USEREVENT + 4

SCALE = 2.35  # pixels par cm
GRID_ORIGIN = (200, 40)  # position (px) du coin haut-gauche de la grille — déplacé vers la gauche pour réduire l'espace menu
SNAP_STEP = 5  # cm
EDGE_SNAP_TOL = 10  # cm : distance de "magnétisme" aux bords voisins / à la pièce
ND = 3       # nombre de décimales conservées pour toute coordonnée (cm)
EPS = 0.01   # tolérance (cm) pour les comparaisons de bords / chevauchements

# Palette construite dynamiquement à partir de dallage/geometry.py : ajouter,
# retirer ou modifier un format dans geometry.FORMATS suffit à mettre à jour
# l'éditeur (aucune taille n'est plus codée en dur ici).
# Default palette from geometry; per-project palette stored on the Editor instance
# PALETTE removed; instances use self.palette = all_pieces()


def R(v):
    """Arrondit une coordonnée (cm) à une précision fixe afin d'éliminer les
    dérives d'arrondi flottant qui s'accumulent au fil des déplacements."""
    return round(v, ND)


class PlacedTile:
    _next_id = 1

    def __init__(self, x, y, w, h, fmt, orientation, base_w=None, base_h=None, pattern_instance=None):
        self.id = PlacedTile._next_id
        PlacedTile._next_id += 1
        self.x, self.y, self.w, self.h = R(x), R(y), R(w), R(h)
        self.base_w = R(base_w) if base_w is not None else self.w
        self.base_h = R(base_h) if base_h is not None else self.h
        self.fmt = fmt
        self.orientation = orientation
        self.cut_sides = []  # sous-ensemble de {'left','right','top','bottom'}
        self.pattern_instance = pattern_instance  # optional id linking tile to a placed pattern

    def rect_cm(self):
        return (self.x, self.y, self.w, self.h)

    @property
    def is_cut(self):
        return self.w < self.base_w - EPS or self.h < self.base_h - EPS

    def rotate(self):
        self.w, self.h = self.h, self.w
        self.base_w, self.base_h = self.base_h, self.base_w
        if self.orientation == "H":
            self.orientation = "V"
        elif self.orientation == "V":
            self.orientation = "H"


def cm_to_px(x_cm, y_cm):
    return GRID_ORIGIN[0] + x_cm * SCALE, GRID_ORIGIN[1] + y_cm * SCALE


def px_to_cm(x_px, y_px):
    return (x_px - GRID_ORIGIN[0]) / SCALE, (y_px - GRID_ORIGIN[1]) / SCALE


def rects_overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw - EPS and ax + aw > bx + EPS and \
        ay < by + bh - EPS and ay + ah > by + EPS


def snap(v, step):
    return R(round(v / step) * step)


def snap_axis(raw, size, others_ranges, room_size):
    """Aimante une coordonnée (x ou y) soit à la grille, soit au bord d'une
    dalle voisine, soit au bord de la pièce - en choisissant l'accroche la
    plus proche dans une tolérance EDGE_SNAP_TOL, sinon le pas de grille."""
    candidates = []
    # bord de la pièce
    candidates.append((abs(raw - 0), 0.0))
    candidates.append((abs(raw - (room_size - size)), room_size - size))
    # bords des dalles voisines (accolement bord à bord)
    for (start, end) in others_ranges:
        candidates.append((abs(raw - start), start))       # aligné à gauche/haut
        candidates.append((abs(raw - end), end))            # accolé juste après
        candidates.append((abs(raw - (start - size)), start - size))  # accolé juste avant
        candidates.append((abs(raw - (end - size)), end - size))       # aligné à droite/bas
    candidates.sort(key=lambda c: c[0])
    if candidates and candidates[0][0] <= EDGE_SNAP_TOL:
        return R(candidates[0][1])
    return snap(raw, SNAP_STEP)


def compute_cut_sides(full_rect, clipped):
    fx, fy, fw, fh = full_rect
    cx, cy, cw, ch = clipped
    sides = []
    if cx > fx + EPS:
        sides.append("left")
    if cx + cw < fx + fw - EPS:
        sides.append("right")
    if cy > fy + EPS:
        sides.append("top")
    if cy + ch < fy + fh - EPS:
        sides.append("bottom")
    return sides


def clip_to_room(x, y, w, h, room_w=ROOM_W, room_h=ROOM_H):
    """Découpe (clippe) le rectangle demandé aux limites de la pièce.
    Retourne (cx, cy, cw, ch) ou None si entièrement hors zone."""
    x1, y1 = x + w, y + h
    cx0, cy0 = max(x, 0.0), max(y, 0.0)
    cx1, cy1 = min(x1, room_w), min(y1, room_h)
    if cx1 <= cx0 + EPS or cy1 <= cy0 + EPS:
        return None
    return (R(cx0), R(cy0), R(cx1 - cx0), R(cy1 - cy0))


class Editor:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Éditeur de calepinage - drag & drop")
        # ensure initial window is wide enough for grid + side panel
        room_w_px = int(ROOM_W * SCALE)
        min_width = GRID_ORIGIN[0] + room_w_px + 260
        self.win_w, self.win_h = max(980, min_width), 760
        self.screen = pygame.display.set_mode((self.win_w, self.win_h),
                                               pygame.RESIZABLE)
        self.font = pygame.font.SysFont("Arial", 15)
        self.font_small = pygame.font.SysFont("Arial", 12)
        self.font_bold = pygame.font.SysFont("Arial", 16, bold=True)
        self.clock = pygame.time.Clock()

        self.tiles = []  # PlacedTile list
        self.snap_on = True
        self.selected = None  # single selected PlacedTile
        self.selected_tiles = []  # multi-selection list
        # project-specific settings (set during new project or load)
        self.project_formats = None
        self.joint_mm = JOINT_MM if 'JOINT_MM' in globals() else 5
        self.joint_color = '#dcd6c3'  # default joint color (hex)
        self.palette = all_pieces()
        # patterns saved in project: list of {'name':..., 'tiles':[...]} where tiles are relative
        self.project_patterns = []
        self._next_pattern_instance = 1

        # état du drag
        self.dragging = None  # dict: kind='new'/'move'/'pattern', tile info, offset
        self.drag_valid = False

        # selection rectangle (ctrl+drag)
        self.select_rect = None  # (x0,y0,x1,y1) in pixels during drag

        self.message = ""
        self.message_timer = 0

        # change tracking
        self.dirty = False
        # menu buttons (populated on draw)
        self.menu_buttons = {}
        # native menu flag (disabled: using Pygame menu by default).
        # Previously attempted starting a Tk menu in a background thread which
        # caused crashes on macOS because Tk must run on the main thread.
        # Keep native menu disabled; use Pygame in-window menu instead.
        self.use_native_menu = False


    # ---------- palette ----------
    def palette_rects(self):
        """Retourne [(rect_px, palette_item)] pour zone de droite, disposés en grille."""
        items = []
        room_w_px = int(ROOM_W * SCALE)
        preferred_x = self.win_w - 210
        min_x = GRID_ORIGIN[0] + room_w_px + 20
        base_x = max(preferred_x, min_x)
        # grid layout to save vertical space
        cols = 2
        cell_w = 90
        cell_h = 80
        x0 = base_x - 10
        y0 = 90
        # expand palette to include both orientations for rectangular formats
        expanded = []
        for item in self.palette:
            fmt, w, h, orient, color = item
            # always include canonical orientation
            expanded.append((fmt, w, h, orient, color))
            # if rectangular (w != h) also include the rotated variant
            if abs(w - h) > EPS:
                # rotated orientation: swap w/h and invert orientation
                rot_orient = 'V' if orient == 'H' else 'H'
                expanded.append((fmt, h, w, rot_orient, color))

        for idx, item in enumerate(expanded):
            col = idx % cols
            row = idx // cols
            x = x0 + col * (cell_w + 12)
            y = y0 + row * (cell_h + 18)
            fmt, w, h, orient, color = item
            # represent tile size scaled for visual (cm -> px using SCALE)
            # compute display size preserving tile proportions (cm->px via SCALE)
            natural_w = w * SCALE
            natural_h = h * SCALE
            max_w = cell_w - 16
            max_h = cell_h - 28
            if natural_w <= 0 or natural_h <= 0:
                scale = 1.0
            else:
                scale = min(1.0, max_w / natural_w, max_h / natural_h)
            disp_w = max(8, int(natural_w * scale))
            disp_h = max(8, int(natural_h * scale))
            # center within cell
            rect = pygame.Rect(x + (cell_w - disp_w) // 2, y + 8 + (cell_h - 28 - disp_h) // 2, disp_w, disp_h)
            items.append((rect, item))
        return items

    def _palette_color(self, fmt: str) -> str:
        """Return color hex for a given format name from project palette or global COLORS."""
        # search project palette first
        for p in self.palette:
            if p[0] == fmt:
                return p[4]
        # fallback to global COLORS mapping if present
        try:
            return COLORS.get(fmt, '#cccccc')
        except Exception:
            return '#cccccc'

    # ---------- rendu ----------
    def draw_grid(self):
        room_w_px = ROOM_W * SCALE
        room_h_px = ROOM_H * SCALE
        ox, oy = GRID_ORIGIN
        surf = self.screen
        pygame.draw.rect(surf, (255, 255, 255), (ox, oy, room_w_px, room_h_px))
        step = SNAP_STEP * 2
        gx = 0
        # draw grid lines using joint color (convert hex to pygame.Color)
        try:
            joint_col = pygame.Color(self.joint_color)
        except Exception:
            joint_col = pygame.Color('#dcd6c3')
        while gx <= ROOM_W + 0.001:
            x_px = ox + gx * SCALE
            pygame.draw.line(surf, joint_col, (x_px, oy), (x_px, oy + room_h_px))
            gx += step
        gy = 0
        while gy <= ROOM_H + 0.001:
            y_px = oy + gy * SCALE
            pygame.draw.line(surf, joint_col, (ox, y_px), (ox + room_w_px, y_px))
            gy += step
        pygame.draw.rect(surf, (20, 20, 20), (ox, oy, room_w_px, room_h_px), 2)

        # cotes
        lbl = self.font.render(f"{ROOM_W:.0f} cm", True, (30, 30, 30))
        surf.blit(lbl, (ox + room_w_px / 2 - 25, oy - 24))
        lbl2 = self.font.render(f"{ROOM_H:.0f} cm", True, (30, 30, 30))
        lbl2 = pygame.transform.rotate(lbl2, 90)
        surf.blit(lbl2, (ox - 30, oy + room_h_px / 2 - 20))

    def draw_tile(self, rect_cm, color, selected=False, label=None, alpha=255,
                  cut_edges=None):
        x, y, w, h = rect_cm
        px, py = cm_to_px(x, y)
        pw, ph = w * SCALE, h * SCALE
        tile_surf = pygame.Surface((pw, ph), pygame.SRCALPHA)
        col = pygame.Color(color)
        col.a = alpha
        tile_surf.fill(col)
        # draw border using joint color for visible joints
        try:
            jcol = pygame.Color(self.joint_color)
            jcol.a = alpha
            border_col = (jcol.r, jcol.g, jcol.b, jcol.a)
        except Exception:
            border_col = (75, 63, 47, alpha)
        pygame.draw.rect(tile_surf, border_col, tile_surf.get_rect(), 2)
        if selected:
            pygame.draw.rect(tile_surf, (220, 30, 30, 255), tile_surf.get_rect(), 3)
        self.screen.blit(tile_surf, (px, py))
        if label:
            txt = self.font_small.render(label, True, (40, 35, 28))
            self.screen.blit(txt, (px + pw / 2 - txt.get_width() / 2,
                                    py + ph / 2 - txt.get_height() / 2))
        if cut_edges:
            for edge in cut_edges:
                if edge == "left":
                    a, b = (px, py), (px, py + ph)
                elif edge == "right":
                    a, b = (px + pw, py), (px + pw, py + ph)
                elif edge == "top":
                    a, b = (px, py), (px + pw, py)
                else:  # bottom
                    a, b = (px, py + ph), (px + pw, py + ph)
                pygame.draw.line(self.screen, (210, 20, 20), a, b, 4)

    def draw_palette(self):
        surf = self.screen
        # ensure palette is placed to the right of the grid to avoid overlap
        room_w_px = int(ROOM_W * SCALE)
        preferred_x = self.win_w - 210
        min_x = GRID_ORIGIN[0] + room_w_px + 20
        base_x = max(preferred_x, min_x)
        title = self.font_bold.render("PALETTE (glisser-déposer)", True, (30, 25, 20))
        surf.blit(title, (base_x - 10, 55))
        # show numbered badges for formats
        palette_index = {p[0]: i+1 for i, p in enumerate(self.palette)}
        for rect, item in self.palette_rects():
            fmt, w, h, orient, color = item
            pygame.draw.rect(surf, color, rect)
            pygame.draw.rect(surf, (75, 63, 47), rect, 2)
            label = f"{fmt}" + (f" {orient}" if orient else "")
            txt = self.font_small.render(label, True, (40, 35, 28))
            surf.blit(txt, (rect.centerx - txt.get_width() / 2,
                             rect.bottom + 3))
            # badge
            badge = str(palette_index.get(fmt, '?'))
            badge_s = self.font_small.render(badge, True, (255,255,255))
            pygame.draw.circle(surf, (30,30,30), (rect.left+10, rect.top+10), 10)
            surf.blit(badge_s, (rect.left+4, rect.top+2))

    def draw_side_info(self):
        surf = self.screen
        # align side info with the palette and ensure it is right of the grid
        room_w_px = int(ROOM_W * SCALE)
        preferred_x = self.win_w - 210
        min_x = GRID_ORIGIN[0] + room_w_px + 20
        base_x = max(preferred_x, min_x)
        # place quantitative section below the palette grid to avoid overlap
        # compute palette footprint
        cols = 2
        cell_h = 80
        y0 = 90
        rows = (len(self.palette) + cols - 1) // cols
        y = y0 + rows * (cell_h + 18) + 12
        # counts by format name from project palette
        counts = {p[0]: 0 for p in self.palette}
        for t in self.tiles:
            if t.fmt in counts:
                counts[t.fmt] += 1
            else:
                counts[t.fmt] = counts.get(t.fmt, 0) + 1
        surface_posee = sum(t.w * t.h for t in self.tiles) / 10000.0
        surface_totale = ROOM_W * ROOM_H / 10000.0
        # Build quantitative lines dynamically from the project palette
        lines = []
        lines.append(("QUANTITATIF (posé)", True))
        for fmt, w, h, orient, color in self.palette:
            lines.append((f"{fmt}: {counts.get(fmt,0)}", False))
        lines.append((f"Total : {len(self.tiles)}", False))
        lines.append((f"Dont découpées : {sum(1 for t in self.tiles if t.is_cut)}", False))
        lines.append(("", False))
        lines.append((f"Surface posée : {surface_posee:.2f} m2", False))
        lines.append((f"Surface totale : {surface_totale:.2f} m2", False))
        lines.append((f"Couverture : {100*surface_posee/surface_totale:.1f} %", False))
        lines.append(("", False))
        lines.append(("Aimant grille (G) :", False))
        lines.append(("ON" if self.snap_on else "OFF", False))
        for text, bold in lines:
            f = self.font_bold if bold else self.font
            surf.blit(f.render(text, True, (35, 30, 25)), (base_x - 10, y))
            y += 22

        # move help lines to bottom-left of the main window
        help_x = 12
        help_y = self.win_h - 140
        help_lines = [
            "Clic-glisser palette -> pose",
            "Clic-glisser carreau -> déplace",
            "Alt+clic -> sélectionner motif entier",
            "Suppr -> supprimer sélection/groupe",
            "R : pivoter sélection",
            "C : tout effacer   S : exporter",
        ]
        for i, line in enumerate(help_lines):
            surf.blit(self.font_small.render(line, True, (90, 85, 75)), (help_x, help_y + i * 18))

    def draw_message(self):
        if self.message and pygame.time.get_ticks() < self.message_timer:
            txt = self.font_bold.render(self.message, True, (20, 110, 20))
            self.screen.blit(txt, (20, self.win_h - 30))

    def set_message(self, text, duration_ms=2500):
        self.message = text
        self.message_timer = pygame.time.get_ticks() + duration_ms

    # ---------- interactions ----------
    def tile_at_pixel(self, px, py):
        x_cm, y_cm = px_to_cm(px, py)
        for t in reversed(self.tiles):
            if t.x <= x_cm <= t.x + t.w and t.y <= y_cm <= t.y + t.h:
                return t
        return None

    def handle_mousedown(self, event):
        mx, my = event.pos
        # ensure last_mouse_pos is initialized so previews use correct start position
        self.last_mouse_pos = (mx, my)
        # check menu buttons first (if any)
        if event.button == 1 and getattr(self, 'menu_buttons', None):
            for name, rect in self.menu_buttons.items():
                if rect.collidepoint(mx, my):
                    if name == 'Ouvrir':
                        self._menu_open()
                    elif name == 'Nouveau':
                        self._menu_new()
                    elif name == 'Sauvegarder':
                        self._menu_save()
                    elif name == 'Quitter':
                        # quit after confirmation
                        if self._menu_quit():
                            pygame.quit()
                            sys.exit(0)
                    return
        mods = pygame.key.get_mods()
        if event.button == 1:
            # palette click -> start new tile drag
            for rect, item in self.palette_rects():
                if rect.collidepoint(mx, my):
                    fmt, w, h, orient, color = item
                    self.dragging = {"kind": "new", "w": w, "h": h, "fmt": fmt,
                                      "orientation": orient, "color": color,
                                      "mouse": (mx, my)}
                    return
            # clicked on a tile?
            t = self.tile_at_pixel(mx, my)
            if t:
                # shift toggles multi-select
                if mods & pygame.KMOD_SHIFT:
                    if t in self.selected_tiles:
                        self.selected_tiles.remove(t)
                    else:
                        self.selected_tiles.append(t)
                else:
                    # normal click selects single tile
                    # if tile belongs to a pattern instance, select the whole instance and start pattern-move drag
                    if getattr(t, 'pattern_instance', None):
                        pid = t.pattern_instance
                        self.selected_tiles = [tt for tt in self.tiles if getattr(tt, 'pattern_instance', None) == pid]
                        self.selected = None
                        # prepare pattern-move: store start anchor (center) and raw mouse
                        xs = []
                        ys = []
                        for tt in self.selected_tiles:
                            px, py = cm_to_px(tt.x, tt.y)
                            xs.append(px)
                            ys.append(py)
                            xs.append(px + tt.w * SCALE)
                            ys.append(py + tt.h * SCALE)
                        if xs and ys:
                            minx, maxx = min(xs), max(xs)
                            miny, maxy = min(ys), max(ys)
                            center_px = (minx + maxx) / 2
                            center_py = (miny + maxy) / 2
                        else:
                            center_px, center_py = mx, my
                        start_raw = (mx, my)
                        start_center_cm = px_to_cm(center_px, center_py)
                        self.dragging = {'kind': 'move_pattern', 'pattern_instance': pid, 'tiles': list(self.selected_tiles), 'start_raw': start_raw, 'start_center_cm': start_center_cm}
                        return
                    # otherwise handle single-tile selection and move
                    self.selected = t
                    # prepare move drag with offset
                    x_cm, y_cm = px_to_cm(mx, my)
                    offset = (x_cm - t.x, y_cm - t.y)
                    # if the clicked tile is in selected_tiles, start move_group
                    if t in self.selected_tiles:
                        # build offsets per tile
                        offsets = {tt.id: (px_to_cm(mx, my)[0] - tt.x, px_to_cm(mx, my)[1] - tt.y) for tt in self.selected_tiles}
                        self.dragging = {"kind": "move_group", "tiles": list(self.selected_tiles), "orig": [(tt.x, tt.y, tt.w, tt.h, list(tt.cut_sides)) for tt in self.selected_tiles], "mouse": (mx, my), "offsets": offsets}
                    else:
                        self.dragging = {"kind": "move", "tile": t, "orig": (t.x, t.y, t.w, t.h, list(t.cut_sides)), "mouse": (mx, my), "offset": offset}
                return
            # empty area: if Ctrl pressed, start selection rectangle
            if mods & (pygame.KMOD_CTRL | pygame.KMOD_META):
                self.select_rect = (mx, my, mx, my)
                return
            # otherwise clear selection
            self.selected = None
            self.selected_tiles.clear()

    def compute_drag(self, mx, my):
        """Calcule le rectangle nominal, le rectangle recoupé (ou None si
        entièrement hors zone), sa validité (pas de chevauchement) et les
        côtés éventuellement recoupés."""
        d = self.dragging
        if d["kind"] == "new":
            w, h = d["w"], d["h"]
            exclude = None
            x_cm, y_cm = px_to_cm(mx, my)
            x_cm -= w / 2
            y_cm -= h / 2
        elif d.get("kind") == "pattern":
            # compute pattern bounding box and position it centered at the mouse
            pat = d.get("pattern")
            tiles = pat.get("tiles", []) if pat else []
            if tiles:
                min_dx = min(ti.get('dx', 0) for ti in tiles)
                min_dy = min(ti.get('dy', 0) for ti in tiles)
                max_x = max(ti.get('dx', 0) + ti.get('w', 0) for ti in tiles)
                max_y = max(ti.get('dy', 0) + ti.get('h', 0) for ti in tiles)
                w, h = max_x - min_dx, max_y - min_dy
            else:
                w, h = 0, 0
            exclude = None
            # apply stored mouse_offset (in pixels) so preview and placement align
            # use delta from start_raw/start_center if available for consistent placement
            start_raw = d.get('start_raw')
            start_center = d.get('start_center_px')
            # Prefer applying stored mouse_offset so the pattern center stays exactly under cursor
            off_px, off_py = d.get('mouse_offset', (0, 0))
            mouse_warped = d.get('mouse_warped', False)
            if mouse_warped or d.get('mouse_offset'):
                # use mouse position plus offset to compute center
                base_px = mx + off_px
                base_py = my + off_py
                try:
                    print(f"[DEBUG][pattern place] mx,my=({mx},{my}) using offset base_px={base_px} base_py={base_py} off=({off_px},{off_py}) start_raw={d.get('start_raw')}")
                except Exception:
                    pass
            elif start_raw and start_center:
                # compute movement delta in pixels since drag start
                cur_dx = mx - start_raw[0]
                cur_dy = my - start_raw[1]
                base_px = start_center[0] + cur_dx
                base_py = start_center[1] + cur_dy
                try:
                    print(f"[DEBUG][pattern place] mx,my=({mx},{my}) start_raw={start_raw} start_center_px={start_center} cur_dx={cur_dx} cur_dy={cur_dy} base_px={base_px} base_py={base_py}")
                except Exception:
                    pass
            else:
                base_px = mx
                base_py = my
            x_cm, y_cm = px_to_cm(base_px, base_py)
            # center pattern at mouse: subtract half size so mouse sits at pattern center
            x_cm -= w / 2
            y_cm -= h / 2
            # clamp so pattern origin stays within room bounds to avoid unintended full clipping
            x_cm = max(0.0, min(x_cm, ROOM_W - w))
            y_cm = max(0.0, min(y_cm, ROOM_H - h))
        else:
            t = d.get("tile")
            if t is None:
                # fallback to treating as new
                x_cm, y_cm = px_to_cm(mx, my)
                w, h = 0, 0
                exclude = None
            else:
                w, h = t.base_w, t.base_h
                exclude = t
                x_cm, y_cm = px_to_cm(mx, my)
                off = d.get("offset", (0, 0))
                x_cm -= off[0]
                y_cm -= off[1]

        # For pattern drags, avoid snapping/edge magnetism to prevent rounding-induced misplacements
        do_snap = self.snap_on and d.get('kind') != 'pattern'
        if do_snap:
            others_x = [(o.x, o.x + o.w) for o in self.tiles if o is not exclude]
            others_y = [(o.y, o.y + o.h) for o in self.tiles if o is not exclude]
            x_cm = snap_axis(x_cm, w, others_x, ROOM_W)
            y_cm = snap_axis(y_cm, h, others_y, ROOM_H)

        full_rect = (x_cm, y_cm, w, h)
        clipped = clip_to_room(*full_rect)
        if clipped is None:
            return full_rect, None, False, []

        other_tiles = [o for o in self.tiles if o is not exclude]
        overlap = any(rects_overlap(clipped, o.rect_cm()) for o in other_tiles)
        cut_sides = compute_cut_sides(full_rect, clipped) if not overlap else []
        return full_rect, clipped, (not overlap), cut_sides

    def handle_mouseup(self, event):
        mx, my = event.pos
        # finish selection rectangle if any
        if self.select_rect:
            x0, y0, x1, y1 = self.select_rect
            rx0, rx1 = sorted((x0, x1))
            ry0, ry1 = sorted((y0, y1))
            # select tiles whose pixel rect intersects selection
            sel = []
            for t in self.tiles:
                px, py = cm_to_px(t.x, t.y)
                pw, ph = t.w * SCALE, t.h * SCALE
                if not (px+pw < rx0 or px > rx1 or py+ph < ry0 or py > ry1):
                    sel.append(t)
            self.selected_tiles = sel
            self.select_rect = None
            return

        if not self.dragging or event.button != 1:
            return
        d = self.dragging
        full_rect, clipped, valid, cut_sides = self.compute_drag(mx, my)

        if d["kind"] == "new":
            if valid:
                nt = PlacedTile(clipped[0], clipped[1], clipped[2], clipped[3],
                                 d["fmt"], d["orientation"],
                                 base_w=full_rect[2], base_h=full_rect[3])
                nt.cut_sides = cut_sides
                self.tiles.append(nt)
                self.selected = nt
                self.dirty = True
            else:
                self.set_message("Dépôt invalide (hors zone ou chevauchement)")
        elif d["kind"] == "move":
            t = d.get("tile")
            if t is None:
                # nothing to move
                self.set_message('Aucun tile à déplacer')
            else:
                if valid:
                    t.x, t.y, t.w, t.h = clipped
                    t.cut_sides = cut_sides
                    self.dirty = True
                else:
                    t.x, t.y, t.w, t.h = d["orig"][:4]
                    t.cut_sides = d["orig"][4]
                    self.set_message("Déplacement invalide (hors zone ou chevauchement)")
        elif d["kind"] == "move_group":
            # move multiple tiles by the delta between mouse orig and current
            mx0, my0 = d['mouse']
            x0_cm, y0_cm = px_to_cm(mx0, my0)
            x1_cm, y1_cm = px_to_cm(mx, my)
            dx = x1_cm - x0_cm
            dy = y1_cm - y0_cm
            # apply movement and check overlaps/clipping
            new_positions = []
            valid_group = True
            for (ox, oy, ow, oh, ocuts), tt in zip(d['orig'], d['tiles']):
                nx, ny = R(ox + dx), R(oy + dy)
                clip = clip_to_room(nx, ny, ow, oh)
                if clip is None:
                    # fully outside -> invalid
                    valid_group = False
                    break
                cx, cy, cw, ch = clip
                new_positions.append((tt, (cx, cy, cw, ch), compute_cut_sides((nx, ny, ow, oh), (cx, cy, cw, ch))))
            if valid_group and not any(any(rects_overlap(pos[1], o.rect_cm()) for o in self.tiles if o not in [p[0] for p in new_positions]) for pos in new_positions):
                # commit
                for tt, rect, cuts in new_positions:
                    tt.x, tt.y, tt.w, tt.h = rect
                    tt.cut_sides = cuts
                self.dirty = True
            else:
                self.set_message('Déplacement de groupe invalide (chevauchement ou hors zone)')
        elif d.get('kind') == 'move_pattern':
            # reposition an existing pattern instance so its CENTER matches the preview center at release
            tiles = d.get('tiles', [])
            # compute original pattern bbox center in cm
            xs = []
            ys = []
            for tt in tiles:
                xs.append(tt.x)
                ys.append(tt.y)
                xs.append(tt.x + tt.w)
                ys.append(tt.y + tt.h)
            if xs and ys:
                minx, maxx = min(xs), max(xs)
                miny, maxy = min(ys), max(ys)
                orig_center_x = (minx + maxx) / 2
                orig_center_y = (miny + maxy) / 2
            else:
                orig_center_x, orig_center_y = 0, 0
            # compute desired center at release (same logic as preview)
            start_raw = d.get('start_raw')
            start_center_cm = d.get('start_center_cm')
            if start_raw and start_center_cm:
                dx_cm = (mx - start_raw[0]) / SCALE
                dy_cm = (my - start_raw[1]) / SCALE
                center_x_cm = start_center_cm[0] + dx_cm
                center_y_cm = start_center_cm[1] + dy_cm
            else:
                off = d.get('mouse_offset', (0, 0))
                if d.get('mouse_warped'):
                    center_px = mx + off[0]
                    center_py = my + off[1]
                else:
                    center_px = mx
                    center_py = my
                center_x_cm, center_y_cm = px_to_cm(center_px, center_py)
            # compute delta to move tiles
            delta_x = center_x_cm - orig_center_x
            delta_y = center_y_cm - orig_center_y
            new_positions = []
            for tt in tiles:
                nx, ny = R(tt.x + delta_x), R(tt.y + delta_y)
                clip = clip_to_room(nx, ny, tt.w, tt.h)
                if clip is None:
                    # invalid move
                    self.set_message('Repositionnement invalide (hors zone)')
                    new_positions = None
                    break
                cx, cy, cw, ch = clip
                new_positions.append((tt, (cx, cy, cw, ch), compute_cut_sides((nx, ny, tt.w, tt.h), (cx, cy, cw, ch))))
            if new_positions is None:
                pass
            elif any(any(rects_overlap(pos[1], o.rect_cm()) for o in self.tiles if o not in tiles) for pos in new_positions):
                self.set_message('Repositionnement invalide (chevauchement)')
            else:
                for tt, rect, cuts in new_positions:
                    tt.x, tt.y, tt.w, tt.h = rect
                    tt.cut_sides = cuts
                self.dirty = True
        elif d.get("kind") == "pattern":
            # place pattern at offset with clipping & cut sides
            pat = d["pattern"]
            # compute pattern bounding box (w,h) from tiles
            tiles = pat.get('tiles', []) if pat else []
            if tiles:
                min_dx = min(ti.get('dx', 0) for ti in tiles)
                min_dy = min(ti.get('dy', 0) for ti in tiles)
                max_x = max(ti.get('dx', 0) + ti.get('w', 0) for ti in tiles)
                max_y = max(ti.get('dy', 0) + ti.get('h', 0) for ti in tiles)
                w, h = max_x - min_dx, max_y - min_dy
            else:
                w, h = 0, 0

            # final placement: compute center based on current mouse so center at release matches preview
            # align placement calculation with preview: prefer deterministic mouse_offset
            off = d.get('mouse_offset', (0, 0))
            if d.get('mouse_warped') or off != (0, 0):
                center_px = mx + off[0]
                center_py = my + off[1]
                center_x_cm, center_y_cm = px_to_cm(center_px, center_py)
            elif d.get('start_raw') and d.get('start_center_cm'):
                start_raw = d.get('start_raw')
                start_center_cm = d.get('start_center_cm')
                dx_cm = (mx - start_raw[0]) / SCALE
                dy_cm = (my - start_raw[1]) / SCALE
                center_x_cm = start_center_cm[0] + dx_cm
                center_y_cm = start_center_cm[1] + dy_cm
            else:
                center_x_cm, center_y_cm = px_to_cm(mx, my)
            # convert center to top-left origin for placement
            base_x = center_x_cm - w / 2
            base_y = center_y_cm - h / 2
            # clamp so pattern origin stays within room bounds
            base_x = max(0.0, min(base_x, ROOM_W - w))
            base_y = max(0.0, min(base_y, ROOM_H - h))
            # DEBUG: log mouse and offset info to diagnose placement alignment
            try:
                # compute helpful diagnostics
                base_px_calc = base_x * SCALE + GRID_ORIGIN[0]
                base_py_calc = base_y * SCALE + GRID_ORIGIN[1]
                origin_x_cm = x_cm
                origin_y_cm = y_cm
                print(f"[DEBUG][pattern place] mouse_event=({mx},{my}) mouse_offset={d.get('mouse_offset')} base_px_calc={base_px_calc:.1f} base_py_calc={base_py_calc:.1f} origin_cm=({origin_x_cm:.3f},{origin_y_cm:.3f}) clipped_cm={clipped}")
            except Exception:
                pass
            placed_any = False
            pid = str(self._next_pattern_instance)
            for ti in pat["tiles"]:
                px = base_x + ti["dx"]
                py = base_y + ti["dy"]
                # clip to room
                clip = clip_to_room(px, py, ti["w"], ti["h"])
                if clip is None:
                    # skip tiles fully outside
                    continue
                cx, cy, cw, ch = clip
                nt = PlacedTile(cx, cy, cw, ch, ti["fmt"], ti.get("orientation"), base_w=ti.get("base_w"), base_h=ti.get("base_h"), pattern_instance=pid)
                nt.cut_sides = compute_cut_sides((px, py, ti["w"], ti["h"]), (cx, cy, cw, ch))
                # skip if overlaps existing
                if any(rects_overlap(nt.rect_cm(), o.rect_cm()) for o in self.tiles):
                    continue
                self.tiles.append(nt)
                placed_any = True
            if placed_any:
                # increment instance counter after successful placement to ensure unique ids
                self._next_pattern_instance += 1
                self.dirty = True
            else:
                self.set_message('Placement du motif annulé (aucune tuile placée)')
        self.dragging = None

    def handle_keydown(self, event):
        if event.key in (pygame.K_ESCAPE,):
            return False
        if event.key == pygame.K_r and self.selected:
            t = self.selected
            new_base_w, new_base_h = t.base_h, t.base_w
            full_rect = (t.x, t.y, new_base_w, new_base_h)
            clipped = clip_to_room(*full_rect)
            others = [o for o in self.tiles if o is not t]
            if clipped and not any(rects_overlap(clipped, o.rect_cm())
                                    for o in others):
                t.base_w, t.base_h = new_base_w, new_base_h
                t.x, t.y, t.w, t.h = clipped
                t.cut_sides = compute_cut_sides(full_rect, clipped)
                if t.orientation == "H":
                    t.orientation = "V"
                elif t.orientation == "V":
                    t.orientation = "H"
            else:
                self.set_message("Rotation impossible ici")
        elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            # delete single selection or entire selected_tiles group
            if self.selected and not self.selected_tiles:
                if self.selected in self.tiles:
                    self.tiles.remove(self.selected)
                    self.selected = None
                    self.dirty = True
            elif self.selected_tiles:
                for t in list(self.selected_tiles):
                    if t in self.tiles:
                        self.tiles.remove(t)
                self.selected = None
                self.selected_tiles.clear()
                self.dirty = True
        elif event.key == pygame.K_g:
            self.snap_on = not self.snap_on
        elif event.key == pygame.K_c:
            self.tiles.clear()
            self.selected = None
            self.dirty = True
        elif event.key == pygame.K_s:
            self.export()
        # shortcuts: Ctrl/Cmd+O, Ctrl/Cmd+N, Ctrl/Cmd+S
        mods = pygame.key.get_mods()
        if mods & (pygame.KMOD_CTRL | pygame.KMOD_META):
            if event.key == pygame.K_o:
                self._menu_open()
            elif event.key == pygame.K_n:
                self._menu_new()
            elif event.key == pygame.K_s:
                self._menu_save()
            # Ctrl+M -> save selected tiles as pattern
            elif event.key == pygame.K_m:
                if self.selected_tiles:
                    # create pattern with relative positions
                    min_x = min(t.x for t in self.selected_tiles)
                    min_y = min(t.y for t in self.selected_tiles)
                    pat_tiles = []
                    for t in self.selected_tiles:
                        pat_tiles.append({'fmt': t.fmt, 'orientation': t.orientation, 'dx': R(t.x - min_x), 'dy': R(t.y - min_y), 'w': t.w, 'h': t.h, 'base_w': t.base_w, 'base_h': t.base_h})
                    name = self._prompt_text('Nom du motif (laisser vide pour motif auto):', default=f'motif_{len(self.project_patterns)+1}')
                    if not name:
                        name = f'motif_{len(self.project_patterns)+1}'
                    self.project_patterns.append({'name': name, 'tiles': pat_tiles})
                    self.set_message(f"Motif '{name}' enregistré")
                    self.dirty = True
                else:
                    self.set_message('Aucune sélection pour créer un motif')
            # Ctrl+D -> duplicate pattern: show simple modal to choose
            elif event.key == pygame.K_d:
                if not self.project_patterns:
                    self.set_message('Aucun motif enregistré')
                else:
                    # choose pattern
                    items = [p['name'] for p in self.project_patterns]
                    # reuse select modal
                    sel = self._prompt_text('Choisir motif à dupliquer (nom):', default=items[0])
                    if not sel:
                        self.set_message('Duplication annulée')
                    else:
                        pat = None
                        for p in self.project_patterns:
                            if p['name'] == sel:
                                pat = p
                                break
                        if pat is None:
                            self.set_message('Motif introuvable')
                        else:
                            # start a pattern-drag: center the mouse on the pattern to avoid clipping crashes
                            mx, my = pygame.mouse.get_pos()
                            # compute pattern bounding box in cm from relative tile positions
                            tiles = pat.get('tiles', []) if pat else []
                            if tiles:
                                xs = []
                                ys = []
                                for t in tiles:
                                    dx = t.get('dx', 0)
                                    dy = t.get('dy', 0)
                                    w = t.get('w', t.get('base_w', 0))
                                    h = t.get('h', t.get('base_h', 0))
                                    xs.extend([dx, dx + w])
                                    ys.extend([dy, dy + h])
                                minx, maxx = min(xs), max(xs)
                                miny, maxy = min(ys), max(ys)
                                center_cm_x = (minx + maxx) / 2.0
                                center_cm_y = (miny + maxy) / 2.0
                                cx_px, cy_px = cm_to_px(center_cm_x, center_cm_y)
                                # set mouse to center so pattern is centered under cursor during drag
                                center_px = int(cx_px)
                                center_py = int(cy_px)
                                mouse_pos = (center_px, center_py)
                            else:
                                mouse_pos = (mx, my)
                                center_px, center_py = mx, my
                            # compute offset to apply to real mouse to center pattern under cursor
                            offset = (center_px - mx, center_py - my)
                            # DO NOT attempt to warp OS mouse (macOS may block); use deterministic offset instead
                            mouse_warped = False
                            # compute center position in cm from mouse + offset
                            x_cm, y_cm = px_to_cm(mx + offset[0], my + offset[1])
                            # DEBUG: log drag-start info
                            try:
                                print(f"[DEBUG][pattern start] mouse_raw=({mx},{my}) center_px=({center_px},{center_py}) offset={offset} mouse_warped={mouse_warped} center_cm=({center_cm_x:.2f},{center_cm_y:.2f})")
                            except Exception:
                                pass
                            # store both offset and whether warp succeeded; also store raw start mouse and anchor (top-left) in cm
                            start_anchor_cm = px_to_cm(mx, my)  # top-left anchor per user's choice
                            # store both center (cm & px) so preview and placement can use consistent keys
                            start_center_cm = (center_cm_x, center_cm_y) if tiles else px_to_cm(center_px, center_py)
                            start_center_px = (center_px, center_py)
                            self.dragging = {
                                'kind': 'pattern', 'pattern': pat, 'mouse': mouse_pos,
                                'mouse_offset': offset, 'mouse_warped': mouse_warped,
                                'start_raw': (mx, my), 'start_anchor_cm': start_anchor_cm,
                                'start_center_cm': start_center_cm, 'start_center_px': start_center_px
                            }
                            try:
                                print(f"[DEBUG][pattern start] start_raw=({mx},{my}) anchor_cm={start_anchor_cm} offset={offset} mouse_warped={mouse_warped}")
                                print(f"[DEBUG][pattern start] dragging={self.dragging}")
                            except Exception:
                                pass
                            self.set_message(f'Déplacer pour positionner le motif "{sel}" et cliquer')
        return True

    def export(self):
        """Export CSV + PNG into the project directory when possible.
        Also mark project as saved (dirty=False).
        """
        # determine filenames — if a current project exists, use its name
        base_name = getattr(self, 'current_project', None) or 'mon_calepinage'
        # Determine target paths: write into the project dir if current_project set
        if getattr(self, 'current_project', None):
            proj_dir = os.path.join(self._projects_dir(), self.current_project)
            os.makedirs(proj_dir, exist_ok=True)
            png_path = os.path.join(proj_dir, f"{base_name}.png")
            # export image path
            png_path = os.path.join(proj_dir, f"{base_name}.png")
        else:
            png_path = os.path.join(OUT_DIR, f"{base_name}.png")

        # export project JSON is handled by save_project(); do not write temporary pose JSON here

        room_w_px, room_h_px = int(ROOM_W * SCALE), int(ROOM_H * SCALE)
        snapshot = pygame.Surface((room_w_px, room_h_px))
        snapshot.fill((255, 255, 255))
        for t in self.tiles:
            x_px, y_px = t.x * SCALE, t.y * SCALE
            w_px, h_px = t.w * SCALE, t.h * SCALE
            r = pygame.Rect(x_px, y_px, w_px, h_px)
            # determine color from project palette or global COLORS
            col_hex = self._palette_color(t.fmt)
            pygame.draw.rect(snapshot, pygame.Color(col_hex), r)
            pygame.draw.rect(snapshot, (75, 63, 47), r, 2)
            for edge in t.cut_sides:
                if edge == "left":
                    a, b = (x_px, y_px), (x_px, y_px + h_px)
                elif edge == "right":
                    a, b = (x_px + w_px, y_px), (x_px + w_px, y_px + h_px)
                elif edge == "top":
                    a, b = (x_px, y_px), (x_px + w_px, y_px)
                else:
                    a, b = (x_px, y_px + h_px), (x_px + w_px, y_px + h_px)
                pygame.draw.line(snapshot, (210, 20, 20), a, b, 3)
        pygame.image.save(snapshot, png_path)

        n_cuts = sum(1 for t in self.tiles if t.is_cut)
        # mark saved
        self.dirty = False
        self.set_message(f"Exporté ({n_cuts} découpe(s)) : {png_path}")

        # proposer la sauvegarde du projet via dialogue pygame
        try:
            self._prompt_save_project()
        except Exception:
            # En cas d'erreur graphique (headless ou erreurs SDL), fallback console
            try:
                if getattr(self, 'current_project', None):
                    if input(f"Remplacer le projet '{self.current_project}' ? (o/N): ").lower().startswith('o'):
                        self.save_project(self.current_project)
                else:
                    name = input('Nom du projet à sauvegarder (ou vide pour annuler): ').strip()
                    if name:
                        if os.path.exists(os.path.join(self._projects_dir(), f"{name}.json")):
                            if input(f"Le projet {name} existe. Écraser ? (o/N): ").lower().startswith('o'):
                                self.save_project(name)
                        else:
                            self.save_project(name)
            except Exception:
                # si tout échoue, on n'insiste pas
                self.set_message('Sauvegarde non effectuée (mode non interactif)')

    # Persistence helpers
    def _projects_dir(self):
        # Use repository/script directory as base so IDE cwd doesn't hide projects
        base = os.path.dirname(__file__)
        d = os.path.join(base, "projects")
        os.makedirs(d, exist_ok=True)
        return d

    def list_projects(self):
        d = self._projects_dir()
        names = []
        for f in sorted(os.listdir(d)):
            full = os.path.join(d, f)
            # current canonical layout: projects/<name>/<name>.json
            if os.path.isdir(full) and os.path.exists(os.path.join(full, f"{f}.json")):
                names.append(f)
        return names

    def save_project(self, name: str):
        if not name:
            return False
        data = {
            'room_w': ROOM_W,
            'room_h': ROOM_H,
            'joint_mm': self.joint_mm,
            'joint_color': getattr(self, 'joint_color', '#dcd6c3'),
            'palette': [
                {'name': p[0], 'w': p[1], 'h': p[2], 'orientation': p[3], 'color': p[4]} for p in self.palette
            ],
            'patterns': self.project_patterns,
            'tiles': [
                {'id': t.id, 'x': t.x, 'y': t.y, 'w': t.w, 'h': t.h,
                 'fmt': t.fmt, 'orientation': t.orientation,
                 'base_w': t.base_w, 'base_h': t.base_h,
                 'cut_sides': list(t.cut_sides)} for t in self.tiles
            ]
        }
        # ensure per-project directory
        proj_dir = os.path.join(self._projects_dir(), name)
        os.makedirs(proj_dir, exist_ok=True)
        path = os.path.join(proj_dir, f"{name}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        # generate standard output files for editor projects: 1_plan, 2_pose, 4_decoupes, 5_vue3d, 6_fiche_carreleur
        # generate standard output files for editor projects: 1_plan, 2_pose, 4_decoupes, 5_vue3d, 6_fiche_carreleur
        # run each generation step independently to avoid one failing step stopping the rest
        # 1_plan.png
        try:
            palette_map = {p[0]: p[4] for p in self.palette}
            render_plan(self.tiles, name, os.path.join(proj_dir, f"{name}_1_plan.png"), joint_color=self.joint_color, palette_map=palette_map)
        except TypeError:
            # older render functions may not accept joint_color; fallback to call without
            try:
                render_plan(self.tiles, name, os.path.join(proj_dir, f"{name}_1_plan.png"))
            except Exception:
                pass
        except Exception:
            pass
        # 2_pose.png (visual pose table)
        try:
            render_pose_table_png(self.tiles, name, os.path.join(proj_dir, f"{name}_2_pose.png"), joint_color=self.joint_color, palette_map=palette_map)
        except TypeError:
            try:
                render_pose_table_png(self.tiles, name, os.path.join(proj_dir, f"{name}_2_pose.png"))
            except Exception:
                pass
        except Exception:
            pass
        # 4_decoupes.png
        try:
            render_cuts(self.tiles, name, os.path.join(proj_dir, f"{name}_4_decoupes.png"), joint_color=self.joint_color, palette_map=palette_map)
        except TypeError:
            try:
                render_cuts(self.tiles, name, os.path.join(proj_dir, f"{name}_4_decoupes.png"))
            except Exception:
                pass
        except Exception:
            pass
        # 5_vue3d.png
        try:
            render_3d(self.tiles, name, os.path.join(proj_dir, f"{name}_5_vue3d.png"), joint_color=self.joint_color, palette_map=palette_map)
        except TypeError:
            try:
                render_3d(self.tiles, name, os.path.join(proj_dir, f"{name}_5_vue3d.png"))
            except Exception:
                pass
        except Exception:
            pass
        # write canonical project JSON as <name>.json (include joint_color)
        # write canonical project JSON as <name>.json, include palette and joint settings
        try:
            with open(os.path.join(proj_dir, f"{name}.json"), 'w', encoding='utf-8') as pf:
                json.dump(data, pf, indent=2, ensure_ascii=False)
        except Exception:
            pass
        # 6_fiche_carreleur.md
        try:
            q = compute_quantitatif(self.tiles)
            # Only include formats defined in project palette
            tiles_total = sum(q.counts.values())
            quant_lines = []
            for p in self.palette:
                fmt_name = p[0]
                cnt = q.counts.get(fmt_name, 0)
                to_order = q.a_commander.get(fmt_name, 0)
                pct = round(cnt / sum(q.counts.values()) * 100, 2)
                quant_lines.append(f"- {fmt_name} cm : {cnt} - {pct} % (à commander : {to_order})")
            fiche_lines = [
                f"# Fiche carreleur — {name}",
                "",
                f"- Dimensions de l'entrée de garage : {ROOM_W:.0f} x {ROOM_H:.0f} cm",
                f"- Surface totale : {q.surface_totale_m2} m²",
                "",
                "## Quantitatif",
                *quant_lines,
                f"- Surface de carreaux à acheter : {q.surface_carreaux_posee_m2} m²",
                f"- Chutes : {q.chutes_m2} m²  (taux de perte {q.taux_perte_pct} %)",
                f"- Nombre de découpes : {q.n_cuts}",
            ]
            with open(os.path.join(proj_dir, f"{name}_6_fiche_carreleur.md"), 'w', encoding='utf-8') as ff:
                ff.write('\n'.join(fiche_lines))
        except Exception:
            pass
        self.current_project = name
        # mark saved
        self.dirty = False
        self.set_message(f"Projet sauvegardé : {name}")
        return True

    def load_project(self, name: str):
        d = self._projects_dir()
        # canonical layout only: projects/<name>/<name>.json
        path = os.path.join(d, name, f"{name}.json")
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # load project-level settings if present
            self.joint_mm = data.get('joint_mm', self.joint_mm)
            self.joint_color = data.get('joint_color', getattr(self, 'joint_color', '#dcd6c3'))
            pal = data.get('palette') or []
            if pal:
                self.palette = [(p.get('name'), p.get('w'), p.get('h'), p.get('orientation'), p.get('color')) for p in pal]
            # load patterns
            self.project_patterns = data.get('patterns', []) or []
            tiles_from_json = data.get('tiles', []) or []
            self.tiles.clear()
            for td in tiles_from_json:
                nt = PlacedTile(td['x'], td['y'], td['w'], td['h'], td['fmt'],
                                td.get('orientation'), base_w=td.get('base_w'),
                                base_h=td.get('base_h'), pattern_instance=td.get('pattern_instance'))
                nt.cut_sides = td.get('cut_sides', [])
                self.tiles.append(nt)
            # restore next pattern instance id to avoid collisions
            max_pid = 0
            for t in self.tiles:
                if getattr(t, 'pattern_instance', None):
                    try:
                        max_pid = max(max_pid, int(t.pattern_instance))
                    except Exception:
                        pass
            self._next_pattern_instance = max(self._next_pattern_instance, max_pid + 1)
            self.current_project = name
            # loaded from disk -> not dirty
            self.dirty = False
            self.set_message(f"Projet chargé (JSON) : {name}")
            return True
        return False

    # ---------- simple pygame text prompt (modal) ----------
    def _prompt_text(self, title: str, default: str = "") -> str | None:
        """Affiche un petit dialogue modal pour saisir un texte. Retourne None si annulé."""
        # create a small surface for modal
        font = pygame.font.SysFont(None, 24)
        clock = pygame.time.Clock()
        s_w, s_h = 520, 120
        win = pygame.Surface((s_w, s_h))
        input_text = default
        active = True
        while active:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return None
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return None
                    elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        return input_text.strip() or None
                    elif ev.key == pygame.K_BACKSPACE:
                        input_text = input_text[:-1]
                    else:
                        if ev.unicode and len(input_text) < 64:
                            input_text += ev.unicode
            # draw
            win.fill((240, 240, 240))
            pygame.draw.rect(win, (40, 40, 40), (0, 0, s_w, s_h), 2)
            lbl = font.render(title, True, (30, 30, 30))
            win.blit(lbl, (12, 8))
            inp_rect = pygame.Rect(12, 40, s_w - 24, 36)
            pygame.draw.rect(win, (255, 255, 255), inp_rect)
            txt = font.render(input_text, True, (10, 10, 10))
            win.blit(txt, (inp_rect.x + 6, inp_rect.y + 6))
            # blit over main screen centered
            sw, sh = self.screen.get_size()
            self.screen.blit(win, ((sw - s_w) // 2, (sh - s_h) // 2))
            pygame.display.flip()
            clock.tick(30)
        return None

    def _prompt_color_picker(self, title: str) -> str:
        """Affiche un modal simple avec quelques swatches de couleur et retourne un hex."""
        presets = ['#f8f4e6', '#e6e2d0', '#dcd6c3', '#c8bfb1', '#b0a89c', '#9aa395']
        font = pygame.font.SysFont(None, 20)
        clock = pygame.time.Clock()
        s_w, s_h = 400, 140
        win = pygame.Surface((s_w, s_h))
        selected = 0
        running = True
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return presets[0]
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return presets[0]
                    elif ev.key == pygame.K_RETURN:
                        return presets[selected]
                    elif ev.key == pygame.K_RIGHT:
                        selected = (selected + 1) % len(presets)
                    elif ev.key == pygame.K_LEFT:
                        selected = (selected - 1) % len(presets)
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    mx, my = ev.pos
                    sw_x = (self.screen.get_width() - s_w) // 2
                    sw_y = (self.screen.get_height() - s_h) // 2
                    rel_x = mx - sw_x
                    rel_y = my - sw_y
                    if 10 <= rel_y <= 60:
                        # click on swatch row
                        idx = rel_x // 60
                        if 0 <= idx < len(presets):
                            selected = idx
                    # confirm area
                    if 80 <= rel_y <= 110 and 140 <= rel_x <= 260:
                        return presets[selected]
            # draw
            win.fill((250, 250, 250))
            pygame.draw.rect(win, (10, 10, 10), (0, 0, s_w, s_h), 2)
            lbl = font.render(title + ' (← → pour naviguer, Entrée pour valider)', True, (20, 20, 20))
            win.blit(lbl, (10, 8))
            # swatches
            for i, c in enumerate(presets):
                x = 10 + i * 60
                pygame.draw.rect(win, pygame.Color(c), (x, 30, 50, 40))
                if i == selected:
                    pygame.draw.rect(win, (0, 0, 0), (x-2, 28, 54, 44), 2)
            # confirm button
            pygame.draw.rect(win, (200, 200, 200), (140, 80, 120, 30))
            cb = font.render('Valider', True, (10, 10, 10))
            win.blit(cb, (170, 86))
            # blit
            sw_x = (self.screen.get_width() - s_w) // 2
            sw_y = (self.screen.get_height() - s_h) // 2
            self.screen.blit(win, (sw_x, sw_y))
            pygame.display.flip()
            clock.tick(30)
        return presets[0]

    def _confirm(self, message: str) -> bool:
        """Simple confirmation modal: Enter = yes, Esc = no."""
        res = self._prompt_text(message + " (Entrée=oui, Echap=non)", default="")
        return res is not None

    def _select_project_modal(self) -> str | None:
        """Affiche une modal Pygame listant les projets existants et retourne
        le nom choisi (ou None si annulation). Retourne '__new__' si l'utilisateur
        choisit de créer un nouveau projet."""
        projects = self.list_projects()
        # Always provide a 'Nouveau projet' option at the top
        items = ["<Nouveau projet>"] + projects
        if len(items) == 1:
            # only 'Nouveau projet'
            return '__new__'
        font = self.font
        clock = self.clock
        per_item_h = 30
        padding = 12
        max_visible = 10
        total = len(items)
        visible = min(total, max_visible)
        s_w = 420
        s_h = padding * 2 + visible * per_item_h + 40
        win = pygame.Surface((s_w, s_h))
        selected = 0
        offset = 0
        running = True
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return None
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return None
                    elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if selected == 0:
                            return '__new__'
                        return items[selected]
                    elif ev.key == pygame.K_DOWN:
                        if selected < total - 1:
                            selected += 1
                            if selected >= offset + visible:
                                offset += 1
                    elif ev.key == pygame.K_UP:
                        if selected > 0:
                            selected -= 1
                            if selected < offset:
                                offset -= 1
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    mx, my = ev.pos
                    sw, sh = self.screen.get_size()
                    bx = (sw - s_w) // 2
                    by = (sh - s_h) // 2
                    if bx <= mx <= bx + s_w and by <= my <= by + s_h:
                        rel_y = my - by - padding - 20
                        if 0 <= rel_y < visible * per_item_h:
                            idx = offset + (rel_y // per_item_h)
                            if 0 <= idx < total:
                                if idx == 0:
                                    return '__new__'
                                return items[idx]
            # draw
            win.fill((245, 245, 245))
            pygame.draw.rect(win, (10, 10, 10), (0, 0, s_w, s_h), 2)
            title = font.render("Choisir un projet (Entrée=Nouveau, Échap=annuler)", True, (30, 30, 30))
            win.blit(title, (padding, 8))
            # list area
            y = padding + 28
            for i in range(offset, offset + visible):
                if i >= total:
                    break
                name = items[i]
                item_rect = pygame.Rect(padding, y - 4, s_w - padding * 2, per_item_h)
                if i == selected:
                    pygame.draw.rect(win, (200, 220, 240), item_rect)
                txt = font.render(name, True, (20, 20, 20))
                win.blit(txt, (padding + 6, y + 4))
                y += per_item_h
            # blit centered
            sw, sh = self.screen.get_size()
            self.screen.blit(win, ((sw - s_w) // 2, (sh - s_h) // 2))
            pygame.display.flip()
            clock.tick(30)
        return None

    def _menu_open(self):
        # ask save if dirty
        from editor_menu_helpers import _ask_save_if_dirty
        if not _ask_save_if_dirty(self):
            return
        projects = self.list_projects()
        if not projects:
            # create new
            self._menu_new()
            return
        selected = self._select_project_modal()
        if selected:
            if selected == '__new__':
                self._menu_new()
            else:
                self.load_project(selected)

    def _menu_new(self):
        from editor_menu_helpers import _ask_save_if_dirty
        if not _ask_save_if_dirty(self):
            return
        name = self._prompt_text('Nom du nouveau projet :', default='mon_calepinage')
        if not name:
            self.set_message('Création annulée')
            return
        # if exists, confirm selection/overwrite
        if name in self.list_projects():
            if self._confirm(f"Le projet '{name}' existe. Le sélectionner ?"):
                self.load_project(name)
                return
            else:
                self.set_message('Création annulée')
                return
        # ask project-level settings
        joint_s = self._prompt_text('Largeur de joint recommandée (mm) :', default=str(self.joint_mm))
        try:
            joint_val = float(joint_s) if joint_s else self.joint_mm
        except Exception:
            joint_val = self.joint_mm
        # joint color
        joint_color = self._prompt_color_picker('Choisir couleur pour les joints')
        # number of formats
        n_s = self._prompt_text('Nombre de formats de carreaux à définir :', default='2')
        try:
            n = max(1, int(n_s))
        except Exception:
            n = 2
        palette = []
        for i in range(n):
            fmt_name = self._prompt_text(f'Nom format #{i+1} (ex: 30x50) :', default=f'{30+i*10}x{30+i*10}')
            if not fmt_name:
                fmt_name = f'{30+i*10}x{30+i*10}'
            dim_s = self._prompt_text(f'Dimensions (LxH en cm) pour {fmt_name} (ex: 30x50) :', default='30x30')
            color = self._prompt_color_picker(f'Choisir couleur pour {fmt_name}')
            try:
                w_s, h_s = dim_s.lower().split('x')
                w = float(w_s)
                h = float(h_s)
            except Exception:
                w, h = 30.0, 30.0
            orientation = 'H' if w >= h else 'V'
            palette.append((fmt_name, w, h, orientation, color))
        # initialize empty state and save with project-specific palette and joint
        self.tiles.clear()
        self.current_project = name
        self.palette = palette
        self.joint_mm = joint_val
        self.joint_color = joint_color
        self.save_project(name)

    def _menu_save(self):
        if getattr(self, 'current_project', None):
            self.save_project(self.current_project)
        else:
            self._prompt_save_project()

    def _menu_quit(self) -> bool:
        from editor_menu_helpers import _ask_save_if_dirty
        if not _ask_save_if_dirty(self):
            return False
        return True

    def _prompt_save_project(self):
        """Après export, proposer de sauvegarder le projet (nom si absent).
        Si un projet du même nom existe, demander confirmation d'écrasement.
        Utilise l'UX Pygame (modal) pour tout interaction."""
        # if already have a project name, save directly
        if getattr(self, 'current_project', None):
            return self.save_project(self.current_project)

        # otherwise ask name and save
        name = self._prompt_text("Nom du projet à sauvegarder :", default="mon_calepinage")
        if not name:
            self.set_message("Sauvegarde annulée")
            return False
        path = os.path.join(self._projects_dir(), f"{name}.json")
        # if exists, confirm overwrite
        if os.path.exists(path):
            if not self._confirm(f"Le projet '{name}' existe déjà. Écraser ?"):
                self.set_message("Sauvegarde annulée")
                return False
        self.save_project(name)
        return True

    def _draw_menu(self):
        # vertical menu at left, below the title
        surf = self.screen
        base_x = 20
        base_y = 60  # start a bit lower than the title
        padding_y = 8
        buttons = ['Nouveau','Ouvrir','Sauvegarder','Quitter']
        self.menu_buttons.clear()
        max_w = 0
        # first compute max width
        for b in buttons:
            txt = self.font.render(b, True, (255,255,255))
            w = txt.get_width()+12
            if w > max_w:
                max_w = w
        h = 28
        y = base_y
        for b in buttons:
            rect = pygame.Rect(base_x, y, max_w, h)
            pygame.draw.rect(surf, (60,60,60), rect, border_radius=4)
            txt = self.font.render(b, True, (255,255,255))
            surf.blit(txt, (base_x+6, y+4))
            self.menu_buttons[b]=rect
            y += h + padding_y


    # ---------- boucle principale ----------
    def run(self):
        # If requested, ask to load a project on the first frame
        if getattr(self, 'ask_load_on_start', False):
            # clear the flag so we don't repeat
            self.ask_load_on_start = False
            projects = self.list_projects()
            if projects:
                selected = self._select_project_modal()
                if selected:
                    if selected == '__new__':
                        # delegate full new-project flow to existing helper which uses modals
                        self._menu_new()
                    else:
                                        # add debug log when loading
                                        print(f"[DEBUG] Loading project '{selected}' — listing files in projects dir: {os.listdir(self._projects_dir())}")
                                        loaded = self.load_project(selected)
                                        print(f"[DEBUG] load_project returned: {loaded}; tiles count: {len(self.tiles)}")
                                        for i, t in enumerate(self.tiles, start=1):
                                            print(f"[DEBUG] tile {i}: {t.x},{t.y} {t.w}x{t.h} fmt={t.fmt} cut={t.cut_sides}")
        running = True
        frame = 0
        while running:
            # debug: print tiles count on first frames
            if frame < 5:
                print(f"[FRAME {frame}] tiles={len(self.tiles)} current_project={getattr(self,'current_project',None)} dirty={self.dirty}")
            frame += 1
            for event in pygame.event.get():
                # track raw mouse movements for reliable drag previews
                if event.type == pygame.MOUSEMOTION:
                    self.last_mouse_pos = event.pos
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE:
                    # enforce a minimum width so grid and side panel don't overlap
                    room_w_px = int(ROOM_W * SCALE)
                    min_width = GRID_ORIGIN[0] + room_w_px + 260  # grid origin + grid + side panel + margin
                    self.win_w = max(event.w, min_width)
                    self.win_h = max(event.h, 480)
                    self.screen = pygame.display.set_mode(
                        (self.win_w, self.win_h), pygame.RESIZABLE)
                    # notify user if requested size was too small
                    if event.w < min_width:
                        self.set_message(f"Fenêtre trop petite — largeur minimale: {min_width}px", duration_ms=4000)
                    else:
                        # clear any previous size warning
                        self.message_timer = 0
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    self.handle_mousedown(event)
                elif event.type == pygame.MOUSEBUTTONUP:
                    self.handle_mouseup(event)
                elif event.type == pygame.KEYDOWN:
                    if not self.handle_keydown(event):
                        running = False
                elif event.type == MENU_OPEN:
                    self._menu_open()
                elif event.type == MENU_NEW:
                    self._menu_new()
                elif event.type == MENU_SAVE:
                    self._menu_save()
                elif event.type == MENU_QUIT:
                    if self._menu_quit():
                        running = False

            self.screen.fill((245, 243, 236))
            title = self.font_bold.render(
                "Éditeur de calepinage — entrée de garage 283 x 295 cm", True,
                (30, 25, 20))
            self.screen.blit(title, (20, 12))

            self.draw_grid()
            for t in self.tiles:
                sel = (t is self.selected) and self.dragging is None
                multi_sel = t in self.selected_tiles
                # color resolved from project palette first, then global COLORS
                # label now shows format index instead of tile id
                try:
                    palette_index = {p[0]: i+1 for i, p in enumerate(self.palette)}
                    fmt_label = str(palette_index.get(t.fmt, ''))
                except Exception:
                    fmt_label = ''
                self.draw_tile(t.rect_cm(), self._palette_color(t.fmt), selected=sel or multi_sel,
                                label=fmt_label if fmt_label else None, cut_edges=t.cut_sides)

            # draw colored outlines around each placed pattern instance for visibility
            instances = {}
            for t in self.tiles:
                pid = getattr(t, 'pattern_instance', None)
                if pid:
                    if pid not in instances:
                        instances[pid] = []
                    instances[pid].append(t)
            if instances:
                # small palette of distinct outline colors
                outline_colors = [(200,30,30),(30,120,200),(50,160,60),(160,60,160),(200,120,30),(30,180,180)]
                for i, (pid, tiles_group) in enumerate(instances.items()):
                    xs = []
                    ys = []
                    x2s = []
                    y2s = []
                    for tt in tiles_group:
                        px, py = cm_to_px(tt.x, tt.y)
                        pw, ph = tt.w * SCALE, tt.h * SCALE
                        xs.append(px)
                        ys.append(py)
                        x2s.append(px + pw)
                        y2s.append(py + ph)
                    minx, miny = min(xs), min(ys)
                    maxx, maxy = max(x2s), max(y2s)
                    color = outline_colors[i % len(outline_colors)]
                    rect = pygame.Rect(minx-3, miny-3, (maxx-minx)+6, (maxy-miny)+6)
                    pygame.draw.rect(self.screen, color, rect, 3)

            if self.dragging:
                mx, my = getattr(self, 'last_mouse_pos', pygame.mouse.get_pos())
                d = self.dragging
                # compute preview center and bounding box in px for additional visuals
                preview_center_px = None
                preview_bbox_px = None
                if d.get('kind') == 'pattern':
                    # preview exact tiles of the pattern at mouse position
                    # compute base using delta from initial raw mouse to keep preview aligned with movement
                    start_raw = d.get('start_raw')
                    start_center_cm = d.get('start_center_cm')
                    if start_raw and start_center_cm:
                        dx_px = mx - start_raw[0]
                        dy_px = my - start_raw[1]
                        dx_cm = dx_px / SCALE
                        dy_cm = dy_px / SCALE
                        base_x_cm = start_center_cm[0] + dx_cm
                        base_y_cm = start_center_cm[1] + dy_cm
                    else:
                        off_x, off_y = d.get('mouse_offset', (0, 0))
                        base_x_px = mx + off_x
                        base_y_px = my + off_y
                        base_x_cm, base_y_cm = px_to_cm(base_x_px, base_y_px)
                    pat = d.get('pattern')
                    if pat:
                        # gather bbox in px while drawing tiles
                        xs, ys, x2s, y2s = [], [], [], []
                        for ti in pat.get('tiles', []):
                            px_cm = base_x_cm + ti['dx']
                            py_cm = base_y_cm + ti['dy']
                            full = (px_cm, py_cm, ti['w'], ti['h'])
                            clipped = clip_to_room(*full)
                            if clipped is None:
                                continue
                            # check overlap
                            overlap = any(rects_overlap(clipped, o.rect_cm()) for o in self.tiles)
                            valid = not overlap
                            draw_color = "#8fd18f" if valid else "#e58b8b"
                            # show tile preview (semi-transparent)
                            self.draw_tile(clipped if clipped is not None else full, draw_color, alpha=160,
                                           cut_edges=compute_cut_sides(full, clipped) if clipped is not None else [])
                            # add to bbox lists
                            px_px, py_px = cm_to_px(clipped[0], clipped[1]) if clipped is not None else cm_to_px(full[0], full[1])
                            pw_px, ph_px = (clipped[2] * SCALE, clipped[3] * SCALE) if clipped is not None else (full[2] * SCALE, full[3] * SCALE)
                            xs.append(px_px); ys.append(py_px); x2s.append(px_px + pw_px); y2s.append(py_px + ph_px)
                        if xs:
                            minx, miny = min(xs), min(ys)
                            maxx, maxy = max(x2s), max(y2s)
                            preview_bbox_px = (minx, miny, maxx, maxy)
                            preview_center_px = ((minx + maxx) // 2, (miny + maxy) // 2)
                else:
                    full_rect, clipped, valid, cut_sides = self.compute_drag(mx, my)
                    preview = clipped if clipped is not None else full_rect
                    color = "#8fd18f" if valid else "#e58b8b"
                    self.draw_tile(preview, color, alpha=170,
                                    cut_edges=cut_sides if valid else [])
                    # compute bbox and center for single-tile preview
                    px_px, py_px = cm_to_px(preview[0], preview[1])
                    pw_px, ph_px = preview[2] * SCALE, preview[3] * SCALE
                    preview_bbox_px = (px_px, py_px, px_px + pw_px, py_px + ph_px)
                    preview_center_px = (int(px_px + pw_px/2), int(py_px + ph_px/2))

                # draw outline around preview bbox
                if preview_bbox_px:
                    minx, miny, maxx, maxy = preview_bbox_px
                    outline_rect = pygame.Rect(minx-4, miny-4, (maxx-minx)+8, (maxy-miny)+8)
                    pygame.draw.rect(self.screen, (30, 144, 60), outline_rect, 3)
                    # draw center marker
                    if preview_center_px:
                        cx, cy = preview_center_px
                        pygame.draw.circle(self.screen, (10,10,10), (cx, cy), 5)
                        pygame.draw.circle(self.screen, (255,255,255), (cx, cy), 3)
                        # numeric display of center in cm
                        cx_cm, cy_cm = px_to_cm(cx, cy)
                        txt = f"C: {cx_cm:.2f}cm, {cy_cm:.2f}cm"
                        txt_surf = self.font.render(txt, True, (40,40,40))
                        # draw background box for readability
                        bx, by = cx + 10, cy - 10
                        bg = pygame.Surface((txt_surf.get_width()+6, txt_surf.get_height()+4), pygame.SRCALPHA)
                        bg.fill((250,250,250,220))
                        self.screen.blit(bg, (bx, by - 2))
                        self.screen.blit(txt_surf, (bx+3, by))

                # crosshair under cursor
                pygame.draw.line(self.screen, (120,120,120), (mx-12, my), (mx+12, my), 1)
                pygame.draw.line(self.screen, (120,120,120), (mx, my-12), (mx, my+12), 1)
                pygame.draw.circle(self.screen, (120,120,120), (mx, my), 3, 1)

            self.draw_palette()
            self.draw_side_info()
            # draw menu (only if native menu not available)
            # menu is drawn below title to avoid overlap
            if not self.use_native_menu:
                self._draw_menu()
            self.draw_message()

            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()


def main():
    # Démarrage : ouvrir l'éditeur. Project selection will be shown inside the UI.
    ed = Editor()
    # ask_load_on_start will cause run() to display the modal at first frame
    ed.ask_load_on_start = True

    # Lancer la boucle principale
    ed.run()


if __name__ == "__main__":
    main()
