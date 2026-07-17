"""Génère les 4 planches de présentation complètes (plan, découpes, pose,
quantitatif, vue 3D, fiche carreleur) dans le dossier output/."""
import os
import json

from dallage.geometry import ROOM_W, ROOM_H, JOINT_MM, FORMATS
from dallage.layout_engine import generate_layout, PATTERNS, SEEDS
from dallage.quantitatif import compute_quantitatif
from dallage.render import render_plan, render_cuts, render_pose_table_png, render_3d

OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUT_DIR, exist_ok=True)

# Write a description file describing the auto-generated patterns
DESCRIPTION_PATH = os.path.join(OUT_DIR, "description.md")
with open(DESCRIPTION_PATH, "w", encoding="utf-8") as ddf:
    ddf.write("# Description des motifs auto-générés\n\n")
    ddf.write("Ce dossier contient plusieurs propositions de calepinage générées automatiquement.\n")
    ddf.write("Chaque motif produit les fichiers suivants :\n\n")
    ddf.write("- 1_plan.png : plan de pose visuel\n")
    ddf.write("- 2_pose.png : tableau de pose (aperçu)\n")
    ddf.write("- 4_decoupes.png : vues des découpes\n")
    ddf.write("- 5_vue3d.png : rendu 3D simplifié\n")
    ddf.write("- 6_fiche_carreleur.md : fiche carreleur et quantitatif\n")
    ddf.write("- <key>.json : données canoniques du projet (tiles, dimensions)\n\n")
    ddf.write("Les motifs disponibles sont :\n\n")
    for key, title in PATTERNS.items():
        ddf.write(f"- {key} : {title}\n")
    ddf.write("\nChaque motif est documenté par une fiche carreleur détaillée et un fichier JSON canonique utilisable pour réouvrir le projet dans l'éditeur.\n")

POSE_ADVICE = {
    "contemporain": "Démarrer par le plus grand format (points d'ancrage), puis "
                     "compléter chaque bande avec les formats plus petits. "
                     "Poser du fond du garage vers la porte.",
    "semi": "Poser en bandes régulières du fond vers la porte, en alternant "
            "strictement les carreaux comme indiqué dans le plan de pose. "
            "Solution la plus simple à mettre en œuvre.",
    "bandes": "Poser en colonnes (bandes verticales) d'un mur latéral vers "
              "l'autre, en respectant l'orientation indiquée pour chaque "
              "colonne.",
    "romain": "Poser par zones de 2 bandes en alternant les formats comme en "
              "pierre naturelle ; ajuster visuellement les découpes en "
              "périphérie pour un rendu irrégulier mais harmonieux.",
}


def fiche_carreleur_md(key, title, tiles, q):
    n_bands = len({t.row for t in tiles}) if key != "bandes" else len({t.col for t in tiles})
    quant_lines = [
        f"- {fmt} cm : {q.counts[fmt]} (à commander : {q.a_commander[fmt]})"
        for fmt in FORMATS
    ]
    lines = [
        f"# Fiche carreleur — {title}",
        "",
        f"- Dimensions de l'entrée de garage : {ROOM_W:.0f} x {ROOM_H:.0f} cm",
        f"- Largeur de joint recommandée : {JOINT_MM} mm",
        f"- Sens de pose : {POSE_ADVICE[key]}",
        "",
        "## Quantitatif",
        *quant_lines,
        f"- Surface totale : {q.surface_totale_m2} m²",
        f"- Surface de carreaux à acheter : {q.surface_carreaux_posee_m2} m²",
        f"- Chutes : {q.chutes_m2} m²  (taux de perte {q.taux_perte_pct} %)",
        f"- Nombre de découpes : {q.n_cuts}",
        "",
        "## Recommandations",
        "- Prévoir une marge de sécurité de 8 % incluse dans les quantités "
        "\"à commander\".",
        "- Réaliser les découpes à la pince/disque diamant, chants ébavurés.",
        "- Vérifier le sens de pose des carreaux rectangulaires (H = horizontal, "
        "V = vertical) sur le plan de calepinage avant la pose définitive.",
        "- Toutes les découpes sont regroupées en périphérie (bords et bandeau "
        "final) : aucune découpe au centre du dallage.",
    ]
    return "\n".join(lines)


def main():
    summary_lines = ["# Récapitulatif global — 4 propositions de dallage",
                      f"\nEntrée de garage : {ROOM_W:.0f} x {ROOM_H:.0f} cm "
                      f"({ROOM_W*ROOM_H/10000:.2f} m²)\n"]

    for key, title in PATTERNS.items():
        seed = SEEDS[key]
        tiles = generate_layout(key, seed=seed)
        q = compute_quantitatif(tiles)

        render_plan(tiles, title, os.path.join(OUT_DIR, f"{key}_1_plan.png"))
        render_cuts(tiles, title, os.path.join(OUT_DIR, f"{key}_4_decoupes.png"))
        render_pose_table_png(tiles, title,
                               os.path.join(OUT_DIR, f"{key}_2_pose.png"))
        render_3d(tiles, title, os.path.join(OUT_DIR, f"{key}_5_vue3d.png"))

        # write canonical project JSON into output/<key>.json
        project_data = {
            'room_w': ROOM_W,
            'room_h': ROOM_H,
            'tiles': [
                {'id': t.id, 'x': t.x, 'y': t.y, 'w': t.w, 'h': t.h,
                 'fmt': t.fmt, 'orientation': t.orientation,
                 'base_w': getattr(t, 'base_w', t.w), 'base_h': getattr(t, 'base_h', t.h),
                 'cut_sides': list(getattr(t, 'cut_sides', []))}
                for t in tiles
            ]
        }
        with open(os.path.join(OUT_DIR, f"{key}.json"), 'w', encoding='utf-8') as f:
            json.dump(project_data, f, indent=2, ensure_ascii=False)

        fiche = fiche_carreleur_md(key, title, tiles, q)
        with open(os.path.join(OUT_DIR, f"{key}_6_fiche_carreleur.md"), "w",
                  encoding="utf-8") as f:
            f.write(fiche)

        summary_lines.append(f"## {title}")
        for fmt in FORMATS:
            summary_lines.append(f"- Carreaux {fmt} : {q.counts[fmt]}")
        summary_lines.append(f"- Total carreaux : {sum(q.counts.values())}")
        summary_lines.append(f"- Découpes : {q.n_cuts}")
        summary_lines.append(f"- Chutes : {q.chutes_m2} m² (perte {q.taux_perte_pct} %)")
        commande_str = ", ".join(f"{fmt}={q.a_commander[fmt]}" for fmt in FORMATS)
        summary_lines.append(f"- À commander (avec marge 8%) : {commande_str}")
        summary_lines.append("")
        print(f"[OK] {title}: {sum(q.counts.values())} carreaux, "
              f"{q.n_cuts} découpes, perte {q.taux_perte_pct}%")

    with open(os.path.join(OUT_DIR, "0_recapitulatif.md"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(summary_lines))

    print("\nTous les fichiers ont été générés dans:", OUT_DIR)


if __name__ == "__main__":
    main()
