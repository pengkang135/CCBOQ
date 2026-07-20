"""Outlook COM Fetcher — standalone, reads pipeline_config.yaml.

Usage:
    python outlook_com.py [--config pipeline_config.yaml]

Requires: pip install pywin32 pyyaml
Outlook must be running or auto-started via COM.
"""

import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger("outlook_com")

# ── Constants ──────────────────────────────────────────────────────

FOLDER_MAP = {"inbox": 6, "sent": 5}

SYSTEM_FOLDERS = {
    "deleted items", "outbox", "junk email", "contacts", "calendar",
    "conversation history", "notes", "archive", "journal", "yammer root",
    "tasks", "drafts", "sync issues", "rss feeds", "rss 源",
    "social activity notifications", "conversation action settings",
    "externalcontacts", "files", "对话历史记录", "快速步骤设置",
}

STANDARD_FOLDERS = {"inbox", "sent items"}

ATTACH_SKIP_PATTERNS = [
    re.compile(r"^image\d{3,}\.png$", re.IGNORECASE),
    re.compile(r"^image\d{3,}\.jpg$", re.IGNORECASE),
    re.compile(r"^temp\d+", re.IGNORECASE),
]

ENTRYID_SUFFIX_RE = re.compile(r"_[0-9A-Fa-f]{8}$")


# ── Helpers ────────────────────────────────────────────────────────

def _outlook_app():
    import pythoncom
    pythoncom.CoInitialize()
    import win32com.client
    try:
        return win32com.client.GetObject(None, "Outlook.Application")
    except Exception:
        return win32com.client.Dispatch("Outlook.Application")


def _html_to_text(html: str) -> str:
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.skip = False

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.skip = True

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self.skip = False
            if tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
                self.parts.append("\n")

        def handle_data(self, data):
            if not self.skip:
                self.parts.append(data)

    p = P()
    p.feed(html)
    return " ".join("".join(p.parts).split())


def _safe_filename(subject: str, max_len: int = 80) -> str:
    s = "".join(c if c.isalnum() or c in " _.-()" else "_" for c in subject)
    s = re.sub(r"_+", "_", s).strip().strip("._")
    return s[:max_len]


def _should_skip_attachment(filename: str, size: int) -> bool:
    for pat in ATTACH_SKIP_PATTERNS:
        if pat.match(filename):
            return True
    if filename.endswith(".png") and size < 2000:
        return True
    return False


# ── Config loader ──────────────────────────────────────────────────

def load_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "pipeline_config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Cursor management ──────────────────────────────────────────────

def get_cursor(db_path: str, key: str) -> str | None:
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS cursors (source TEXT PRIMARY KEY, position TEXT, updated TEXT)")
    row = conn.execute("SELECT position FROM cursors WHERE source = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None


def update_cursor(db_path: str, key: str, position: str):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS cursors (source TEXT PRIMARY KEY, position TEXT, updated TEXT)")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO cursors(source, position, updated) VALUES (?, ?, ?)",
        (key, position, now),
    )
    conn.commit()
    conn.close()


# ── Folder resolution ──────────────────────────────────────────────

def _find_subfolder(parent, name: str):
    name_lower = name.lower()
    for f in parent.Folders:
        if f.Name.lower() == name_lower:
            return f
    for f in parent.Folders:
        try:
            result = _find_subfolder(f, name)
            if result:
                return result
        except Exception:
            pass
    return None


def resolve_folder(ns, folder_name: str):
    if folder_name in FOLDER_MAP:
        return ns.GetDefaultFolder(FOLDER_MAP[folder_name])
    inbox = ns.GetDefaultFolder(6)
    result = _find_subfolder(inbox, folder_name)
    if result:
        return result
    for i in range(1, 20):
        try:
            top = ns.Folders.Item(i)
            if top.Name.lower() == folder_name.lower():
                return top
            result = _find_subfolder(top, folder_name)
            if result:
                return result
        except Exception:
            break
    return None


