"""Interface interactive (pygame) pour visualiser les 4 propositions de
dallage et leurs différentes vues (plan, découpes, vue 3D).

Commandes :
  <-  / ->   : changer de proposition (1 à 4)
  Haut/Bas   : changer de vue (plan / découpes / vue 3D)
  Echap / Q  : quitter
"""
import os
import sys

import pygame

from dallage.layout_engine import generate_layout, PATTERNS, SEEDS
from dallage.quantitatif import compute_quantitatif

OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
KEYS = list(PATTERNS.keys())

VIEWS = [
    ("1_plan", "Plan de calepinage"),
    ("4_decoupes", "Plan des découpes"),
    ("5_vue3d", "Vue 3D artistique"),
]

WIN_W, WIN_H = 1000, 900


def load_image(path, max_w, max_h):
    img = pygame.image.load(path)
    iw, ih = img.get_size()
    scale = min(max_w / iw, max_h / ih)
    return pygame.transform.smoothscale(img, (int(iw * scale), int(ih * scale)))


def main():
    if not os.path.isdir(OUT_DIR) or not os.listdir(OUT_DIR):
        print("Aucun fichier trouvé dans output/. Lancez d'abord "
              "'python generate_all.py'.")
        sys.exit(1)

    pygame.init()
    pygame.display.set_caption("Dallage - Entrée de garage 295x283 cm")
    screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
    font_title = pygame.font.SysFont("Arial", 22, bold=True)
    font = pygame.font.SysFont("Arial", 16)
    font_small = pygame.font.SysFont("Arial", 13)
    clock = pygame.time.Clock()

    prop_idx = 0
    view_idx = 0
    running = True

    # cache des carreaux / quantitatifs déjà calculés
    cache = {}

    def get_data(key):
        if key not in cache:
            tiles = generate_layout(key, seed=SEEDS[key])
            cache[key] = (tiles, compute_quantitatif(tiles))
        return cache[key]

    while running:
        win_w, win_h = screen.get_size()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                win_w, win_h = event.w, event.h
                screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_RIGHT:
                    prop_idx = (prop_idx + 1) % len(KEYS)
                elif event.key == pygame.K_LEFT:
                    prop_idx = (prop_idx - 1) % len(KEYS)
                elif event.key == pygame.K_DOWN:
                    view_idx = (view_idx + 1) % len(VIEWS)
                elif event.key == pygame.K_UP:
                    view_idx = (view_idx - 1) % len(VIEWS)

        key = KEYS[prop_idx]
        title = PATTERNS[key]
        view_suffix, view_label = VIEWS[view_idx]
        tiles, q = get_data(key)

        screen.fill((245, 243, 236))

        header = font_title.render(f"{title}  —  {view_label}", True, (30, 25, 20))
        screen.blit(header, (20, 12))

        help_txt = font_small.render(
            "<-/-> proposition   Haut/Bas: vue   Echap: quitter", True,
            (90, 85, 75))
        screen.blit(help_txt, (20, win_h - 26))

        img_path = os.path.join(OUT_DIR, f"{key}_{view_suffix}.png")
        panel_w = int(win_w * 0.68)
        panel_h = win_h - 90
        if os.path.exists(img_path):
            img = load_image(img_path, panel_w - 20, panel_h)
            screen.blit(img, (10, 50))
        else:
            missing = font.render("Image manquante : lancez generate_all.py",
                                   True, (150, 30, 30))
            screen.blit(missing, (20, 60))

        # panneau latéral quantitatif
        side_x = panel_w + 10
        pygame.draw.rect(screen, (255, 255, 255), (side_x, 50, win_w - side_x - 10,
                                                     panel_h))
        pygame.draw.rect(screen, (200, 195, 180), (side_x, 50, win_w - side_x - 10,
                                                     panel_h), 1)
        lines = [
            "QUANTITATIF", "",
            f"50x50 cm : {q.counts['50x50']}",
            f"30x50 cm : {q.counts['30x50']}",
            f"30x30 cm : {q.counts['30x30']}",
            f"Total    : {sum(q.counts.values())}",
            "",
            f"Découpes : {q.n_cuts}",
            f"Surface totale : {q.surface_totale_m2} m2",
            f"Achat carreaux : {q.surface_carreaux_posee_m2} m2",
            f"Chutes : {q.chutes_m2} m2",
            f"Taux de perte : {q.taux_perte_pct} %",
            "",
            "A COMMANDER (+8%)",
            f"50x50 : {q.a_commander['50x50']}",
            f"30x50 : {q.a_commander['30x50']}",
            f"30x30 : {q.a_commander['30x30']}",
            "",
            f"Proposition {prop_idx + 1}/{len(KEYS)}",
            f"Vue {view_idx + 1}/{len(VIEWS)}",
        ]
        yy = 62
        for line in lines:
            bold = line.isupper() and line != ""
            f_ = font_title if False else (pygame.font.SysFont("Arial", 15, bold=True)
                                            if bold else font)
            surf = f_.render(line, True, (40, 35, 28))
            screen.blit(surf, (side_x + 12, yy))
            yy += 22

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()


if __name__ == "__main__":
    main()
