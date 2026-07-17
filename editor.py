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
PALETTE = all_pieces()  # [(fmt, w, h, orientation, couleur), ...]


def R(v):
    """Arrondit une coordonnée (cm) à une précision fixe afin d'éliminer les
    dérives d'arrondi flottant qui s'accumulent au fil des déplacements."""
    return round(v, ND)


class PlacedTile:
    _next_id = 1

    def __init__(self, x, y, w, h, fmt, orientation, base_w=None, base_h=None):
        self.id = PlacedTile._next_id
        PlacedTile._next_id += 1
        self.x, self.y, self.w, self.h = R(x), R(y), R(w), R(h)
        self.base_w = R(base_w) if base_w is not None else self.w
        self.base_h = R(base_h) if base_h is not None else self.h
        self.fmt = fmt
        self.orientation = orientation
        self.cut_sides = []  # sous-ensemble de {'left','right','top','bottom'}

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
        self.selected = None  # PlacedTile

        # état du drag
        self.dragging = None  # dict: kind='new'/'move', tile info, offset
        self.drag_valid = False

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
        for idx, item in enumerate(PALETTE):
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

    # ---------- rendu ----------
    def draw_grid(self):
        room_w_px = ROOM_W * SCALE
        room_h_px = ROOM_H * SCALE
        ox, oy = GRID_ORIGIN
        surf = self.screen
        pygame.draw.rect(surf, (255, 255, 255), (ox, oy, room_w_px, room_h_px))
        step = SNAP_STEP * 2
        gx = 0
        while gx <= ROOM_W + 0.001:
            x_px = ox + gx * SCALE
            pygame.draw.line(surf, (225, 222, 214), (x_px, oy), (x_px, oy + room_h_px))
            gx += step
        gy = 0
        while gy <= ROOM_H + 0.001:
            y_px = oy + gy * SCALE
            pygame.draw.line(surf, (225, 222, 214), (ox, y_px), (ox + room_w_px, y_px))
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
        pygame.draw.rect(tile_surf, (75, 63, 47, alpha), tile_surf.get_rect(), 2)
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
        for rect, item in self.palette_rects():
            fmt, w, h, orient, color = item
            pygame.draw.rect(surf, color, rect)
            pygame.draw.rect(surf, (75, 63, 47), rect, 2)
            label = f"{fmt}" + (f" {orient}" if orient else "")
            txt = self.font_small.render(label, True, (40, 35, 28))
            surf.blit(txt, (rect.centerx - txt.get_width() / 2,
                             rect.bottom + 3))

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
        rows = (len(PALETTE) + cols - 1) // cols
        y = y0 + rows * (cell_h + 18) + 12
        counts = {"50x50": 0, "30x50": 0, "30x30": 0}
        for t in self.tiles:
            counts[t.fmt] += 1
        surface_posee = sum(t.w * t.h for t in self.tiles) / 10000.0
        surface_totale = ROOM_W * ROOM_H / 10000.0
        lines = [
            ("QUANTITATIF (posé)", True),
            (f"50x50: {counts['50x50']}", False),
            (f"30x50: {counts['30x50']}", False),
            (f"30x30 : {counts['30x30']}", False),
            (f"Total : {len(self.tiles)}", False),
            (f"Dont découpées : {sum(1 for t in self.tiles if t.is_cut)}", False),
            ("", False),
            (f"Surface posée : {surface_posee:.2f} m2", False),
            (f"Surface totale : {surface_totale:.2f} m2", False),
            (f"Couverture : {100*surface_posee/surface_totale:.1f} %", False),
            ("", False),
            ("Aimant grille (G) :", False),
            ("ON" if self.snap_on else "OFF", False),
        ]
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
            "Clic droit -> supprimer",
            "R : pivoter sélection",
            "Suppr : supprimer sélection",
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
        if event.button == 1:
            for rect, item in self.palette_rects():
                if rect.collidepoint(mx, my):
                    fmt, w, h, orient, color = item
                    self.dragging = {"kind": "new", "w": w, "h": h, "fmt": fmt,
                                      "orientation": orient, "color": color,
                                      "mouse": (mx, my)}
                    return
            t = self.tile_at_pixel(mx, my)
            if t:
                self.selected = t
                x_cm, y_cm = px_to_cm(mx, my)
                self.dragging = {"kind": "move", "tile": t,
                                  "offset": (x_cm - t.x, y_cm - t.y),
                                  "orig": (t.x, t.y, t.w, t.h,
                                           list(t.cut_sides))}
            else:
                self.selected = None
        elif event.button == 3:
            t = self.tile_at_pixel(mx, my)
            if t:
                self.tiles.remove(t)
                if self.selected is t:
                    self.selected = None

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
        else:
            t = d["tile"]
            w, h = t.base_w, t.base_h
            exclude = t
            x_cm, y_cm = px_to_cm(mx, my)
            x_cm -= d["offset"][0]
            y_cm -= d["offset"][1]

        if self.snap_on:
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
        if not self.dragging or event.button != 1:
            return
        mx, my = event.pos
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
        else:
            t = d["tile"]
            if valid:
                t.x, t.y, t.w, t.h = clipped
                t.cut_sides = cut_sides
                self.dirty = True
            else:
                t.x, t.y, t.w, t.h = d["orig"][:4]
                t.cut_sides = d["orig"][4]
                self.set_message("Déplacement invalide (hors zone ou chevauchement)")
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
        elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE) and self.selected:
            self.tiles.remove(self.selected)
            self.selected = None
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
            pose_path = os.path.join(proj_dir, f"{base_name}_pose.json")
        else:
            png_path = os.path.join(OUT_DIR, f"{base_name}.png")
            pose_path = os.path.join(OUT_DIR, f"{base_name}_pose.json")

        # export pose as JSON
        pose_list = []
        for t in self.tiles:
            pose_list.append({
                'id': t.id,
                'format': t.fmt,
                'orientation': t.orientation or None,
                'x_cm': round(t.x, 1),
                'y_cm': round(t.y, 1),
                'w_cm': round(t.w, 1),
                'h_cm': round(t.h, 1),
                'base_w_cm': round(t.base_w, 1),
                'base_h_cm': round(t.base_h, 1),
                'is_cut': bool(t.is_cut),
            })
        with open(pose_path, 'w', encoding='utf-8') as f:
            json.dump(pose_list, f, indent=2, ensure_ascii=False)

        room_w_px, room_h_px = int(ROOM_W * SCALE), int(ROOM_H * SCALE)
        snapshot = pygame.Surface((room_w_px, room_h_px))
        snapshot.fill((255, 255, 255))
        for t in self.tiles:
            x_px, y_px = t.x * SCALE, t.y * SCALE
            w_px, h_px = t.w * SCALE, t.h * SCALE
            r = pygame.Rect(x_px, y_px, w_px, h_px)
            pygame.draw.rect(snapshot, pygame.Color(COLORS[t.fmt]), r)
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
        # generate exports (PNG + pose JSON) into project dir
        try:
            # snapshot PNG
            room_w_px, room_h_px = int(ROOM_W * SCALE), int(ROOM_H * SCALE)
            snapshot = pygame.Surface((room_w_px, room_h_px))
            snapshot.fill((255, 255, 255))
            for t in self.tiles:
                x_px, y_px = t.x * SCALE, t.y * SCALE
                w_px, h_px = t.w * SCALE, t.h * SCALE
                r = pygame.Rect(x_px, y_px, w_px, h_px)
                pygame.draw.rect(snapshot, pygame.Color(COLORS[t.fmt]), r)
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
            png_path = os.path.join(proj_dir, f{"{name}.png"})
            pygame.image.save(snapshot, png_path)
            # pose JSON
            pose_list = []
            for t in self.tiles:
                pose_list.append({
                    'id': t.id,
                    'format': t.fmt,
                    'orientation': t.orientation or None,
                    'x_cm': round(t.x, 1),
                    'y_cm': round(t.y, 1),
                    'w_cm': round(t.w, 1),
                    'h_cm': round(t.h, 1),
                    'base_w_cm': round(t.base_w, 1),
                    'base_h_cm': round(t.base_h, 1),
                    'is_cut': bool(t.is_cut),
                })
            with open(os.path.join(proj_dir, f"{name}_pose.json"), 'w', encoding='utf-8') as pf:
                json.dump(pose_list, pf, indent=2, ensure_ascii=False)
        except Exception:
            # fallback: draw simple top menu buttons if graphics unavailable
            surf = self.screen
            base_y = 10
            x = 20
            buttons = ['Ouvrir','Nouveau','Sauvegarder','Quitter']
            self.menu_buttons.clear()
            for b in buttons:
                txt = self.font.render(b, True, (255,255,255))
                w = txt.get_width()+12
                h = 24
                rect = pygame.Rect(x, base_y, w, h)
                pygame.draw.rect(surf, (60,60,60), rect, border_radius=4)
                surf.blit(txt, (x+6, base_y+4))
                self.menu_buttons[b]=rect
                x += w+8
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
            tiles_from_json = data.get('tiles', []) or []
            self.tiles.clear()
            for td in tiles_from_json:
                nt = PlacedTile(td['x'], td['y'], td['w'], td['h'], td['fmt'],
                                td.get('orientation'), base_w=td.get('base_w'),
                                base_h=td.get('base_h'))
                nt.cut_sides = td.get('cut_sides', [])
                self.tiles.append(nt)
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
        if name:
            if name in self.list_projects():
                if not self._confirm(f"Le projet '{name}' existe. Le sélectionner ?"):
                    self.set_message('Création annulée')
                    return
                else:
                    self.load_project(name)
                    return
            self.tiles.clear()
            self.current_project = name
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
                        # create new project: ask for name, initialize empty project
                        name = self._prompt_text('Nom du nouveau projet :', default='mon_calepinage')
                        if name:
                            # ensure unique name
                            if name in projects:
                                if not self._confirm(f"Le projet '{name}' existe déjà. Le sélectionner à la place ?"):
                                    # ask for a different name
                                    self.set_message('Création annulée : nom en conflit')
                                else:
                                    self.load_project(name)
                            else:
                                # initialize empty state and save
                                self.tiles.clear()
                                self.current_project = name
                                self.save_project(name)
                        else:
                            self.set_message('Création de projet annulée')
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
                self.draw_tile(t.rect_cm(), COLORS[t.fmt], selected=sel,
                                label=f"#{t.id}", cut_edges=t.cut_sides)

            if self.dragging:
                mx, my = pygame.mouse.get_pos()
                full_rect, clipped, valid, cut_sides = self.compute_drag(mx, my)
                preview = clipped if clipped is not None else full_rect
                color = "#8fd18f" if valid else "#e58b8b"
                self.draw_tile(preview, color, alpha=170,
                                cut_edges=cut_sides if valid else [])

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
