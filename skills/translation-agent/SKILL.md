---
name: translation-agent
description: Hybrid translation workflow for Excel, documents, and engineering project content using Flash -> Pro sub-agent chain. Features term extraction, glossary management, NRM-aware terminology control, and refined QA. Use when the user asks to translate, localize, or polish technical/project documents, especially construction, quantity surveying, cost planning, BOQ, or NRM-based material. Trigger words: "翻译", "精翻", "快翻", "改成中文", "改成英文", "translate", "localize".
---

# Translation Agent

Use this as the canonical translation skill.

Core principle: Flash sub-agent does the first-pass translation, then Pro sub-agent reviews and polishes. For engineering content, prioritize professional terms used in project delivery and align terminology with NRM-style quantity surveying language whenever applicable.

## Default Behavior

- Default mode: `normal`
- Default target language: keep the user's requested target language; if omitted, ask only when necessary
- Default style for engineering content: `technical`
- Default quality rule: preserve meaning first, terminology second, fluency third, but complete all three before delivery
- Default escalation chain (all formats): Flash sub-agent (first-pass translation) → Pro sub-agent (review & polish; escalation for cases Flash cannot resolve)
- Default Excel rule for engineering schedules, BOQ, and repetitive line-item files: Excel is only the source container, Markdown is the review workspace, and Excel is updated only after the Markdown final draft has been fully reviewed and confirmed

## Modes

| Mode | Workflow | When to Use |
|------|----------|-------------|
| `quick` | Light analysis -> Flash translation -> Brief terminology check | Fast turnaround, low-risk text |
| `normal` | Analyze -> Term extraction/glossary -> Flash translation -> Pro review | Default for most files and project documents |
| `refined` | Analyze -> Term extraction/glossary -> Flash translation -> Pro review -> Polish -> Final QA | "精翻", client-facing material, contractual or high-visibility content |

If the user says "快翻", use `quick`.
If the user says "精翻", use `refined`.
If the user does not specify a mode, use `normal`.

## Workflow

### Stage 1: Analyze the task

Before translating, identify the minimum context needed to keep terminology stable.

Check:
1. Source language and target language.
2. File type and whether formatting must be preserved.
3. Domain: general, engineering, construction, cost management, procurement, specification, BOQ, or NRM-related.
4. Output expectation: quick draft, working translation, or publication/client-ready translation.

For `normal` and `refined` modes, provide a short analysis covering:
1. Source context: author intent, document purpose, target reader.
2. Tone and style: technical, formal, contractual, explanatory, marketing, etc.
3. Key terminology: identify 3-10 domain terms that must stay consistent.

### Stage 2: Prepare terminology

Build or confirm a glossary before large-scale translation whenever the text is technical, repetitive, or file-based.

When the document is related to engineering, BOQ, cost planning, procurement, or NRM-style quantity surveying, read `references/nrm-terms.md` first and use `references/nrm-glossary.json` as the default starter glossary.

For BOQ and construction-schedule files (especially marine/port projects), also load `references/boq-glossary.json` as a second base layer. It covers preliminaries, dredging, reclamation, quay structures, drainage, electrical, pavements, and building terms (~600 entries). Use NRM glossary for QS methodology terms and BOQ glossary for domain-specific construction vocabulary.

#### Excel term extraction

Use the bundled script when the source is an Excel sheet and terminology consistency matters.

```bash
python .trae/skills/translation-agent/scripts/analyze_terms.py "{file_path}" --col {src_col_idx} --output "{file_dir}/terms_candidate.json"
```

Agent actions:
1. Run the analysis script.
2. Read `terms_candidate.json`.
3. Filter out noise and keep the terms that matter to the document.
4. Confirm or edit translations with the user when the terms affect scope, cost, measurement rules, or contract meaning.

#### Glossary rules

Create or update `{file_dir}/glossary.json` using this format:

```json
{
  "SourceTerm": "TargetTerm",
  "混凝土": "Concrete",
  "梁": "Beam",
  "工程量清单": "bill of quantities"
}
```

Terminology policy:
- Prefer approved client, project, or company terminology over generic machine choices.
- For engineering and cost documents, prefer NRM-aligned terminology where it fits the source context.
- Keep quantity surveying terms stable across the whole file.
- If a term can map to multiple English choices, choose one and stay consistent.
- If a term is ambiguous and changes commercial meaning, flag it instead of guessing.
- Treat `references/nrm-glossary.json` as the base layer, then overlay project-specific approved terms on top of it.

