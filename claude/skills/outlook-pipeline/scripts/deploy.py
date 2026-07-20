"""Outlook Pipeline Deployer — interactive setup, zero-edit deployment.

Usage:
    python deploy.py                    # Interactive deploy
    python deploy.py --non-interactive --config config.yaml  # CI/scripted
    python deploy.py --validate         # Check existing deployment health
    python deploy.py --uninstall        # Remove pipeline (keeps data)

Configuration is written to pipeline_config.yaml at the deployment root.
Templates are copied from ../templates/ relative to this script.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"

# ── Windows Task Scheduler XML template ─────────────────────────────
TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Outlook Email Pipeline — fetch &amp; classify</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT{interval_minutes}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start_boundary}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user_sid}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{python_exe}</Command>
      <Arguments>{pipeline_py}</Arguments>
      <WorkingDirectory>{pipeline_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

SYSTEMD_UNIT = """[Unit]
Description=Outlook Email Pipeline
After=network.target

[Service]
Type=oneshot
ExecStart={python_exe} {pipeline_py}
WorkingDirectory={pipeline_dir}
User={user}
Environment=PYTHONUNBUFFERED=1
"""

SYSTEMD_TIMER = """[Unit]
Description=Outlook Email Pipeline Timer

[Timer]
OnBootSec=2min
OnUnitActiveSec={interval_sec}s
AccuracySec=10s
Persistent=true

