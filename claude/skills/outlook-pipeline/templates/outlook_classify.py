"""Outlook Email Classifier — standalone, reads pipeline_config.yaml.

Generates:
  {download_dir}/_index/     → Markdown indexes by category
  {download_dir}/_shortcuts/ → Windows .lnk shortcuts by category
  {download_dir}/_junctions/ → NTFS Junction points (ByCategory view)

Usage:
    python outlook_classify.py [--config pipeline_config.yaml]
"""

import json
import logging
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger("outlook_classify")

ENTRYID_SUFFIX_RE = re.compile(r"_[0-9A-Fa-f]{8}$")

# ── CSS for Markdown indexes ───────────────────────────────────────

INDEX_CSS = """<style>
body { font-family: 'Microsoft YaHei', sans-serif; font-size: 14px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; }
th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }
th { background: #f5f5f5; font-weight: bold; }
tr:hover { background: #fafafa; }
h1 { border-bottom: 2px solid #333; padding-bottom: 4px; }
h2 { margin-top: 24px; color: #333; }
h3 { color: #555; }
a { color: #0366d6; text-decoration: none; }
a:hover { text-decoration: underline; }
.summary-box { background: #f0f7ff; border-left: 4px solid #0366d6; padding: 12px; margin: 12px 0; }
</style>
"""


# ── Config ─────────────────────────────────────────────────────────

def load_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "pipeline_config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Classifier engine ──────────────────────────────────────────────

class Classifier:
    """Rule-based email classifier. All rules come from config."""

    def __init__(self, clf_config: dict):
        self.mep_pats = [re.compile(p, re.IGNORECASE) for p in clf_config.get("mep_keywords", [])]
        self.internal_domains = clf_config.get("internal_domains", [])
        self.internal_names = clf_config.get("internal_names", [])
        self.supplier_pats = [re.compile(p, re.IGNORECASE) for p in clf_config.get("supplier_keywords", [
            r"\bquotation\b|\bquote\b|报价|RFQ|budgetary.*price|financial.*proposal|commercial.*proposal",
            r"供应商|厂家.*报价|投标|保费测算|保费.*估",
            r"tender|bid.*proposal",
        ])]
        self.subcat_rules = {}
        for cat, patterns in clf_config.get("subcategory_rules", {}).items():
            self.subcat_rules[cat] = [re.compile(p, re.IGNORECASE) for p in patterns]
        self.attach_signals = clf_config.get("attach_signals", {})
        self.outgoing_senders = clf_config.get("outgoing_rfq_senders", [])
        self.reply_pats = [re.compile(p, re.IGNORECASE) for p in clf_config.get("reply_patterns", ["Re", "回复", "答复", "转发", "Fwd"])]
        self.quotation_attach_pats = [re.compile(p, re.IGNORECASE) for p in clf_config.get("quotation_attach_patterns", ["quotation", "报价"])]
        self.top_level_order = clf_config.get("top_level_order", ["MEP", "内部", "供应商", "外部"])
        self.subcat_order = clf_config.get("subcat_order", [])

    def classify(self, email: dict) -> dict:
        subj = email.get("subject", "")
        sender_email = email.get("sender_email", "")
        sender_name = email.get("sender_name", "")
        body = email.get("body", "")
        attachments = email.get("attachments", [])
        folder = email.get("folder", "")
        to_field = email.get("to", "")
        search_text = f"{subj} {body} {' '.join(attachments)}"

        top_level = self._classify_top(email, search_text)
        subcat = self._classify_subcat(email, top_level, search_text)

        return {"top_level": top_level, "sub_category": subcat}

    def _classify_top(self, email: dict, search_text: str) -> str:
        folder = email.get("folder", "")
        if folder == "sent":
            return self._classify_sent_top(email, search_text)

        if any(p.search(search_text) for p in self.mep_pats):
            return "MEP"

        sender_email = email.get("sender_email", "")
        sender_name = email.get("sender_name", "")
        sender_text = f"{sender_email} {sender_name}"
        if any(d in sender_text for d in self.internal_domains):
            return "内部"
        if any(re.search(n, sender_text, re.IGNORECASE) for n in self.internal_names):
            return "内部"

        subj = email.get("subject", "")
        body = email.get("body", "")
        if any(p.search(f"{subj} {body}") for p in self.supplier_pats):
            return "供应商"

        return "外部"

    def _classify_sent_top(self, email: dict, search_text: str) -> str:
        if any(p.search(search_text) for p in self.mep_pats):
            return "MEP"

        to_field = email.get("to", "")
        cc_field = email.get("cc", "")
        recipients = f"{to_field} {cc_field}"

        if any(d in recipients for d in self.internal_domains):
            return "内部"
        if any(re.search(n, recipients, re.IGNORECASE) for n in self.internal_names):
            return "内部"

        subj = email.get("subject", "")
        body = email.get("body", "")
        if any(p.search(f"{subj} {body}") for p in self.supplier_pats):
            return "供应商"

        return "外部"

    def _classify_subcat(self, email: dict, top_level: str, search_text: str) -> str:
        subj = email.get("subject", "")
        body = email.get("body", "")
        attachments = email.get("attachments", [])

        if top_level == "内部" and self._is_query_doc(email):
            return "询价文件"

        for cat_name, patterns in self.subcat_rules.items():
            if any(p.search(subj) or p.search(body) for p in patterns):
                return cat_name

        # Attachment fallback
        for cat_name, signals in self.attach_signals.items():
            for fname in attachments:
                if any(re.search(s, fname, re.IGNORECASE) for s in signals):
                    return cat_name

        return "其他"

    def _is_query_doc(self, email: dict) -> bool:
        sender_name = email.get("sender_name", "")
        sender_email = email.get("sender_email", "")
        to_field = email.get("to", "")

        is_outgoing = any(re.search(s, f"{sender_name} {sender_email}", re.IGNORECASE) for s in self.outgoing_senders)
        if not is_outgoing:
            return False

        to_self = any(re.search(s, to_field, re.IGNORECASE) for s in self.outgoing_senders)
        empty_to = not to_field.strip()
        return to_self or empty_to


