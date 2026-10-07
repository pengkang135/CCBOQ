"""Sync MCP config from Claude source-of-truth to Claude runtime and Trae."""

from __future__ import annotations

import json
from pathlib import Path


HOME = Path(r"C:\Users\Kevin")
SOURCE_MCP = HOME / ".mcp.json"
CLAUDE_TEMPLATE_MCP = HOME / ".claude" / ".mcp.json"
CLAUDE_RUNTIME = HOME / ".claude.json"
CLAUDE_LOCAL_SETTINGS = HOME / ".claude" / "settings.local.json"
TRAE_USER_MCP = HOME / "AppData" / "Roaming" / "Trae" / "User" / "mcp.json"


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _extract_servers(path: Path) -> dict:
    data = read_json(path)
    servers = data.get("mcpServers", data)
    if not isinstance(servers, dict):
        raise ValueError(f"Invalid MCP config in {path}: expected object")
    return servers


def load_source_servers() -> tuple[dict, Path]:
    # Prefer the MCP set Claude is actually using right now.
    try:
        runtime_servers = _extract_servers(CLAUDE_RUNTIME)
        if runtime_servers:
            return runtime_servers, CLAUDE_RUNTIME
    except Exception:
        pass

    return _extract_servers(SOURCE_MCP), SOURCE_MCP


def sync_claude_runtime(servers: dict) -> None:
    config = read_json(CLAUDE_RUNTIME)
    config["mcpServers"] = servers
    write_json(CLAUDE_RUNTIME, config)


def sync_claude_local_settings(servers: dict) -> None:
    settings = read_json(CLAUDE_LOCAL_SETTINGS)
    settings["enabledMcpjsonServers"] = list(servers.keys())
    write_json(CLAUDE_LOCAL_SETTINGS, settings)


def try_sync(label: str, action) -> tuple[str, str]:
    try:
        action()
        return label, "ok"
    except PermissionError as exc:
        return label, f"permission-denied: {exc}"
    except Exception as exc:  # pragma: no cover - defensive logging for local scripts
        return label, f"error: {exc}"


def main() -> None:
    servers, source_path = load_source_servers()

    results = [
        try_sync(
            "Claude template",
            lambda: write_json(CLAUDE_TEMPLATE_MCP, servers),
        ),
        try_sync("Claude runtime", lambda: sync_claude_runtime(servers))
        if source_path != CLAUDE_RUNTIME
        else ("Claude runtime", "source-of-truth (skipped write)"),
        try_sync("Claude local settings", lambda: sync_claude_local_settings(servers)),
        try_sync(
            "Trae user MCP",
            lambda: write_json(TRAE_USER_MCP, {"mcpServers": servers}),
        ),
    ]

    print(f"Source: {source_path}")
    print(f"Servers: {', '.join(servers.keys())}")
    for label, result in results:
        print(f"{label}: {result}")


if __name__ == "__main__":
    main()
