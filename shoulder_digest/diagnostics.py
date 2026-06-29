from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import Settings
from .ngrok_sync import verify_public_base_url
from .notion_client import EXPECTED_PROPERTIES, NotionClient
from .obsidian_client import ObsidianVaultWriter
from .storage import Storage


def build_checks(settings: Settings, stored_line_group_id: str | None = None) -> dict[str, Any]:
    codex_found = bool(shutil.which(settings.codex_bin))
    codex_runnable, codex_version = check_codex(settings.codex_bin) if codex_found else (False, "")
    codex_login_ok, codex_login_status = check_codex_login(settings.codex_bin) if codex_runnable else (False, "")
    schema_dir = Path("schemas/codex_app_server/generated")
    schema_files = list(schema_dir.glob("*.json")) if schema_dir.exists() else []
    notion_validation = validate_notion(settings)
    obsidian_validation = validate_obsidian(settings)
    if stored_line_group_id is None:
        stored_line_group_id = load_stored_line_group_id(settings)
    effective_line_group_id = settings.line_group_id or stored_line_group_id
    public_url_check = verify_public_base_url(settings.public_base_url) if settings.public_base_url else {
        "ok": False,
        "reason": "empty url",
        "url": "",
    }
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "database": str(settings.db_path),
        "codex_bin": settings.codex_bin,
        "codex_found": codex_found,
        "codex_runnable": codex_runnable,
        "codex_version": codex_version,
        "codex_login_ok": codex_login_ok,
        "codex_login_status": codex_login_status,
        "codex_schema_dir": str(schema_dir),
        "codex_schema_file_count": len(schema_files),
        "mock_ai": settings.mock_ai,
        "ncbi_api_key": bool(settings.ncbi_api_key),
        "pubmed_eutilities_ready": True,
        "pubmed_rate_limit": "up to 10 requests/second with NCBI_API_KEY; lower unauthenticated rate otherwise",
        "notion_configured": bool(settings.notion_token and settings.notion_database_id),
        "notion_api_base_url": settings.notion_api_base_url,
        "notion_validation": notion_validation,
        "notion_expected_properties": EXPECTED_PROPERTIES,
        "line_token": bool(settings.line_channel_access_token),
        "line_secret": bool(settings.line_channel_secret),
        "line_group_id": bool(effective_line_group_id),
        "line_group_id_source": "env" if settings.line_group_id else ("webhook_storage" if stored_line_group_id else ""),
        "line_api_base_url": settings.line_api_base_url,
        "public_base_url": settings.public_base_url,
        "public_url_check": public_url_check,
        "line_image_delivery_ready": bool(public_url_check.get("ok")),
        "auto_send": settings.auto_send,
        "top_paper_count": settings.top_paper_count,
        "pubmed_lookback_days": settings.pubmed_lookback_days,
        "pubmed_max_lookback_days": settings.pubmed_max_lookback_days,
        "generated_images_dir": str(settings.codex_generated_images_dir),
        "managed_media_dir": str(settings.media_dir()),
        "obsidian_configured": bool(str(settings.obsidian_vault).strip()),
        "obsidian_vault": str(settings.obsidian_vault),
        "obsidian_notes_dir": settings.obsidian_notes_dir,
        "obsidian_validation": obsidian_validation,
    }
    checks["setup_items"] = setup_items(checks)
    checks["ready_for_mock_dry_run"] = bool(checks["pubmed_eutilities_ready"] and checks["mock_ai"])
    checks["ready_for_real_digest"] = all(
        [
            checks["codex_runnable"],
            checks["codex_login_ok"],
            checks["codex_schema_file_count"],
            checks["pubmed_eutilities_ready"],
        ]
    )
    checks["ready_for_line_delivery"] = all(
        [
            checks["ready_for_real_digest"],
            checks["line_token"],
            checks["line_secret"],
            checks["line_group_id"],
            checks["line_image_delivery_ready"],
        ]
    )
    checks["ready_for_notion_archive"] = bool(
        checks["notion_configured"]
        and isinstance(notion_validation, dict)
        and notion_validation.get("ok") is True
    )
    checks["ready_for_obsidian_archive"] = bool(
        checks["obsidian_configured"]
        and isinstance(obsidian_validation, dict)
        and obsidian_validation.get("ok") is True
    )
    checks["ready_for_end_to_end"] = bool(checks["ready_for_line_delivery"] and checks["ready_for_notion_archive"])
    return checks