# ── Email scanner ──────────────────────────────────────────────────

def scan_emails(download_dir: Path) -> list[dict]:
    emails = []
    for meta_path in sorted(download_dir.rglob("metadata.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            email_dir = meta_path.parent
            meta["_dir"] = str(email_dir)
            meta["_rel"] = str(email_dir.relative_to(download_dir))
            meta["_has_entryid"] = bool(ENTRYID_SUFFIX_RE.search(email_dir.name))
            emails.append(meta)
        except Exception:
            logger.warning(f"Failed to read {meta_path}")

    # Deduplicate: same folder + date + subject → prefer EntryID-suffixed
    groups: dict[tuple, list[dict]] = {}
    for em in emails:
        key = (em.get("folder", ""), em.get("received", "")[:10], em.get("subject", ""))
        groups.setdefault(key, []).append(em)

    deduped = []
    for key, group in groups.items():
        with_eid = [e for e in group if e.get("_has_entryid")]
        deduped.extend(with_eid if with_eid else group)

    return deduped


# ── Safe name helper ───────────────────────────────────────────────

def _safe_name(s: str, max_len: int = 60) -> str:
    r = "".join(c if c.isalnum() or c in " _.-()" else "_" for c in s)
    r = r.strip().strip("._")
    return r[:max_len]


# ── Markdown index generation ──────────────────────────────────────

def _build_email_row(em: dict, index_dir: Path) -> str:
    d = em.get("received", "")[:10]
    subj = em.get("subject", "")[:100]
    sender = em.get("sender_name", "") or em.get("sender_email", "")
    atts = em.get("attachments", [])
    att_str = ", ".join(atts[:5]) if atts else "无"
    if len(atts) > 5:
        att_str += f" ...共{len(atts)}个"

    email_dir = Path(em.get("_dir", ""))
    orig = email_dir / "original.msg" if email_dir else None
    view_link = ""
    if orig and orig.exists():
        orig_rel = orig.relative_to(index_dir.parent) if index_dir.parent else ""
        view_link = f" [打开]({orig_rel})"

    return f"| {d} | {sender[:20]} | {subj}{view_link} | {att_str[:80]} |"


def write_indexes(emails: list[dict], download_dir: Path, classifier: Classifier) -> list[str]:
    index_dir = download_dir / "_index"

    # Clean old non-category structure
    if index_dir.exists():
        import shutil
        for old_dir in list(index_dir.iterdir()):
            if old_dir.is_dir() and old_dir.name not in set(classifier.top_level_order) and not old_dir.name.startswith("_"):
                shutil.rmtree(str(old_dir))
    index_dir.mkdir(parents=True, exist_ok=True)

    for em in emails:
        em["_classification"] = classifier.classify(em)

    by_toplevel = defaultdict(lambda: defaultdict(list))
    for em in emails:
        c = em["_classification"]
        by_toplevel[c["top_level"]][c["sub_category"]].append(em)

    generated = []

    for tl_name in classifier.top_level_order:
        subcats = by_toplevel.get(tl_name, {})
        if not subcats:
            continue

        safe_tl = _safe_name(tl_name)
        tl_dir = index_dir / safe_tl
        tl_dir.mkdir(parents=True, exist_ok=True)

        total = sum(len(v) for v in subcats.values())
        lines = [INDEX_CSS, f"# {tl_name}", ""]
        lines.append(f'<div class="summary-box">共 <b>{total}</b> 封邮件，{len(subcats)} 个子类别</div>')
        lines.append("")

        for sc_name in classifier.subcat_order:
            sc_emails = subcats.get(sc_name, [])
            if not sc_emails:
                continue
            sc_emails.sort(key=lambda e: e.get("received", ""), reverse=True)
            lines.append(f"## {sc_name} ({len(sc_emails)})")
            lines.append("")
            lines.append("| 日期 | 发件人 | 主题 | 附件 |")
            lines.append("|------|--------|------|------|")
            for em in sc_emails:
                lines.append(_build_email_row(em, index_dir))
            lines.append("")

        idx_file = tl_dir / f"{safe_tl}.md"
        idx_file.write_text("\n".join(lines), encoding="utf-8")
        generated.append(str(idx_file))
        logger.info(f"Index: {tl_name} ({total} emails)")

    # README
    readme = index_dir / "README.md"
    now = datetime.now(timezone.utc).isoformat()
    summary_lines = [
        INDEX_CSS,
        "# 邮件分类索引",
        f"> 自动生成于 {now}",
        "",
        "## 统计概览",
        f"- **总邮件数**: {len(emails)}",
        f"- **一级分类数**: {len(by_toplevel)}",
        "",
        "## 导航",
    ]
    for tl_name in classifier.top_level_order:
        subcats = by_toplevel.get(tl_name, {})
        if not subcats:
            continue
        safe_tl = _safe_name(tl_name)
        total = sum(len(v) for v in subcats.values())
        summary_lines.append(f"### {tl_name} ({total}封)")
        for sc_name in classifier.subcat_order:
            sc_emails = subcats.get(sc_name, [])
            if not sc_emails:
                continue
            summary_lines.append(f"- [{sc_name}]({safe_tl}/{safe_tl}.md) ({len(sc_emails)}封)")
        summary_lines.append("")

    readme.write_text("\n".join(summary_lines), encoding="utf-8")
    generated.append(str(readme))

    return generated


# ── Shortcut generation ────────────────────────────────────────────

def _shortcut_name(em: dict) -> str:
    d = em.get("received", "")[:10]
    sender = (em.get("sender_name", "") or em.get("sender_email", ""))[:25]
    subj = em.get("subject", "no subject")[:50]
    return _safe_name(f"{d}_{sender}_{subj}", max_len=120) + ".lnk"


def write_shortcuts(emails: list[dict], download_dir: Path, classifier: Classifier) -> list[str]:
    if sys.platform != "win32":
        logger.info("Shortcuts only supported on Windows, skipping")
        return []

    lnk_dir = download_dir / "_shortcuts"
    if lnk_dir.exists():
        import shutil
        shutil.rmtree(str(lnk_dir))
    lnk_dir.mkdir(parents=True, exist_ok=True)

    for em in emails:
        if "_classification" not in em:
            em["_classification"] = classifier.classify(em)

    by_toplevel = defaultdict(lambda: defaultdict(list))
    for em in emails:
        c = em["_classification"]
        by_toplevel[c["top_level"]][c["sub_category"]].append(em)

    shortcuts = []
    for tl_name in classifier.top_level_order:
        subcats = by_toplevel.get(tl_name, {})
        if not subcats:
            continue
        for sc_name in classifier.subcat_order:
            sc_emails = sorted(subcats.get(sc_name, []), key=lambda e: e.get("received", ""), reverse=True)
            for em in sc_emails:
                link_name = _shortcut_name(em)
                link_path = lnk_dir / tl_name / sc_name / link_name
                link_path.parent.mkdir(parents=True, exist_ok=True)
                shortcuts.append((str(link_path), em.get("_dir", "")))

    if not shortcuts:
        return []

    ps_lines = ['$ws = New-Object -ComObject WScript.Shell']
    for link_path, target_dir in shortcuts:
        ps_lines.append(f'$sc = $ws.CreateShortcut("{link_path}")')
        ps_lines.append(f'$sc.TargetPath = "{target_dir}"')
        ps_lines.append('$sc.Save()')

    ps_script = "\n".join(ps_lines)
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, timeout=120, check=True,
        )
        logger.info(f"Shortcuts: {len(shortcuts)} created in {lnk_dir}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Shortcut creation failed: {e.stderr.decode(errors='replace')[:500]}")
        return []

    return [str(lnk_dir)]


# ── Junction generation ────────────────────────────────────────────

def write_junctions(emails: list[dict], download_dir: Path, classifier: Classifier) -> list[str]:
    """Create NTFS Junction points: _junctions/ByCategory/{top_level}/{sub_cat}/{email_name}"""
    if sys.platform != "win32":
        logger.info("Junctions only supported on Windows, skipping")
        return []

    jn_dir = download_dir / "_junctions" / "ByCategory"
    if jn_dir.exists():
        import shutil
        shutil.rmtree(str(jn_dir))
    jn_dir.mkdir(parents=True, exist_ok=True)

    for em in emails:
        if "_classification" not in em:
            em["_classification"] = classifier.classify(em)

    count = 0
    for em in emails:
        c = em["_classification"]
        tl = c.get("top_level", "其他")
        sc = c.get("sub_category", "其他")
        em_dir = Path(em.get("_dir", ""))

        if not em_dir or not em_dir.exists():
            continue

        jn_name = em_dir.name
        jn_path = jn_dir / tl / sc / jn_name
        if jn_path.exists():
            continue

        jn_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(jn_path), str(em_dir)],
                capture_output=True, check=True,
            )
            count += 1
        except subprocess.CalledProcessError as e:
            logger.warning(f"Junction failed: {jn_name}: {e.stderr.decode(errors='replace')[:200]}")

    logger.info(f"Junctions: {count} created in {jn_dir}")
    return [str(jn_dir)] if count > 0 else []


# ── Entry point ────────────────────────────────────────────────────

def run(config_path: str = None):
    config = load_config(config_path)
    oc = config.get("outlook", {})
    download_dir = Path(oc["download_dir"])

    if not download_dir.exists():
        logger.warning(f"Download dir not found: {download_dir}")
        return []

    emails = scan_emails(download_dir)
    if not emails:
        logger.info("No emails with metadata.json found")
        return []

    clf_config = config.get("classification", {})
    classifier = Classifier(clf_config)

    logger.info(f"Classifying {len(emails)} emails...")
    idx_files = write_indexes(emails, download_dir, classifier)
    lnk_files = write_shortcuts(emails, download_dir, classifier)
    jn_files = write_junctions(emails, download_dir, classifier)

    return idx_files + lnk_files + jn_files


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run()
