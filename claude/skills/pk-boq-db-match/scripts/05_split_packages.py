"""V2: Split hard items into 3 balanced Matcher packages by family grouping."""
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
hard = json.loads((ROOT / "v2_hard_items.json").read_text(encoding="utf-8"))

# Group families into 3 balanced packages
PKG_MAP = {
    "pkg_A_civil": {
        "families": ["concrete_grade", "block_wall", "structural_steel", "rebar",
                     "earthwork", "geotech", "trench_drain", "pit_manhole", "fence"],
        "label": "Civil/Structural/Earthwork",
    },
    "pkg_B_finish": {
        "families": ["putty_screed", "waterproofing", "wall_paint", "steel_coating",
                     "fire_coating", "tile_finish", "stone_finish", "gypsum_board",
                     "calcium_silicate_board", "acoustic_panel", "vinyl_flooring",
                     "epoxy_flooring", "ceiling_system", "handrail", "skirting"],
        "label": "Finishing/Coating/Boards/Fixtures",
    },
    "pkg_C_special": {
        "families": ["no_family", "insulation_board", "misc_finish", "pavement_road",
                     "sanitary", "fire_door", "door_other", "curtain_wall", "glass",
                     "formwork"],
        "label": "Doors/Insulation/Roads/No-Family/Special",
    },
}

buckets = defaultdict(list)
for x in hard:
    fam = x["family"]
    for pkg, meta in PKG_MAP.items():
        if fam in meta["families"]:
            buckets[pkg].append(x)
            break
    else:
        buckets["pkg_C_special"].append(x)  # fallback

for pkg, meta in PKG_MAP.items():
    items = buckets[pkg]
    p = ROOT / f"v2_{pkg}.json"
    p.write_text(json.dumps({
        "label": meta["label"],
        "families": meta["families"],
        "count": len(items),
        "items": items,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"{pkg} ({meta['label']}): {len(items)} items, {p.stat().st_size // 1024} KB")

total = sum(len(v) for v in buckets.values())
print(f"\nTotal packaged: {total}")