def discover_folders(ns) -> list[str]:
    discovered = []
    inbox = ns.GetDefaultFolder(6)
    for f in inbox.Folders:
        name_lower = f.Name.lower()
        if name_lower not in SYSTEM_FOLDERS and name_lower not in STANDARD_FOLDERS:
            try:
                if f.Items.Count > 0:
                    discovered.append(f.Name)
            except Exception:
                pass
            try:
                for sub in f.Folders:
                    if sub.Name.lower() not in SYSTEM_FOLDERS and sub.Name.lower() not in STANDARD_FOLDERS:
                        try:
                            if sub.Items.Count > 0:
                                discovered.append(sub.Name)
                        except Exception:
                            pass
            except Exception:
                pass

    for i in range(1, 20):
        try:
            top = ns.Folders.Item(i)
            for f in top.Folders:
                if f.Name.lower() not in SYSTEM_FOLDERS and f.Name.lower() not in STANDARD_FOLDERS:
                    try:
                        if f.Items.Count > 0 and f.Name not in discovered:
                            discovered.append(f.Name)
                    except Exception:
                        pass
        except Exception:
            break

    return discovered


# ── Email saving ───────────────────────────────────────────────────

def _find_existing_dir(dl: Path, folder_name: str, dt: str, safe_subj: str, eid: str) -> Path | None:
    month = dt[:7]
    base = dl / folder_name / month
    if not base.exists():
        return None

    if eid and len(eid) >= 8:
        exact = base / f"{dt}_{safe_subj}_{eid[-8:]}"
        if exact.exists():
            return exact

    for candidate in base.iterdir():
        if not candidate.is_dir():
            continue
        if not candidate.name.startswith(f"{dt}_{safe_subj}"):
            continue
        meta_path = candidate / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("entry_id") == eid:
                return candidate
        except Exception:
            pass

    no_suffix = base / f"{dt}_{safe_subj}"
    if no_suffix.exists():
        return no_suffix

    return None


def save_email(msg, download_dir: Path, config: dict) -> dict:
    paths = {}
    try:
        subject = str(msg.Subject or "(no subject)")[:500]
        sender_name = str(msg.SenderName or "")
        sender_email = str(msg.SenderEmailAddress or "")
        received_iso = msg.ReceivedTime.isoformat() if msg.ReceivedTime else ""
        body = str(msg.Body or "")[:2000] or _html_to_text(str(msg.HTMLBody or ""))[:2000]
        to_addr = str(msg.To or "")[:1000]
        cc_addr = str(msg.CC or "")[:500]
        eid = str(getattr(msg, "EntryID", ""))

        dt = re.sub(r"[T ].*", "", received_iso)
        safe_subj = _safe_filename(subject)
        short_id = "_" + eid[-8:] if len(eid) >= 8 else ""

        existing = _find_existing_dir(download_dir, folder_name := "", dt, safe_subj, eid)  # folder_name set later
    except Exception:
        return paths

    # Note: folder_name is set by caller; we receive it as parameter but don't use it for path building here
    # The caller passes folder_name — let me restructure...
    # Actually, let me simplify: save_email receives folder from the fetch loop

    return paths


# ── Main fetch logic ───────────────────────────────────────────────