NRM-aware guidance:
- Treat `工程量清单`, `计量`, `综合单价`, `暂列金额`, `工程量`, `工作范围`, `构件`, `分部分项`, `前期费用`, `成本计划` and similar terms as high-priority glossary candidates.
- Prefer terminology that reads naturally in UK-style construction cost language when the source aligns with NRM practice.
- Do not force NRM wording onto unrelated domains; use it only when the source is clearly cost planning, measurement, procurement, or project control material.
- If a high-risk term appears, check `references/nrm-terms.md` before finalizing wording.

#### Iterative glossary building for new domains

When translating a large domain-specific file with no existing glossary:
1. Run `analyze_terms.py` to extract high-frequency candidate terms
2. Build an initial glossary from extracted terms + base references (`nrm-glossary.json`, `boq-glossary.json`)
3. Translate the first batch (or first few sections)
4. Review output and identify recurring mistranslation patterns
5. Add corrections to the glossary and document pitfalls
6. Re-translate or re-polish affected rows with the updated glossary
7. Repeat until quality stabilizes (typically 2-3 rounds for a new domain)

This iterative approach converges much faster than attempting a perfect glossary upfront, and the accumulated corrections become reusable domain references. After the session, promote stable glossaries and pitfall lists into the skill's `references/` directory.

### Stage 2.5: Create a Markdown review draft for Excel files

For engineering Excel files with many line items, repeated terms, section headers, or high commercial risk, do not rely on direct in-cell review alone.

Default rule:
1. Export the Excel content to a Markdown draft first.
2. Complete all translation, review, terminology correction, and QA in Markdown.
3. Treat the reviewed Markdown as the single source of truth for the target text.
4. Write back to Excel only once the Markdown draft is considered final.

Use this step by default for:
- BOQ and schedule of prices files
- Quantity surveying, procurement, tender, and cost-planning schedules
- Files with more than roughly 100 rows
- Files where repeated machine-translation artifacts or duplicated wording are likely

For long files, add one more default rule:
1. If the file is long enough that translation quality may degrade across the later sections, split the Markdown review workload into semantic chunks before the main review or polishing pass.
2. Split by content structure first, such as `Class`, package, trade, building/area, or heading/subheading blocks.
3. Keep each heading with its subordinate line items; do not split a section in the middle just to satisfy a fixed row count.
4. Do not split too finely. Use the largest chunk size that still preserves quality.
5. As a practical default, prefer one complete section per chunk, or roughly `120-250` rows when a natural section is still too large.
6. If one section is still too large, split it by the next semantic level, not by arbitrary 20-row or 50-row slices.
7. Review each chunk to completion, then merge the corrected chunks back into the master Markdown draft before the one-time Excel write-back.

Bundled scripts:

```bash
python .trae/skills/translation-agent/scripts/export_excel_review_md.py "{file_path}" --src-col {src_col} --tgt-col {tgt_col} --output "{file_dir}/{file_stem}.review.md"
python .trae/skills/translation-agent/scripts/chunk_review_md.py split "{file_dir}/{file_stem}.review.md" --out-dir "{file_dir}/{file_stem}.review_chunks" --min-rows 120 --max-rows 250
python .trae/skills/translation-agent/scripts/chunk_review_md.py merge "{file_dir}/{file_stem}.review.md" "{file_dir}/{file_stem}.review_chunks" --output "{file_dir}/{file_stem}.review.final.md"
python .trae/skills/translation-agent/scripts/import_review_md_to_excel.py "{file_dir}/{file_stem}.review.final.md" "{file_path}" --tgt-col {tgt_col} --output "{file_dir}/{file_stem}_polished.xlsx"
```

Chunking script rules:
- Use `split` after the Markdown draft is exported and before long-form review starts.
- Review and polish the chunk files inside `{file_stem}.review_chunks/`, not separate Excel copies.
- After all chunks are corrected, run `merge` to rebuild one final master Markdown file.
- Write back to Excel from the merged master Markdown file, not from an individual chunk file.

Write-back parameter rule:
- `--tgt-col` may be provided either as a zero-based column index such as `2` or as an Excel column letter such as `C`.
- Use the same target column reference consistently across export, review notes, and write-back.

Markdown review draft goals:
- Keep row numbers so edits can be written back reliably.
- Preserve the English source, current translation, item number, unit, and quantity.
- Make repeated errors, terminology drift, and duplicated wording easy to scan.
- Prevent quality drift caused by repeated in-cell rewrites after review.
- Make long-file work reviewable in chunk-sized units without losing section meaning or row alignment.

### Stage 2.6: Direct Excel Translation (Alternative for Very Large Files)

