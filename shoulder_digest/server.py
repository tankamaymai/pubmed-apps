from __future__ import annotations

import json
import mimetypes
import threading
import time
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .app import ShoulderDigestApp
from .config import Settings
from .diagnostics import build_checks
from .pubmed import default_run_date


def serve(settings: Settings, schedule: bool = False) -> None:
    app = ShoulderDigestApp(settings)
    if schedule:
        threading.Thread(target=_scheduler_loop, args=(app, settings.daily_time), daemon=True).start()
    handler = _make_handler(app, settings)
    server = ThreadingHTTPServer((settings.host, settings.port), handler)
    print(f"Serving shoulder digest at http://{settings.host}:{settings.port}/")
    server.serve_forever()


def _make_handler(app: ShoulderDigestApp, settings: Settings) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                self._json({"ok": True})
                return
            if parsed.path == "/":
                self._html(render_home(app))
                return
            if parsed.path == "/setup":
                checks = build_checks(settings)
                if parse_qs(parsed.query).get("format") == ["json"]:
                    self._json(checks)
                else:
                    self._html(render_setup(checks))
                return
            if parsed.path.startswith("/runs/"):
                run_date = parsed.path.removeprefix("/runs/").strip("/")
                run = app.get_run(run_date)
                if not run:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                    return
                if parse_qs(parsed.query).get("format") == ["json"]:
                    self._json(run)
                else:
                    self._html(render_run(run))
                return
            if parsed.path.startswith("/generated-images/"):
                name = Path(parsed.path).name
                self._serve_image(app.image_path_for_name(name))
                return
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/jobs/daily":
                payload = self._read_json()
                try:
                    result = app.run_daily(
                        run_date=payload.get("date"),
                        dry_run=bool(payload.get("dryRun", False)),
                    )
                    self._json(result)
                except Exception as exc:
                    self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path.startswith("/runs/") and parsed.path.endswith("/approve-send"):
                run_date = parsed.path.removeprefix("/runs/").removesuffix("/approve-send").strip("/")
                payload = self._read_json()
                try:
                    result = app.approve_send(run_date, dry_run=bool(payload.get("dryRun", False)))
                    self._json(result)
                except Exception as exc:
                    self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path == "/webhook/line":
                body = self._read_body()
                signature = self.headers.get("X-Line-Signature", "")
                try:
                    self._json(app.handle_line_webhook(body, signature))
                except Exception as exc:
                    self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/setup/line-group":
                payload = self._read_form_or_json()
                group_id = str(payload.get("groupId", "")).strip()
                if not group_id:
                    self._json({"error": "groupId is required"}, HTTPStatus.BAD_REQUEST)
                    return
                app.storage.set_setting("line_group_id", group_id)
                self._json({"ok": True, "lineGroupId": group_id})
                return
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0"))
            return self.rfile.read(length) if length else b"{}"

        def _read_json(self) -> dict[str, Any]:
            body = self._read_body()
            if not body:
                return {}
            return json.loads(body.decode("utf-8"))

        def _read_form_or_json(self) -> dict[str, Any]:
            body = self._read_body()
            if not body:
                return {}
            content_type = self.headers.get("Content-Type", "")
            if "application/json" in content_type:
                return json.loads(body.decode("utf-8"))
            if "application/x-www-form-urlencoded" in content_type:
                parsed = parse_qs(body.decode("utf-8"))
                return {key: values[-1] for key, values in parsed.items()}
            return json.loads(body.decode("utf-8"))

        def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_image(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            print("%s - %s" % (self.address_string(), format % args))

    return Handler


def _scheduler_loop(app: ShoulderDigestApp, daily_time: str) -> None:
    while True:
        try:
            if should_run_scheduled_daily(app, daily_time):
                today = date.today().isoformat()
                app.run_daily(run_date=today, dry_run=False)
        except Exception as exc:
            print(f"scheduled run failed: {exc}")
        time.sleep(30)


def should_run_scheduled_daily(app: ShoulderDigestApp, daily_time: str, now: datetime | None = None) -> bool:
    current = now or datetime.now()
    try:
        scheduled_hour, scheduled_minute = map(int, daily_time.split(":", 1))
    except ValueError:
        return False
    scheduled_today = current.replace(hour=scheduled_hour, minute=scheduled_minute, second=0, microsecond=0)
    if current < scheduled_today:
        return False

    today = current.date().isoformat()
    existing = app.storage.get_run(today)
    if existing:
        status = str(existing.get("status", ""))
        if status in {"ready_for_approval", "delivered", "no_candidates"}:
            return False
    return True


def render_home(app: ShoulderDigestApp) -> str:
    latest = app.latest_run_date()
    latest_link = f'<p>Latest run: <a href="/runs/{latest}">{latest}</a></p>' if latest else "<p>No runs yet.</p>"
    today = default_run_date()
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Shoulder PubMed Digest</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #17202a; }}
    button {{ padding: 10px 14px; border: 1px solid #2f6f73; background: #2f6f73; color: white; border-radius: 6px; cursor: pointer; }}
    input {{ padding: 9px; border: 1px solid #b8c7c9; border-radius: 6px; }}
    pre {{ background: #f4f7f7; padding: 12px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>Shoulder PubMed Digest</h1>
  <p><a href="/setup">Setup status</a></p>
  {latest_link}
  <label>Run date <input id="date" value="{today}"></label>
  <button onclick="runDaily(true)">Dry run</button>
  <button onclick="runDaily(false)">Run</button>
  <button onclick="sendOnly()">LINE送信のみ</button>
  <p>同じ日付でも何度でも Run / LINE送信できます。配信済みの論文は次回 Run で別の論文を選びます。</p>
  <pre id="out"></pre>
  <script>
    async function runDaily(dryRun) {{
      const date = document.getElementById('date').value;
      const res = await fetch('/jobs/daily', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{date, dryRun}})
      }});
      const data = await res.json();
      document.getElementById('out').textContent = JSON.stringify(data, null, 2);
      if (data.runDate) window.location.href = '/runs/' + data.runDate;
    }}
    async function sendOnly() {{
      const date = document.getElementById('date').value;
      const res = await fetch('/runs/' + date + '/approve-send', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{dryRun: false}})
      }});
      document.getElementById('out').textContent = JSON.stringify(await res.json(), null, 2);
    }}
  </script>