def fetch_folder(ns, folder_name: str, download_dir: Path, db_path: str,
                 cursor: str | None, max_per_run: int, config: dict) -> tuple[list, str]:
    outlook = None
    try:
        outlook = _outlook_app()
        ns = outlook.GetNamespace("MAPI")
        folder = resolve_folder(ns, folder_name)
        if folder is None:
            logger.warning(f"Folder '{folder_name}' not found, skip")
            return [], cursor or ""

        msgs = folder.Items
        msgs.Sort("[ReceivedTime]", False)

        if cursor:
            cursor_date = re.sub(r"T.*", "", cursor)
            try:
                msgs = msgs.Restrict(f"[ReceivedTime] > '{cursor_date}'")
            except Exception:
                pass

        items = []
        newest = cursor or ""

        for msg in msgs:
            if len(items) >= max_per_run:
                break
            try:
                received = msg.ReceivedTime
                received_iso = received.isoformat() if received else ""
            except Exception:
                continue

            if not received_iso:
                continue

            try:
                subject = str(msg.Subject or "(no subject)")[:500]
            except Exception:
                subject = "(no subject)"

            body_text = ""
            try:
                if msg.Body:
                    body_text = str(msg.Body)[:2000]
                elif msg.HTMLBody:
                    body_text = _html_to_text(str(msg.HTMLBody))[:2000]
            except Exception:
                pass

            try:
                sender_name = msg.SenderName or ""
                sender_email = msg.SenderEmailAddress or ""
            except Exception:
                sender_name = ""
                sender_email = ""

            to_addr = ""
            cc_addr = ""
            try:
                to_addr = str(msg.To or "")[:1000]
                cc_addr = str(msg.CC or "")[:500]
            except Exception:
                pass

            # Save email files
            saved_paths = _save_email_files(
                msg, subject, sender_name, sender_email, received_iso,
                folder_name, body_text, to_addr, cc_addr, download_dir, config,
            )

            items.append({
                "subject": subject,
                "sender_name": sender_name,
                "sender_email": sender_email,
                "received": received_iso,
                "folder": folder_name,
                "body": body_text,
                "to": to_addr,
                "cc": cc_addr,
                "attachments": saved_paths.get("attachments", []),
                "entry_id": str(getattr(msg, "EntryID", "")),
                "_saved_paths": saved_paths,
            })

            if received_iso > newest:
                newest = received_iso

        logger.info(f"Folder '{folder_name}': {len(items)} fetched")
        return items, newest
    except Exception as e:
        logger.error(f"Folder '{folder_name}' error: {e}")
        return [], cursor or ""
    finally:
        if outlook:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _save_email_files(msg, subject, sender_name, sender_email, received_iso,
                      folder_name, body_text, to_addr, cc_addr,
                      download_dir: Path, config: dict) -> dict:
    paths = {"attachments": []}
    try:
        dt = re.sub(r"[T ].*", "", received_iso)
        safe_subj = _safe_filename(subject)
        eid = str(getattr(msg, "EntryID", ""))
        short_id = "_" + eid[-8:] if len(eid) >= 8 else ""

        msg_dir = download_dir / folder_name / dt[:7] / f"{dt}_{safe_subj}{short_id}"
        msg_dir.mkdir(parents=True, exist_ok=True)

        # Save .msg original
        if config.get("outlook", {}).get("save_originals", True):
            try:
                msg_path = msg_dir / "original.msg"
                if not msg_path.exists():
                    msg.SaveAs(str(msg_path), 3)
                    paths["original"] = str(msg_path)
            except Exception as e:
                logger.warning(f"Failed to save .msg: {e}")

        # Save attachments
        att_names = []
        if config.get("outlook", {}).get("save_attachments", True):
            try:
                att_count = msg.Attachments.Count if msg.Attachments else 0
            except Exception:
                att_count = 0

            for i in range(1, att_count + 1):
                try:
                    att = msg.Attachments.Item(i)
                    fname = att.FileName
                    fsize = att.Size
                    if _should_skip_attachment(fname, fsize):
                        continue
                    att_path = msg_dir / fname
                    if not att_path.exists():
                        att.SaveAsFile(str(att_path))
                    att_names.append(fname)
                except Exception as e:
                    logger.warning(f"Failed attachment: {e}")

        paths["attachments"] = att_names

        # Write metadata.json
        meta = {
            "subject": subject,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "received": received_iso,
            "folder": folder_name,
            "body": body_text[:500],
            "attachments": att_names,
            "to": to_addr,
            "cc": cc_addr,
            "entry_id": eid,
        }
        meta_path = msg_dir / "metadata.json"
        if not meta_path.exists():
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    except Exception as e:
        logger.warning(f"Save error: {e}")

    return paths


# ── Entry point ────────────────────────────────────────────────────

def run(config_path: str = None):
    config = load_config(config_path)
    oc = config.get("outlook", {})
    if not oc.get("enabled", True):
        logger.info("Outlook fetcher disabled")
        return []

    download_dir = Path(oc["download_dir"])
    folders = list(oc.get("folders", ["inbox", "sent"]))
    auto_discover = oc.get("auto_discover_folders", False)
    max_per_run = oc.get("max_per_run", 30)
    pipeline_dir = Path(__file__).resolve().parent
    db_path = str(pipeline_dir / "db" / "state.sqlite")

    # Discover folders
    if auto_discover:
        try:
            outlook = _outlook_app()
            ns = outlook.GetNamespace("MAPI")
            discovered = discover_folders(ns)
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception as e:
            logger.warning(f"Folder discovery failed: {e}")
            discovered = []
        all_folders = list(dict.fromkeys(folders + discovered))
    else:
        all_folders = folders

    # Need COM app for fetch
    outlook = _outlook_app()
    ns = outlook.GetNamespace("MAPI")

    all_items = []
    for folder_name in all_folders:
        cursor = get_cursor(db_path, f"outlook_{folder_name}")
        items, newest = fetch_folder(ns, folder_name, download_dir, db_path, cursor, max_per_run, config)
        if items and newest:
            update_cursor(db_path, f"outlook_{folder_name}", newest)
        all_items.extend(items)

    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:
        pass

    all_items.sort(key=lambda x: x.get("received", ""))
    logger.info(f"Total: {len(all_items)} emails from {len(all_folders)} folders")
    return all_items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run()