For very large schedule files (1000+ rows) where Markdown review is impractical due to size, or when the user explicitly wants a faster path, use **direct Excel translation** as an alternative to the Markdown review workflow (Stage 2.5).

This path sacrifices the Markdown review step for speed, but includes built-in safeguards: progressive save, crash recovery, exponential backoff retry, JSON failure dump, and BOQ formatting character cleaning.

#### When to Use Direct Excel Translation

- Files with 1000+ rows of repetitive line items
- BOQ / schedule of prices where per-row review is impractical
- When the user explicitly says "direct translation" or "skip markdown review"
- When the file is a working draft and does not require publication quality

#### Workflow

**Step 1: Scan for untranslated rows**
Identify all rows where the target column is empty. Skip rows that already have valid translations (crash recovery / resume support).

**Step 2: Clean source text (BOQ files)**
For BOQ and schedule-of-prices files, pass `--clean` to strip hierarchy markers before translation:
- Remove Chinese angle brackets `《` and `》` (level-2 headings)
- Remove enclosing braces `{` `}` (level-3 sub-headings)
- Remove square bracket enclosures `【` `】` (level-1 section headers)
- Normalize whitespace

Original text with markers is preserved in the Excel cell; only the translator input is cleaned.

**Step 3: Translate with retry + progressive save**
For each pending row:
1. Call translation API with exponential backoff retry (up to 5 attempts: 1s → 2s → 4s → 8s delays)
2. Write result directly to target column
3. Save the entire workbook immediately after each row
4. If the original file is locked (Excel open), auto-save to a new file `{stem}.translated.xlsx`

This ensures zero progress loss on interrupt or API failure.

**Step 4: Review failures**
After translation completes, check the `.failed.json` dump file for rows that could not be translated (all 5 retries exhausted). Re-process failed items manually or with a different translator.

#### Bundled Script

```bash
# Direct translation with progressive save and crash recovery
python .trae/skills/translation-agent/scripts/translate_direct.py "{excel_path}" [--src-col N] [--tgt-col N] [--output path] [--clean]

# Arguments:
#   excel_path     Path to the Excel file
#   --src-col N    Source (English) column index, 1-based (default: auto-detect)
#   --tgt-col N    Target (Chinese) column index, 1-based (default: auto-detect)
#   --output path   Output path (default: {stem}.translated.xlsx)
#   --clean         Strip BOQ hierarchy markers before translation
```

Script features:
- Auto-detects source/target columns by header names (including BOQ-specific headers)
- Translates only empty target cells (safe to re-run)
- Saves after every row (crash recovery)
- Retries failed translations up to 5 times with exponential backoff
- JSON failure dump (`{stem}.failed.json`) for re-processing
- Optional `--clean` flag for BOQ hierarchy marker stripping
- Falls back to new output file if original is locked

#### Quality Safeguards for Direct Path

Since there is no Markdown review step, apply these safeguards:
1. After translation completes, spot-check 5-10 random rows including headings and long technical rows
2. Run `polish_excel_en2zh.py` with `--glossary` and `--pitfalls` to fix known domain-specific errors
3. Search the target column for repeated-character corruption patterns: `总总`, `表表`, `门门`, `具体具体`
4. Check `references/known-pitfalls.md` for common mistranslation patterns in BOQ/engineering text
5. If corruption is found, fix in Excel directly or export to Markdown for a quick review pass

---

### Stage 3: Flash sub-agent first pass (all formats)

The first translation pass is performed by a **Flash sub-agent**. This ensures a high-quality baseline before Pro review.

**Flash agent responsibilities:**
1. Read the source document and established glossary (Stage 2).
2. Produce a complete first-pass translation preserving all formatting, numbering, tables, links, and code blocks.
3. Apply glossary terms consistently throughout the document.
4. Flag any ambiguous or high-risk terms for Pro review.

#### Excel files

Use the bundled script for term extraction (Stage 2), then export to Markdown review draft for the Flash translation pass.

See Stage 2.5 for the Markdown review draft workflow.

#### Markdown / text files

The Flash sub-agent translates directly, preserving all markdown structure.

#### Other file types (DOCX, PDF, etc.)

Extract text content first using the appropriate processor, then pass to Flash sub-agent for translation.

### Stage 4: Pro sub-agent review & polish

After the Flash first pass, dispatch a **Pro sub-agent** to perform the second-pass review and polish.

**Pro agent responsibilities:**
1. Review Flash output for accuracy, terminology drift, and fluency issues.
2. Fix domain-specific terminology errors Flash could not resolve.
3. Polish sentence flow to native-professional level.
4. For `refined` mode, produce a final polished version that reads like a native professional translation.

