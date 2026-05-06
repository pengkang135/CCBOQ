---
name: baoyu-format-markdown
description: Formats plain text or markdown files with frontmatter, titles, summaries, headings, bold, lists, and code blocks. Use when user asks to "format markdown", "beautify article", "add formatting", or improve article layout.
version: 1.0.0
---

# Markdown Formatter (Trae Native Adaptation)

Transforms plain text or markdown into well-structured, reader-friendly markdown. The goal is to help readers quickly grasp key points, highlights, and structure — without changing any original content.

**Core principle**: Only adjust formatting and fix obvious typos. Never add, delete, or rewrite content. Do all formatting directly in your response or by editing the file using tools.

## Workflow

### Step 1: Analyze Content (Reader's Perspective)
Read the entire content carefully. Think from a reader's perspective: what would help them quickly understand and remember the key information?

Produce an analysis covering these dimensions:
- **Highlights & Key Insights**: Core arguments, surprising facts, memorable quotes.
- **Structure Assessment**: Logical flow, natural section boundaries, long walls of text.
- **Reader-Important Information**: Actionable advice, definitions, buried lists.
- **Formatting Issues**: Missing headings, parallel items written as prose, unformatted code.

### Step 2: Check/Create Frontmatter, Title & Summary
Check for YAML frontmatter (`---` block). Create if missing.
- `title`: Generate a strong, hook-based title (e.g., core argument, reader pain point).
- `summary`: 1 sentence, ~50-80 chars. Concise hook.
- `description`: 2-3 sentences, ~100-200 chars. Richer context.

### Step 3: Format Content
Apply formatting guided by the analysis. The goal is making the content scannable and the key points impossible to miss.

**Formatting toolkit:**
- **Headings**: Natural topic boundaries (`##`, `###`).
- **Bold**: Key conclusions, important terms, core takeaways (`**bold**`).
- **Lists**: Parallel items, feature lists, sequential steps (`- item` or `1. item`).
- **Tables**: Comparisons, structured data.
- **Code**: Commands, technical terms (`` `inline` `` or fenced blocks).
- **Blockquotes**: Notable quotes, important warnings (`> quote`).

**Formatting principles:**
- Do NOT add sentences, explanations, or commentary.
- Do NOT delete or shorten any content.
- Do NOT rephrase or rewrite the author's words.
- Preserve the author's voice, tone, and every word.
- Bold key conclusions and core takeaways.
- Fix obvious typos.

### Step 4: Typography Fixes (Directly apply)
Apply these rules directly to the text:
1. **CJK/English Spacing**: Ensure there is a space between Chinese characters and English words/numbers (e.g., `在 Markdown 中` instead of `在Markdown中`).
2. **Emphasis Fixes**: Fix CJK emphasis/bold punctuation issues.
3. **Quotes**: Use standard fullwidth quotes `“...”` for Chinese context if applicable.

### Step 5: Output
Either rewrite the provided file using the `SearchReplace` or `Write` tools, or output the formatted markdown directly in the chat if the user provided text.