</body>
</html>"""


def render_setup(checks: dict[str, Any]) -> str:
    rows = []
    for item in checks.get("setup_items", []):
        ok = bool(item.get("ok"))
        label = escape(item.get("label", ""))
        detail = escape(item.get("detail", ""))
        status = "OK" if ok else "Needs setup"
        klass = "ok" if ok else "bad"
        rows.append(f"<tr><td>{label}</td><td class='{klass}'>{status}</td><td>{detail}</td></tr>")
    readiness = [
        ("Mock dry-run", checks.get("ready_for_mock_dry_run")),
        ("Real digest generation", checks.get("ready_for_real_digest")),
        ("Notion archive", checks.get("ready_for_notion_archive")),
        ("LINE delivery", checks.get("ready_for_line_delivery")),
        ("End to end", checks.get("ready_for_end_to_end")),
    ]
    readiness_items = "".join(
        f"<li><strong>{escape(label)}:</strong> {'OK' if ok else 'Needs setup'}</li>" for label, ok in readiness
    )
    next_steps = setup_next_steps(checks)
    next_step_items = "".join(f"<li>{escape(item)}</li>" for item in next_steps) or "<li>All setup checks are green.</li>"
    raw_json = escape(json.dumps(checks, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Setup Status</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #17202a; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border-bottom: 1px solid #d5dfdf; padding: 10px; text-align: left; vertical-align: top; }}
    .ok {{ color: #1d6b4f; font-weight: 700; }}
    .bad {{ color: #a33b2b; font-weight: 700; }}
    pre {{ background: #f4f7f7; padding: 12px; overflow: auto; }}
  </style>
</head>
<body>
  <p><a href="/">Home</a></p>
  <h1>Setup Status</h1>
  <table>
    <thead><tr><th>Item</th><th>Status</th><th>Detail</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <h2>Readiness</h2>
  <ul>{readiness_items}</ul>
  <h2>Next Steps</h2>
  <ul>{next_step_items}</ul>
  <h2>LINE Group</h2>
  <form method="post" action="/setup/line-group">
    <label>Group ID <input name="groupId" placeholder="C..." style="min-width: 320px; padding: 8px;"></label>
    <button type="submit" style="padding: 8px 12px;">Save</button>
  </form>
  <p>Use this when you already know the LINE group ID. Otherwise let the LINE webhook capture it from a group event.</p>
  <p><a href="/setup?format=json">JSON</a></p>
  <details>
    <summary>Raw checks</summary>
    <pre>{raw_json}</pre>
  </details>
</body>
</html>"""