[Install]
WantedBy=timers.target
"""

# ── Default classification rules ───────────────────────────────────

DEFAULT_CLASSIFICATION = {
    "top_level_order": ["MEP", "内部", "供应商", "外部"],
    "subcat_order": ["询价文件", "报价文件", "工程量清单", "设计图纸", "澄清往来", "内部通知", "其他"],
    "mep_keywords": [
        "MEP", "机电", "暖通", "给排水", "消防", "fire\\s*fighting",
        "HVAC", "plumbing", "electrical", "配电", "变压器",
        "generator", "DG\\s*set", "空调", "ventilation",
        "电缆", "cable\\s*(tray|trunking|ladder)", "KV",
        "mechanical", "fire\\s*alarm", "fire\\s*pump", "fire\\s*hydrant",
    ],
    "subcategory_rules": {
        "询价文件": ["RFQ", "询价", "inquiry.*(document|doc)", "询价函"],
        "报价文件": ["quotation", "quote", "报价", "budgetary.*price", "financial.*proposal", "commercial.*proposal", "DG\\s*set", "保费", "测算"],
        "工程量清单": ["BOQ", "BQ", "schedule\\s*of\\s*prices", "工程量", "bill\\s*of\\s*quantit"],
        "设计图纸": ["drawing", "图纸", "dwg", "specification", "tender", "招标", "ground\\s*improvement", "地基处理"],
        "澄清往来": ["clarification", "query\\s*management", "澄清", "query.*form"],
        "内部通知": ["安排", "通知", "周报", "月报", "会议", "meeting", "minutes", "纪要", "报销", "审批", "请假"],
    },
    "attach_signals": {
        "询价文件": ["询价", "RFQ", "inquiry"],
        "报价文件": ["报价单", "quotation", "price.*list", "报价.*单", "financial.*proposal", "commercial.*proposal"],
        "工程量清单": ["BOQ", "BQ", "schedule.*price", "工程量"],
        "设计图纸": ["drawing", "图纸", "\\\\.dwg$", "specification", "tender"],
        "澄清往来": ["query.*form", "clarification", "question"],
    },
    "outgoing_rfq_senders": [
        "Peng Kang", "彭康", "pengkang", "pkang",
        "Marketing Department.*Public", "noreply", "no-reply",
    ],
    "reply_patterns": ["Re", "回复", "答复", "AW", "WG", "转发", "Fwd"],
    "quotation_attach_patterns": ["quotation", "报价", "price\\s*list", "financial", "commercial"],
}


# ── Interactive prompts ────────────────────────────────────────────

def ask(prompt: str, default: str = "", validate: callable = None) -> str:
    """Prompt with default value support."""
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        val = raw if raw else default
        if not val:
            print("  (required)")
            continue
        if validate:
            err = validate(val)
            if err:
                print(f"  {err}")
                continue
        return val


def ask_path(prompt: str, default: str = "", must_exist: bool = False) -> str:
    def _check(v):
        p = Path(v)
        if must_exist and not p.exists():
            return f"Path does not exist: {v}"
        return None
    return ask(prompt, default, _check)


def ask_yn(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{d}]: ").strip().lower()
    if not raw:
        return default
    return raw.startswith("y")


# ── Validation ─────────────────────────────────────────────────────

def validate_deployment(pipeline_dir: Path) -> dict:
    """Check health of an existing deployment."""
    results = {
        "config_exists": False,
        "scripts_present": [],
        "scripts_missing": [],
        "cron_active": False,
        "python_deps_ok": True,
        "errors": [],
    }

    config = pipeline_dir / "pipeline_config.yaml"
    results["config_exists"] = config.exists()

    for name in ("outlook_com.py", "outlook_classify.py", "pipeline.py"):
        path = pipeline_dir / name
        if path.exists():
            results["scripts_present"].append(name)
        else:
            results["scripts_missing"].append(name)

    # Check Python deps
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        results["python_deps_ok"] = False
        results["errors"].append("Missing pywin32 — run: pip install pywin32")

    try:
        import yaml  # noqa: F401
    except ImportError:
        results["python_deps_ok"] = False
        results["errors"].append("Missing pyyaml — run: pip install pyyaml")

    # Check cron (Windows)
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["schtasks", "/query", "/tn", "OutlookPipeline"],
                capture_output=True, text=True,
            )
            results["cron_active"] = r.returncode == 0
        except Exception:
            pass
    else:
        try:
            r = subprocess.run(
                ["systemctl", "is-enabled", "outlook-pipeline.timer"],
                capture_output=True, text=True,
            )
            results["cron_active"] = "enabled" in r.stdout
        except Exception:
            pass

    return results


# ── Deployment ─────────────────────────────────────────────────────

def get_user_sid() -> str:
    """Get current user SID on Windows."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def deploy_windows_scheduler(pipeline_dir: Path, config: dict):
    """Create Windows Task Scheduler job."""
    interval = int(config.get("interval_minutes", 30))
    python_exe = sys.executable
    pipeline_py = str(pipeline_dir / "pipeline.py")
    user_sid = get_user_sid()

    now = datetime.now()
    start_boundary = now.strftime("%Y-%m-%dT%H:%M:%S")

    xml = TASK_XML.format(
        interval_minutes=interval,
        start_boundary=start_boundary,
        user_sid=user_sid,
        python_exe=python_exe,
        pipeline_py=pipeline_py,
        pipeline_dir=str(pipeline_dir),
    )

    xml_path = pipeline_dir / "_task.xml"
    xml_path.write_text(xml, encoding="utf-16")

    r = subprocess.run(
        ["schtasks", "/create", "/tn", "OutlookPipeline", "/xml", str(xml_path), "/f"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"  WARNING: Failed to create scheduled task:\n{r.stderr}")
    else:
        print(f"  Scheduled task created (every {interval} min)")

    xml_path.unlink(missing_ok=True)


def deploy_cron(pipeline_dir: Path, config: dict):
    """Create cron/systemd timer on Linux."""
    interval = int(config.get("interval_minutes", 30))
    interval_sec = interval * 60
    python_exe = sys.executable
    pipeline_py = str(pipeline_dir / "pipeline.py")
    user = os.environ.get("USER", os.environ.get("LOGNAME", "unknown"))

    # Try systemd first
    try:
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)

        unit = SYSTEMD_UNIT.format(
            python_exe=python_exe, pipeline_py=pipeline_py,
            pipeline_dir=str(pipeline_dir), user=user,
        )
        timer = SYSTEMD_TIMER.format(interval_sec=interval_sec)

        (unit_dir / "outlook-pipeline.service").write_text(unit)
        (unit_dir / "outlook-pipeline.timer").write_text(timer)

        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "outlook-pipeline.timer"], capture_output=True)
        subprocess.run(["systemctl", "--user", "start", "outlook-pipeline.timer"], capture_output=True)
        print(f"  systemd timer created (every {interval} min)")
    except Exception:
        # Fall back to crontab
        cron_line = f"*/{interval} * * * * cd {pipeline_dir} && {python_exe} {pipeline_py}"
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = r.stdout.strip() if r.returncode == 0 else ""
        if "outlook-pipeline" not in existing:
            new = existing + "\n# outlook-pipeline\n" + cron_line + "\n" if existing else cron_line + "\n"
            subprocess.run(["crontab", "-"], input=new, text=True)
            print(f"  crontab entry added (every {interval} min)")
        else:
            print("  crontab entry already exists")