**Manual review checklist (applied to the final AI output):**
1. Accuracy: no omissions, additions, or scope drift.
2. Terminology: glossary terms and NRM-style terms are applied consistently.
3. Fluency: remove machine-translation phrasing and awkward syntax.
4. Register: match the requested style such as technical, formal, business, or narrative.
5. Commercial meaning: check terms that affect quantity, cost, exclusions, obligations, or measurement.

For Excel-origin files that were exported to Markdown:
1. Do all substantive review in Markdown instead of polishing cell-by-cell inside Excel.
2. Correct section headings and trade/package names before reviewing ordinary line items.
3. Search for repeated words, malformed bracket patterns, untranslated fragments, and domain-term mistranslations.
4. Fix repeated line-item patterns in batches so terminology stays stable across the whole file.
5. Keep row alignment intact so the final text can be written back safely.
6. Do not generate a new Excel translation file as an intermediate review artifact if the Markdown draft is still under correction.
7. If a heading or trade label is wrong, fix every matching instance before polishing subordinate rows.
8. For repetitive schedules, prefer source-pattern-based corrections such as `Concrete work -> 混凝土工程` instead of ad hoc one-row rewrites.
9. Cross-check against `references/known-pitfalls.md` for common BOQ/engineering mistranslation patterns (e.g., "Concrete" → "具体的", "Louvre" → "卢浮宫").
10. Treat repeated-token corruption such as `总总总`, `表表表`, `门门`, `具体工作`, or similar machine loops as a blocker that must be cleared before write-back.
11. Treat line items containing route expressions such as `from A to B`, equipment-package names, or long parenthetical clauses as high-risk rows for explicit spot review.
12. For long files, review one semantic chunk at a time, but keep one merged master Markdown file as the final source of truth.
13. Never write chunk outputs back into Excel separately; merge and final-QA them in Markdown first, then perform a single consolidated write-back.

For `refined` mode, explicitly do both steps:
1. Critique the draft translation and note clunky or risky wording.
2. Produce a final polished version that reads like a native professional translation.

### Stage 5: Deliver and verify

When the translation is file-based:
1. If the source was Excel and a Markdown review draft was created, finish Step 4 and Step 5 on the Markdown file first.
2. If the file was chunked for review, merge all corrected chunks back into one final master Markdown file before write-back.
3. Treat the final reviewed Markdown file as the only approved source for write-back.
4. Import the final Markdown result back into Excel once, near the end of the workflow.
5. Save the translated output.
6. Spot-check several rows, especially rows containing glossary terms, headings, and repeated trade items.
7. Verify that high-risk project terminology remains consistent.
8. Explicitly check for duplicated words, broken symbols, untranslated fragments, and corrupted heading translations before delivery.
9. Run a final scan on the Markdown draft for repeated Chinese token loops or obvious corruption patterns before importing back into Excel.
10. After write-back, reopen the output file and verify a small sample of headings, ordinary rows, and long technical rows in the Excel target column.

When the translation is plain text or markdown:
1. Flash sub-agent produces the first-pass translation.
2. Pro sub-agent reviews and polishes.
3. Present the final result or save to the project as requested.

## File-Type Guidance

- Excel (Markdown review path - recommended for quality): use `term extraction -> Flash translation -> Markdown draft -> Stage 4 polish in Markdown -> one-time write-back to Excel`. Best for: BOQ, schedules, cost plans, and files where terminology consistency matters.
- Excel (Direct translation path - large files): for files with 1000+ rows or when speed is the priority, use `translate_direct.py` (Stage 2.6) for direct cell-level translation with progressive save and crash recovery. Spot-check quality after completion.
- Markdown/text: Flash sub-agent first pass, then Pro review, escalate to Pro if needed.
- Large documents: extract terminology first, then translate in batches, then polish section by section.
- Client-facing or contractual content: use `refined` unless the user explicitly wants speed over quality.

## Bundled References

- `references/nrm-terms.md`: decision notes for engineering, BOQ, QS, and NRM-style terminology
- `references/nrm-glossary.json`: reusable starter glossary for Chinese -> English engineering translation (62 terms)
- `references/boq-glossary.json`: extended marine/port construction domain glossary (~600 terms covering preliminaries, dredging, reclamation, quay structures, drainage, electrical, pavements, buildings)
- `references/known-pitfalls.md`: recurring machine translation error patterns with corrections for BOQ/engineering text

## Dependencies

- Python 3.8+
- `pandas`
- `openpyxl`
- `jieba`