def setup_next_steps(checks: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    if not checks.get("codex_login_ok"):
        steps.append("Run codex login with the standalone Codex CLI.")
    if not checks.get("ready_for_notion_archive"):
        steps.append("Set NOTION_TOKEN, set NOTION_DATABASE_ID, and share the Notion database with the integration.")
    if not checks.get("line_token"):
        steps.append("Set LINE_CHANNEL_ACCESS_TOKEN from the LINE Messaging API channel.")
    if not checks.get("line_secret"):
        steps.append("Set LINE_CHANNEL_SECRET so webhook signatures can be verified.")
    if not checks.get("line_group_id"):
        steps.append("Set LINE_GROUP_ID or let POST /webhook/line capture it from a group event.")
    if not checks.get("line_image_delivery_ready"):
        steps.append("Set SHOULDER_DIGEST_PUBLIC_BASE_URL to a public HTTPS URL for LINE image delivery.")
    return steps


def render_run(run: dict[str, Any]) -> str:
    image = ""
    if run.get("image_path"):
        image = f'<img src="/generated-images/{Path(run["image_path"]).name}" style="max-width:100%;height:auto;border:1px solid #d5dfdf">'
    papers = []
    for paper in run.get("papers", []):
        papers.append(
            "<section>"
            f"<h2>{escape(paper.get('title', ''))}</h2>"
            f"<p><strong>PMID:</strong> <a href='{escape(paper.get('pubmed_url', ''))}'>{escape(paper.get('pmid', ''))}</a></p>"
            f"<p>{escape(paper.get('japanese_summary') or paper.get('abstract', ''))}</p>"
            "</section>"
        )
    status = str(run.get("status", ""))
    can_send = status in {"ready_for_approval", "delivered"}
    send_label = "LINE再送信" if status == "delivered" else "LINE送信"
    send_buttons = ""
    if can_send:
        send_buttons = f"""
  <button onclick="approve(false)">{send_label}</button>
  <button onclick="approve(true)">送信Dry run</button>"""
    else:
        send_buttons = "<p>この run はまだ送信できません。Home から Run を実行してください。</p>"
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Run {escape(run.get('run_date', ''))}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #17202a; }}
    section {{ border-top: 1px solid #d5dfdf; padding: 18px 0; }}
    button {{ padding: 10px 14px; border: 1px solid #2f6f73; background: #2f6f73; color: white; border-radius: 6px; cursor: pointer; }}
    pre {{ background: #f4f7f7; padding: 12px; overflow: auto; }}
  </style>
</head>
<body>
  <p><a href="/">Home</a></p>
  <h1>Run {escape(run.get('run_date', ''))}</h1>
  <p>Status: {escape(run.get('status', ''))}</p>
  <p>{escape(run.get('digest_summary', ''))}</p>
  {image}
  {''.join(papers)}
  {send_buttons}
  <pre id="out"></pre>
  <script>
    async function approve(dryRun) {{
      const res = await fetch('/runs/{escape(run.get('run_date', ''))}/approve-send', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{dryRun}})
      }});
      document.getElementById('out').textContent = JSON.stringify(await res.json(), null, 2);
    }}
  </script>
</body>
</html>"""


def escape(value: Any) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