def deploy(pipeline_dir: Path, config: dict, interactive: bool = True):
    """Main deploy routine."""
    print(f"\nDeploying Outlook Pipeline to: {pipeline_dir}\n")

    pipeline_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy scripts from templates
    print("── Copying scripts ──")
    scripts = ["outlook_com.py", "outlook_classify.py", "pipeline.py"]
    for name in scripts:
        src = TEMPLATES_DIR / name
        dst = pipeline_dir / name
        shutil.copy2(src, dst)
        print(f"  {name}")

    # 2. Write config
    print("\n── Writing config ──")
    import yaml as _yaml
    config_path = pipeline_dir / "pipeline_config.yaml"
    config["_deployed_at"] = datetime.now().isoformat()
    config["_deployed_by"] = "outlook-pipeline-skill"
    with open(config_path, "w", encoding="utf-8") as f:
        _yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False)
    print(f"  pipeline_config.yaml")

    # 3. Create data dirs
    print("\n── Creating data directories ──")
    dl = Path(config.get("download_dir", ""))
    if dl and not dl.exists():
        dl.mkdir(parents=True, exist_ok=True)
        print(f"  {dl}")
    db_dir = pipeline_dir / "db"
    db_dir.mkdir(exist_ok=True)
    print(f"  {db_dir}")

    # 4. Setup scheduler
    print("\n── Setting up scheduler ──")
    if sys.platform == "win32":
        deploy_windows_scheduler(pipeline_dir, config)
    else:
        deploy_cron(pipeline_dir, config)

    # 5. Verify Python deps
    print("\n── Checking dependencies ──")
    deps_ok = True
    for mod, name in [("win32com", "pywin32"), ("yaml", "pyyaml")]:
        try:
            __import__(mod)
            print(f"  {name}: OK")
        except ImportError:
            print(f"  {name}: MISSING — run: pip install {name}")
            deps_ok = False

    # 6. Test run
    print("\n── Running first fetch ──")
    r = subprocess.run(
        [sys.executable, str(pipeline_dir / "pipeline.py")],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode == 0:
        print("  First run OK")
    else:
        print(f"  First run returned {r.returncode}")
        if r.stderr:
            print(f"  stderr: {r.stderr[:500]}")

    print(f"\nDone. Pipeline deployed to {pipeline_dir}")
    print(f"Config: {config_path}")
    print(f"Data:   {dl}")


# ── Uninstall ──────────────────────────────────────────────────────

def uninstall(pipeline_dir: Path):
    """Remove pipeline scheduling and scripts."""
    print(f"Uninstalling from {pipeline_dir}")

    if sys.platform == "win32":
        subprocess.run(
            ["schtasks", "/delete", "/tn", "OutlookPipeline", "/f"],
            capture_output=True,
        )
        print("  Removed scheduled task")
    else:
        subprocess.run(
            ["systemctl", "--user", "stop", "outlook-pipeline.timer"],
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "disable", "outlook-pipeline.timer"],
            capture_output=True,
        )
        print("  Removed systemd timer")

    # Remove scripts, keep data
    for name in ("outlook_com.py", "outlook_classify.py", "pipeline.py", "pipeline_config.yaml"):
        (pipeline_dir / name).unlink(missing_ok=True)
    print(f"  Removed scripts (data preserved)")
    print("  To remove data dirs, delete manually: " + str(pipeline_dir))


# ── Interactive config builder ─────────────────────────────────────