def setup_items(checks: dict[str, Any]) -> list[dict[str, Any]]:
    notion_validation = checks.get("notion_validation")
    notion_ok = bool(isinstance(notion_validation, dict) and notion_validation.get("ok") is True)
    obsidian_validation = checks.get("obsidian_validation")
    obsidian_ok = bool(isinstance(obsidian_validation, dict) and obsidian_validation.get("ok") is True)
    return [
        {
            "label": "Standalone Codex CLI",
            "ok": bool(checks.get("codex_runnable")),
            "detail": checks.get("codex_version") or "Install standalone Codex CLI.",
        },
        {
            "label": "Codex ChatGPT login",
            "ok": bool(checks.get("codex_login_ok")),
            "detail": checks.get("codex_login_status") or "Run codex login.",
        },
        {
            "label": "Codex app-server schema",
            "ok": int(checks.get("codex_schema_file_count") or 0) > 0,
            "detail": f"{checks.get('codex_schema_file_count', 0)} schema files",
        },
        {
            "label": "PubMed E-utilities",
            "ok": bool(checks.get("pubmed_eutilities_ready")),
            "detail": (
                "Ready. NCBI_API_KEY is optional but recommended for higher rate limits."
                if not checks.get("ncbi_api_key")
                else "Ready with NCBI_API_KEY."
            ),
        },
        {
            "label": "Notion archive database",
            "ok": notion_ok,
            "detail": (
                "Ready."
                if notion_ok
                else (
                    "Set NOTION_TOKEN and share the archive DB with your Notion integration."
                    if not checks.get("notion_configured")
                    else _notion_validation_detail(notion_validation)
                )
            ),
        },
        {
            "label": "Obsidian vault",
            "ok": obsidian_ok if checks.get("obsidian_configured") else True,
            "detail": (
                f"Notes dir: {checks.get('obsidian_notes_dir')}."
                if obsidian_ok
                else (
                    "Set OBSIDIAN_VAULT to your vault path."
                    if not checks.get("obsidian_configured")
                    else str((obsidian_validation or {}).get("error") or "Obsidian vault path is invalid.")
                )
            ),
        },
        {
            "label": "LINE Messaging API",
            "ok": bool(checks.get("line_token") and checks.get("line_secret") and checks.get("line_group_id")),
            "detail": (
                f"Group ID source: {checks.get('line_group_id_source')}."
                if checks.get("line_group_id")
                else "Set LINE token, secret, and group ID, or receive a group webhook."
            ),
        },
        {
            "label": "Public image URL",
            "ok": bool(checks.get("line_image_delivery_ready")),
            "detail": (
                f"Reachable: {checks.get('public_base_url')}."
                if checks.get("line_image_delivery_ready")
                else (
                    str((checks.get("public_url_check") or {}).get("reason") or "Set SHOULDER_DIGEST_PUBLIC_BASE_URL.")
                    if checks.get("public_base_url")
                    else "Set SHOULDER_DIGEST_PUBLIC_BASE_URL and start ngrok."
                )
            ),
        },
    ]


def doctor_exit_code(checks: dict[str, Any]) -> int:
    if (not checks.get("codex_found") or not checks.get("codex_runnable")) and not checks.get("mock_ai"):
        return 2
    if checks.get("codex_runnable") and not checks.get("codex_login_ok") and not checks.get("mock_ai"):
        return 3
    return 0


def check_codex(codex_bin: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [codex_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr).strip()
    return result.returncode == 0, output


def check_codex_login(codex_bin: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [codex_bin, "login", "status"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr).strip()
    return result.returncode == 0, output


def validate_obsidian(settings: Settings) -> dict[str, object]:
    if not str(settings.obsidian_vault).strip():
        return {"checked": False, "reason": "OBSIDIAN_VAULT is not configured"}
    try:
        client = ObsidianVaultWriter(settings.obsidian_vault, settings.obsidian_notes_dir)
        return {"checked": True, **client.validate_vault()}
    except Exception as exc:
        return {"checked": True, "ok": False, "error": str(exc)}


def _notion_validation_detail(notion_validation: dict[str, object] | None) -> str:
    if not isinstance(notion_validation, dict):
        return "Notion validation failed."
    error = str(notion_validation.get("error") or "")
    if "shared with your integration" in error:
        return (
            "Open the archive database in Notion and share it with your integration "
            "(… → Connect to → pubmed-apps)."
        )
    if notion_validation.get("missing"):
        return f"Missing properties: {', '.join(notion_validation['missing'])}"
    if notion_validation.get("mismatched"):
        return "Notion database schema does not match the expected properties."
    return error or "Notion validation failed."


def validate_notion(settings: Settings) -> dict[str, object]:
    if not (settings.notion_token and settings.notion_database_id):
        return {"checked": False, "reason": "NOTION_TOKEN or NOTION_DATABASE_ID is not configured"}
    try:
        client = NotionClient(
            settings.notion_token,
            settings.notion_database_id,
            settings.notion_version,
            settings.notion_api_base_url,
        )
        return {"checked": True, **client.validate_database()}
    except Exception as exc:
        return {"checked": True, "ok": False, "error": str(exc)}


def load_stored_line_group_id(settings: Settings) -> str:
    try:
        return Storage(settings.db_path).get_setting("line_group_id")
    except Exception:
        return ""
