"""Rendu graphique des plans (calepinage, découpes, vue 3D) via matplotlib."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyArrow
import numpy as np

from .geometry import ROOM_W, ROOM_H, COLORS, FORMATS
from .layout_engine import Tile

FIG_DPI = 150


def _draw_tile(ax, t: Tile, show_id=True):
    color = COLORS["cut"] if t.is_cut else COLORS[t.fmt]
    rect = patches.Rectangle((t.x, ROOM_H - t.y - t.h), t.w, t.h,
                              linewidth=1.1, edgecolor="#4b3f2f",
                              facecolor=color)
    ax.add_patch(rect)
    if show_id:
        label = f"{t.id}"
        ax.text(t.x + t.w / 2, ROOM_H - t.y - t.h / 2, label,
                ha="center", va="center", fontsize=5.2, color="#3a3226")


def render_plan(tiles, title, out_path, room_w=ROOM_W, room_h=ROOM_H):
    """Plan de calepinage d'architecte : cotes, numérotation, orientation."""
    fig, ax = plt.subplots(figsize=(9, 10), dpi=FIG_DPI)
    for t in tiles:
        _draw_tile(ax, t)

    ax.set_xlim(-35, room_w + 35)
    ax.set_ylim(-35, room_h + 60)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=13, fontweight="bold", pad=28)

    # Cadre du garage
    ax.add_patch(patches.Rectangle((0, 0), room_w, room_h, fill=False,
                                    edgecolor="black", linewidth=2.2))

    # Cotation largeur (bas)
    y_cote = -18
    ax.annotate("", xy=(room_w, y_cote), xytext=(0, y_cote),
                arrowprops=dict(arrowstyle="<->", color="black", lw=1.2))
    ax.text(room_w / 2, y_cote - 6, f"{room_w:.0f} cm (largeur)",
            ha="center", va="top", fontsize=9, fontweight="bold")

    # Cotation hauteur (gauche)
    x_cote = -18
    ax.annotate("", xy=(x_cote, room_h), xytext=(x_cote, 0),
                arrowprops=dict(arrowstyle="<->", color="black", lw=1.2))
    ax.text(x_cote - 6, room_h / 2, f"{room_h:.0f} cm (longueur)",
            ha="center", va="center", rotation=90, fontsize=9,
            fontweight="bold")

    # Légende
    legend_items = [(f"{fmt} cm", COLORS[fmt]) for fmt in FORMATS]
    legend_items.append(("Découpe", COLORS["cut"]))
    lx, ly = 0, room_h + 14
    for i, (label, color) in enumerate(legend_items):
        bx = lx + i * (room_w / len(legend_items))
        ax.add_patch(patches.Rectangle((bx, ly), 14, 10, facecolor=color,
                                        edgecolor="#4b3f2f"))
        ax.text(bx + 18, ly + 5, label, fontsize=8, va="center")

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def render_cuts(tiles, title, out_path, room_w=ROOM_W, room_h=ROOM_H):
    """Plan des découpes uniquement, avec dimensions exactes annotées."""
    fig, ax = plt.subplots(figsize=(9, 10), dpi=FIG_DPI)
    ax.add_patch(patches.Rectangle((0, 0), room_w, room_h, fill=False,
                                    edgecolor="black", linewidth=1.4,
                                    linestyle="--"))
    cuts = [t for t in tiles if t.is_cut]
    for t in tiles:
        base_color = "#f2efe6" if not t.is_cut else COLORS["cut"]
        rect = patches.Rectangle((t.x, room_h - t.y - t.h), t.w, t.h,
                                  linewidth=0.6, edgecolor="#a89f8c",
                                  facecolor=base_color, alpha=0.9 if t.is_cut else 0.35)
        ax.add_patch(rect)
    for t in cuts:
        cx, cy = t.x + t.w / 2, room_h - t.y - t.h / 2
        dims = f"{t.w:.1f}x{t.h:.1f}"
        ax.text(cx, cy, f"#{t.id}\n{dims}", ha="center", va="center",
                fontsize=5.4, color="#5a1414", fontweight="bold")

    ax.set_xlim(-10, room_w + 10)
    ax.set_ylim(-10, room_h + 30)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(f"{title}\nPlan des découpes ({len(cuts)} pièces à recouper)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def render_pose_table_png(tiles, title, out_path, max_rows=40):
    """Rend un tableau de pose (N°, format, orientation) en image, complet en
    CSV à côté (voir generate_all.py)."""
    fig, ax = plt.subplots(figsize=(6, min(0.24 * len(tiles) + 1.2, 24)), dpi=120)
    ax.axis("off")
    rows = [[str(t.id), t.fmt, t.orientation or "-",
             "Oui" if t.is_cut else "Non"] for t in tiles]
    table = ax.table(cellText=rows,
                      colLabels=["N°", "Format", "Orientation", "Découpe"],
                      loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(7)
    table.scale(1, 1.15)
    ax.set_title(title + " — Plan de pose", fontsize=11, fontweight="bold", pad=10)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def render_3d(tiles, title, out_path, room_w=ROOM_W, room_h=ROOM_H):
    """Vue 3D artistique simplifiée : projection en perspective du plan 2D
    (les dalles gardent leurs proportions réelles avant projection)."""
    fig, ax = plt.subplots(figsize=(9, 7), dpi=FIG_DPI)

    # Perspective simple : point de fuite en haut, la profondeur (longueur,
    # room_h) s'éloigne de l'observateur -> on réduit x et on translate
    # progressivement vers le "point de fuite" au fur et à mesure que y augmente.
    vanish_x = room_w / 2
    depth_scale_top = 0.45   # échelle horizontale au fond (haut de l'image)
    height_scale = 0.62      # aplatissement de la profondeur (effet sol incliné)

    def project(x, y):
        # y=0 -> premier plan (bas image), y=room_h -> fond (haut image)
        t = y / room_h
        scale = 1 - t * (1 - depth_scale_top)
        px = vanish_x + (x - vanish_x) * scale
        py = t * room_h * height_scale
        return px, py

    for t in tiles:
        corners = [(t.x, t.y), (t.x + t.w, t.y), (t.x + t.w, t.y + t.h),
                   (t.x, t.y + t.h)]
        poly = [project(cx, cy) for cx, cy in corners]
        color = COLORS["cut"] if t.is_cut else COLORS[t.fmt]
        shade = 1.0 - 0.15 * (t.y / room_h)  # légère ombre en profondeur
        rgb = matplotlib.colors.to_rgb(color)
        rgb = tuple(c * shade for c in rgb)
        ax.add_patch(patches.Polygon(poly, closed=True, facecolor=rgb,
                                      edgecolor="#3a3226", linewidth=0.5))

    ax.set_xlim(-20, room_w + 20)
    ax.set_ylim(-5, room_h * height_scale + 15)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor("#e7e2d8")
    ax.set_title(f"{title} — Vue 3D artistique (perspective)", fontsize=12,
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor="#e7e2d8")
    plt.close(fig)