def interactive_config() -> dict:
    """Walk user through pipeline configuration."""
    print("\n" + "=" * 60)
    print("  Outlook Email Pipeline — Setup")
    print("=" * 60)
    print("\nThis will deploy an automated Outlook email archive + classifier.\n")

    # ── Paths ──
    print("── Storage Locations ──")
    default_pipeline = str(Path.home() / ".outlook-pipeline")
    pipeline_dir = ask_path("Pipeline install directory", default_pipeline)

    default_dl = str(Path.home() / "OutlookArchive")
    download_dir = ask_path("Email archive directory", default_dl)

    # ── Schedule ──
    print("\n── Schedule ──")
    interval = ask("Fetch interval (minutes)", "30", lambda v: "Must be >= 5" if not v.isdigit() or int(v) < 5 else None)
    max_per_run = ask("Max emails per fetch", "30", lambda v: "Must be >= 1" if not v.isdigit() or int(v) < 1 else None)

    # ── Company identity ──
    print("\n── Company Identity (for internal mail detection) ──")
    domains = ask("Company email domains (comma-separated)", "@mycompany.com")
    names = ask("Internal sender names/patterns (comma-separated)", "First Last")

    internal_domains = [d.strip() for d in domains.split(",") if d.strip()]
    internal_names = [n.strip() for n in names.split(",") if n.strip()]

    # ── Classification ──
    print("\n── Classification Rules ──")
    print("  Default rules provide: MEP / 内部 / 供应商 / 外部 → 7 subcategories")
    use_defaults = ask_yn("Use default classification rules?", True)

    classification = {}
    if use_defaults:
        classification = dict(DEFAULT_CLASSIFICATION)
        classification["internal_domains"] = internal_domains
        classification["internal_names"] = internal_names
    else:
        classification = build_custom_rules(internal_domains, internal_names)

    # ── Folders ──
    print("\n── Outlook Folders ──")
    folders = ask("Folders to monitor (comma-separated, 'auto' for discovery)", "inbox,sent,auto")
    folder_list = [f.strip() for f in folders.split(",") if f.strip()]
    auto_discover = "auto" in folder_list
    if auto_discover:
        folder_list.remove("auto")

    # ── Summary ──
    config = {
        "pipeline": {"interval_minutes": int(interval)},
        "outlook": {
            "enabled": True,
            "download_dir": download_dir,
            "folders": folder_list,
            "auto_discover_folders": auto_discover,
            "max_per_run": int(max_per_run),
            "save_originals": True,
            "save_attachments": True,
        },
        "classification": classification,
    }

    print("\n" + "-" * 40)
    print("Configuration summary:")
    print(f"  Pipeline dir: {pipeline_dir}")
    print(f"  Archive dir:  {download_dir}")
    print(f"  Interval:     {interval} min")
    print(f"  Max/run:      {max_per_run}")
    print(f"  Folders:      {folder_list}" + (" + auto-discover" if auto_discover else ""))
    print(f"  Company:      {internal_domains}")
    print("-" * 40)

    if not ask_yn("\nProceed with deployment?", True):
        print("Aborted.")
        sys.exit(0)

    return config, Path(pipeline_dir)


def build_custom_rules(internal_domains: list, internal_names: list) -> dict:
    """Build custom classification rules interactively."""
    rules = dict(DEFAULT_CLASSIFICATION)
    rules["internal_domains"] = internal_domains
    rules["internal_names"] = internal_names

    print("\n  Enter custom keywords (leave empty to keep defaults):")

    for category in rules["subcategory_rules"]:
        current = ", ".join(rules["subcategory_rules"][category])
        val = input(f"  {category} [{current[:60]}...]: ").strip()
        if val:
            rules["subcategory_rules"][category] = [v.strip() for v in val.split(",")]

    mep_current = ", ".join(rules["mep_keywords"][:6])
    val = input(f"  MEP keywords [{mep_current}...]: ").strip()
    if val:
        rules["mep_keywords"] = [v.strip() for v in val.split(",")]

    return rules


# ── Main ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Outlook Pipeline Deployer")
    parser.add_argument("--pipeline-dir", type=str, help="Pipeline install path")
    parser.add_argument("--config", type=str, help="Path to pre-built config YAML")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--validate", action="store_true", help="Check existing deployment")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    if args.uninstall:
        pd = Path(args.pipeline_dir) if args.pipeline_dir else Path.home() / ".outlook-pipeline"
        if pd.exists():
            uninstall(pd)
        else:
            print(f"Pipeline dir not found: {pd}")
        return

    if args.validate:
        pd = Path(args.pipeline_dir) if args.pipeline_dir else Path.home() / ".outlook-pipeline"
        results = validate_deployment(pd)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    if args.non_interactive and args.config:
        import yaml as _yaml
        with open(args.config, encoding="utf-8") as f:
            config = _yaml.safe_load(f)
        pipeline_dir = Path(args.pipeline_dir) if args.pipeline_dir else Path.home() / ".outlook-pipeline"
    elif args.non_interactive:
        print("Non-interactive mode requires --config")
        sys.exit(1)
    else:
        config, pipeline_dir = interactive_config()

    deploy(pipeline_dir, config)


if __name__ == "__main__":
    main()
