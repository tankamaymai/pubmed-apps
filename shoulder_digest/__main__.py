from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .app import ShoulderDigestApp
from .config import Settings, default_codex_bin, load_dotenv
from .diagnostics import build_checks, doctor_exit_code
from .ngrok_sync import sync_public_base_url
from .preflight import run_preflight
from .pubmed import default_run_date
from .server import serve


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(prog="shoulder_digest")
    sub = parser.add_subparsers(dest="command", required=True)

    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--host", default=settings.host)
    serve_parser.add_argument("--port", type=int, default=settings.port)
    serve_parser.add_argument(
        "--no-schedule",
        action="store_true",
        help="Disable automatic daily runs while serve is up",
    )

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--date", default=default_run_date())
    run_parser.add_argument("--pmid", default="", help="Deliver a specific PubMed ID")
    run_parser.add_argument("--dry-run", action="store_true")

    send_parser = sub.add_parser("approve-send", help="Send an existing digest to LINE")
    send_parser.add_argument("--date", required=True)
    send_parser.add_argument("--dry-run", action="store_true")

    send_alias = sub.add_parser("send", help="Alias for approve-send")
    send_alias.add_argument("--date", required=True)
    send_alias.add_argument("--dry-run", action="store_true")

    resend_image_parser = sub.add_parser("resend-image", help="Resend only the graphic for an existing run")
    resend_image_parser.add_argument("--date", required=True)
    resend_image_parser.add_argument("--dry-run", action="store_true")

    group_parser = sub.add_parser("set-line-group")
    group_parser.add_argument("--group-id", required=True)

    preflight_parser = sub.add_parser("preflight")
    preflight_parser.add_argument("--date", default=default_run_date())
    preflight_parser.add_argument("--live-pubmed", action="store_true")
    preflight_parser.add_argument("--allow-incomplete", action="store_true")

    archive_parser = sub.add_parser("archive-notion", help="Archive a run to Notion")
    archive_parser.add_argument("--date", required=True)
    archive_parser.add_argument("--dry-run", action="store_true")
    archive_parser.add_argument("--mark-delivered", action="store_true")

    sync_parser = sub.add_parser("sync-ngrok-url", help="Update SHOULDER_DIGEST_PUBLIC_BASE_URL in .env from ngrok")
    sync_parser.add_argument("--env", default=".env")
    sync_parser.add_argument("--port", type=int, default=settings.port)
    sync_parser.add_argument("--wait-seconds", type=float, default=1.0)
    sync_parser.add_argument("--max-attempts", type=int, default=5)

    sub.add_parser("doctor")

    init_parser = sub.add_parser("init-env")
    init_parser.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "serve":
        settings.host = args.host
        settings.port = args.port
        serve(settings, schedule=not args.no_schedule)
        return 0
    if args.command == "run":
        app = ShoulderDigestApp(settings)
        print(json.dumps(app.run_daily(args.date, dry_run=args.dry_run, pmid=args.pmid), ensure_ascii=False, indent=2))
        return 0
    if args.command in {"approve-send", "send"}:
        app = ShoulderDigestApp(settings)
        print(json.dumps(app.approve_send(args.date, dry_run=args.dry_run), ensure_ascii=False, indent=2))
        return 0
    if args.command == "resend-image":
        app = ShoulderDigestApp(settings)
        print(json.dumps(app.resend_image(args.date, dry_run=args.dry_run), ensure_ascii=False, indent=2))
        return 0
    if args.command == "archive-notion":
        app = ShoulderDigestApp(settings)
        print(
            json.dumps(
                app.archive_notion_for_run(
                    args.date,
                    dry_run=args.dry_run,
                    mark_delivered=args.mark_delivered or None,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "set-line-group":
        app = ShoulderDigestApp(settings)
        app.storage.set_setting("line_group_id", args.group_id)
        print(json.dumps({"ok": True, "line_group_id": args.group_id}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "preflight":
        report = run_preflight(settings, run_date=args.date, live_pubmed=args.live_pubmed)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] or args.allow_incomplete else 1
    if args.command == "sync-ngrok-url":
        result = sync_public_base_url(
            args.env,
            port=args.port,
            wait_seconds=args.wait_seconds,
            max_attempts=args.max_attempts,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if args.command == "doctor":
        return doctor(settings)
    if args.command == "init-env":
        return init_env(force=args.force)
    return 1


def init_env(force: bool = False) -> int:
    env_path = Path(".env")
    if env_path.exists() and not force:
        print(".env already exists. Use --force to overwrite.", file=sys.stderr)
        return 1
    template = Path(".env.example").read_text(encoding="utf-8")
    values = {
        "CODEX_BIN": default_codex_bin(),
        "NOTION_DATABASE_ID": "c78096bc6401494999e598ed022e84a8",
    }
    lines = []
    for line in template.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            lines.append(line)
            continue
        key, _value = line.split("=", 1)
        if key in values:
            lines.append(f"{key}={values[key]}")
        else:
            lines.append(line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {env_path.resolve()}")
    print("Fill NCBI_API_KEY, NOTION_TOKEN, LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, LINE_GROUP_ID, and SHOULDER_DIGEST_PUBLIC_BASE_URL.")
    return 0


def doctor(settings: Settings) -> int:
    checks = build_checks(settings)
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    exit_code = doctor_exit_code(checks)
    if exit_code == 2:
        print(
            "Codex CLI is not runnable. Install standalone Codex CLI, run codex login, "
            "or set SHOULDER_DIGEST_MOCK_AI=1 for local dry-runs.",
            file=sys.stderr,
        )
    elif exit_code == 3:
        print("Codex CLI is installed but not logged in. Run: codex login", file=sys.stderr)
    if not checks.get("codex_schema_file_count") and not settings.mock_ai:
        print(
            "Codex app-server schema has not been generated. Run scripts/generate_codex_schema.ps1 "
            "after installing standalone Codex CLI.",
            file=sys.stderr,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
