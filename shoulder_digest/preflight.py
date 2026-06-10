from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Settings
from .diagnostics import build_checks
from .pubmed import PubMedClient, default_run_date

REQUIRED_CLIENT_METHODS = {"initialize", "thread/start", "turn/start"}
REQUIRED_SERVER_NOTIFICATIONS = {"thread/started", "turn/started", "turn/completed", "item/agentMessage/delta"}


def run_preflight(settings: Settings, run_date: str | None = None, live_pubmed: bool = False) -> dict[str, Any]:
    checks = build_checks(settings)
    schema = validate_codex_schema(Path(checks["codex_schema_dir"]))
    pubmed = validate_pubmed(settings, run_date or default_run_date(), live=live_pubmed)
    line = {
        "ok": bool(checks["line_token"] and checks["line_secret"] and checks["line_group_id"]),
        "image_url_ok": bool(checks["line_image_delivery_ready"]),
        "auto_send": bool(checks["auto_send"]),
    }
    notion = {
        "ok": bool(checks["ready_for_notion_archive"]),
        "validation": checks["notion_validation"],
    }
    real_digest_ready = bool(checks["ready_for_real_digest"] and schema["ok"] and pubmed["ok"])
    end_to_end_ready = bool(real_digest_ready and line["ok"] and line["image_url_ok"] and notion["ok"])
    return {
        "ok": end_to_end_ready,
        "real_digest_ready": real_digest_ready,
        "checks": checks,
        "codex_schema": schema,
        "pubmed": pubmed,
        "line": line,
        "notion": notion,
        "missing": missing_items(checks, schema, pubmed, line, notion),
    }


def validate_codex_schema(schema_dir: Path) -> dict[str, Any]:
    client_path = schema_dir / "ClientRequest.json"
    server_path = schema_dir / "ServerNotification.json"
    if not client_path.exists() or not server_path.exists():
        return {
            "ok": False,
            "error": f"Missing generated schema files under {schema_dir}",
            "client_methods": [],
            "server_notifications": [],
        }
    client_methods = extract_enums(json.loads(client_path.read_text(encoding="utf-8")))
    server_notifications = extract_enums(json.loads(server_path.read_text(encoding="utf-8")))
    missing_client = sorted(REQUIRED_CLIENT_METHODS - client_methods)
    missing_server = sorted(REQUIRED_SERVER_NOTIFICATIONS - server_notifications)
    return {
        "ok": not missing_client and not missing_server,
        "client_method_count": len(client_methods),
        "server_notification_count": len(server_notifications),
        "missing_client_methods": missing_client,
        "missing_server_notifications": missing_server,
    }


def extract_enums(node: Any) -> set[str]:
    values: set[str] = set()
    if isinstance(node, dict):
        enum = node.get("enum")
        if isinstance(enum, list):
            values.update(value for value in enum if isinstance(value, str) and ("/" in value or value == "initialize"))
        for child in node.values():
            values.update(extract_enums(child))
    elif isinstance(node, list):
        for child in node:
            values.update(extract_enums(child))
    return values


def validate_pubmed(settings: Settings, run_date: str, live: bool = False) -> dict[str, Any]:
    if not live:
        return {
            "ok": True,
            "live": False,
            "date": run_date,
            "detail": "Skipped live PubMed check. Use --live-pubmed to verify E-utilities now.",
        }
    try:
        client = PubMedClient(settings.ncbi_api_key, settings.ncbi_email, settings.ncbi_tool)
        pmids = client.search_recent(run_date, retmax=5, lookback_days=settings.pubmed_lookback_days)
        return {
            "ok": True,
            "live": True,
            "date": run_date,
            "lookback_days": settings.pubmed_lookback_days,
            "pmid_count": len(pmids),
            "pmids": pmids,
        }
    except Exception as exc:
        return {"ok": False, "live": True, "date": run_date, "error": str(exc)}


def missing_items(
    checks: dict[str, Any],
    schema: dict[str, Any],
    pubmed: dict[str, Any],
    line: dict[str, Any],
    notion: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    if not checks.get("codex_login_ok"):
        missing.append("Run codex login with the standalone Codex CLI.")
    if not schema.get("ok"):
        missing.append("Regenerate Codex app-server schema.")
    if not pubmed.get("ok"):
        missing.append("Fix PubMed E-utilities connectivity.")
    if not notion.get("ok"):
        missing.append("Set NOTION_TOKEN and share the Notion archive DB with the integration.")
    if not line.get("ok"):
        missing.append("Set LINE token, secret, and group ID.")
    if not line.get("image_url_ok"):
        missing.append("Set SHOULDER_DIGEST_PUBLIC_BASE_URL to a public HTTPS URL.")
    return missing
