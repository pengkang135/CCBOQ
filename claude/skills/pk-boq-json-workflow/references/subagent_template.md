# Sub-agent Instructions Template

`shard.py` copies this into your batches folder as `SUBAGENT_INSTRUCTIONS.md`. Edit it for the current task before dispatching agents. The template below covers the most common workflow — classification calibration for a BOQ — but adapt freely.

---

# BOQ classification VALIDATOR / CORRECTOR — batch instructions

## Your task

Review the flagged items in `batch_XX.json` and produce `results_XX.json`. Each item may be correctly classified already, or wrong; you decide based on context.

## Input record

```json
{
  "excel_row": 12103,
  "desc": "Thai Morning Glory / Thai Water Spinach height 0.30-0.60 m",
  "unit": "sq.m",
  "qty": "410",
  "project": "【SB Animal Hospital】",
  "chapter": "《3.1 Landscape Works (Main)》",
  "chapter_code": "3.1 Landscape Works (Main)",
  "subheading": "{Shrub-Ground Cover Plant}",
  "current_disc": "【MEP】",
  "current_cat": "《ELV / ICT》",
  "current_subcat": "Data network",
  "current_material": "Data/IT equipment",
  "current_spec": null,
  "current_mat_unit": "set",
  "current_mat_qty": "410",
  "prev_context": [ ... ],
  "next_context": [ ... ]
}
```

## Chapter code → discipline map

- `ST` → 【Civil / Structural】
- `AR` → 【Architectural】
- `SN` → 【MEP】 (Sanitary / Plumbing)
- `EE` → 【MEP】 (Electrical)
- `AC` → 【MEP】 (HVAC / Aircon)
- `FA` → 【MEP】 (Fire alarm)
- `EL` / `ELV` → 【MEP】
- `LA` → 【Landscape】
- `ID` → 【Architectural】 (Interior Decoration)

Sub-building prefixes (`HS-`, `HO-`, `MP-`, `ME-`, `SA-`) inherit the trailing discipline. `HS-ST` → Civil/Structural, `HO-EE` → MEP.

**The chapter code is the strongest single signal for discipline** — trust it over whatever `current_disc` says unless the description clearly indicates otherwise.

## Valid (Discipline, Category) pairs

**【Civil / Structural】**: 《Steel》, 《Concrete》, 《Formwork & Temp. Works》, 《Earthwork》, 《Precast Pile》, 《Masonry》

**【Architectural】**: 《Floor & Wall Finish》, 《Painting & Coating》, 《Doors & Windows》, 《Roofing》, 《Glass & Glazing》, 《Ceiling》, 《Insulation》, 《Waterproofing》, 《Ironmongery / Decoration》

**【MEP】**: 《Pipes & Fittings》, 《Sanitary Ware》, 《Cables & Wiring》, 《Valves》, 《HVAC》, 《Electrical Equipment》, 《ELV / ICT》, 《Pumps》, 《Plumbing Equipment》, 《Distribution Boards》, 《Fire Protection》, 《Lighting》

**【Landscape】**: 《Signage & Wayfinding》, 《Softscape》, 《Hardscape》

**【Infrastructure】**: 《Drainage Structures》, 《Road & Pavement》

## Common error patterns

1. **Plant species** (Morning Glory, Ipomoea, Ixora, Sedge, Cyperus, Wild [X], etc.) with `height X.X m` measurement → 【Landscape】/《Softscape》.
2. **`insulation ... pipe / Ø / Waste-drain / refrigerant`** → 【MEP】/《HVAC》 as `Pipe insulation` (NOT Architectural Insulation).
3. **`Gypsum board ceiling ...`** → 【Architectural】/《Ceiling》 as `Gypsum board ceiling`.
4. **`SPIRAL RB<N>mm.@<Y>mm`** → 【Civil / Structural】/《Steel》 as `Reinforcing steel bar`, spec = `SR-24 D<N>mm @<Y>mm spiral`, unit = kg.
5. **Animal-exhibit fixtures** (Soaking Pond, Fruit Tray, Food Trough) → 【Landscape】/《Hardscape》 or 【Architectural】/《Ironmongery / Decoration》 depending on whether the item is a built feature or a movable furniture.
6. **Floor codes** (`ST1 Floor Concrete...`, `WD1 Floor...`, `F# Floor...`) → 【Architectural】/《Floor & Wall Finish》.

## Preservation

Some flagged rows may actually be correct — set `action: "keep"` and give a short reason. Do NOT invent a fix when the current classification is already right.

## Output schema

Write JSON array to `results_XX.json` (same folder as your batch), same order as input:

```json
[
  {
    "excel_row": 12103,
    "action": "fix",                    // "fix" or "keep"
    "updates": {
      "current_disc": "【Landscape】",
      "current_cat": "《Softscape》",
      "current_subcat": "Aquatic",
      "current_material": "Thai Morning Glory",
      "current_spec": "height 0.30-0.60 m",
      "current_mat_unit": "sq.m",
      "current_mat_qty": "410"
    },
    "reason": "plant species in LA chapter"
  },
  { "excel_row": 681, "action": "keep", "reason": "already correctly classified as Ironmongery/Decoration" },
  ...
]
```

## Field rules

- `updates.current_material` — SHORT canonical noun, not the full description.
- `updates.current_spec` — technical dimensions/grade only (e.g. `Ø 139.8 x 4.0 mm`, `SD-40 D16mm`, `PN10 D100mm`).
- `updates.current_mat_unit` — usually equals the row's `unit` field.
- `updates.current_mat_qty` — usually equals the row's `qty` field.
- Only use (Discipline, Category) pairs from the taxonomy above. Do not invent new ones.
- If truly un-classifiable, set updates to empty strings and action to "fix" with a Reason.

## Do not
- Do not touch any Excel file.
- Do not modify the batch input file.
- Do not ask clarifying questions — infer from context and mark uncertain with a `reason` note.
- Do not exceed the taxonomy pairs listed.
