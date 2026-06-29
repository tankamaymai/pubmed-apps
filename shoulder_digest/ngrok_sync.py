from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ENV_KEY = "SHOULDER_DIGEST_PUBLIC_BASE_URL"
DEFAULT_NGROK_API = "http://127.0.0.1:4040"


def fetch_ngrok_https_url(
    port: int | None = None,
    *,
    api_base: str = DEFAULT_NGROK_API,
    timeout: float = 3.0,
) -> str | None:
    url = f"{api_base.rstrip('/')}/api/tunnels"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    tunnels = payload.get("tunnels", [])
    matched: str | None = None
    fallback: str | None = None
    for tunnel in tunnels:
        public_url = str(tunnel.get("public_url", "")).rstrip("/")
        if not public_url.startswith("https://"):
            continue
        if fallback is None:
            fallback = public_url
        if port is None:
            matched = public_url
            break
        addr = str(tunnel.get("config", {}).get("addr", ""))
        if addr.endswith(f":{port}") or f":{port}/" in addr:
            matched = public_url
            break
    return matched or fallback


def update_env_file(env_path: Path, key: str, value: str) -> bool:
    if not env_path.exists():
        raise FileNotFoundError(f".env not found: {env_path}")

    raw = env_path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    changed = False
    found = False
    updated_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            updated_lines.append(line)
            continue
        current_key, _current_value = stripped.split("=", 1)
        if current_key.strip() != key:
            updated_lines.append(line)
            continue
        found = True
        new_line = f"{key}={value}"
        if current_key.strip() == key and stripped != f"{key}={value}":
            changed = True
        updated_lines.append(new_line)

    if not found:
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        updated_lines.append(f"{key}={value}")
        changed = True

    env_path.write_text(newline.join(updated_lines) + newline, encoding="utf-8")
    os.environ[key] = value
    return changed


def sync_public_base_url(
    env_path: Path | str = ".env",
    *,
    port: int = 8765,
    wait_seconds: float = 1.0,
    max_attempts: int = 5,
    api_base: str = DEFAULT_NGROK_API,
) -> dict[str, Any]:
    path = Path(env_path)
    previous = os.environ.get(ENV_KEY, "").rstrip("/")

    url: str | None = None
    for attempt in range(max(1, max_attempts)):
        url = fetch_ngrok_https_url(port=port, api_base=api_base)
        if url:
            break
        if attempt + 1 < max_attempts and wait_seconds > 0:
            time.sleep(wait_seconds)

    if not url:
        return {
            "ok": False,
            "reason": "ngrok tunnel not found",
            "previous": previous,
            "envPath": str(path.resolve()),
        }

    changed = update_env_file(path, ENV_KEY, url)
    return {
        "ok": True,
        "url": url,
        "changed": changed,
        "previous": previous,
        "envPath": str(path.resolve()),
    }


def rebuild_image_url(public_base_url: str, image_path: str) -> str:
    base = public_base_url.rstrip("/")
    if not base or not image_path:
        return ""
    return f"{base}/generated-images/{Path(image_path).name}"


def verify_public_base_url(
    public_base_url: str,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    base = public_base_url.rstrip("/")
    if not base:
        return {"ok": False, "reason": "empty url", "url": ""}
    health_url = f"{base}/healthz"
    try:
        request = urllib.request.Request(
            health_url,
            headers={"User-Agent": "LineBotWebhook/2.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", response.getcode())
            content_type = response.headers.get("Content-Type", "")
            if status != 200:
                return {
                    "ok": False,
                    "reason": f"healthz returned HTTP {status}",
                    "url": base,
                }
            if "json" not in content_type and "text" not in content_type:
                return {
                    "ok": False,
                    "reason": f"healthz returned unexpected content type: {content_type}",
                    "url": base,
                }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "reason": f"healthz HTTP {exc.code}", "url": base}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "reason": str(exc), "url": base}
    return {"ok": True, "url": base}


def verify_image_url(
    image_url: str,
    *,
    timeout: float = 8.0,
) -> dict[str, Any]:
    if not image_url:
        return {"ok": False, "reason": "empty image url", "url": ""}
    try:
        request = urllib.request.Request(
            image_url,
            headers={"User-Agent": "LineBotWebhook/2.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", response.getcode())
            content_type = response.headers.get("Content-Type", "")
            length = int(response.headers.get("Content-Length", "0") or 0)
            if status != 200:
                return {"ok": False, "reason": f"image returned HTTP {status}", "url": image_url}
            if not content_type.startswith("image/"):
                return {
                    "ok": False,
                    "reason": f"image returned unexpected content type: {content_type}",
                    "url": image_url,
                }
            if length and length < 1024:
                return {
                    "ok": False,
                    "reason": f"image response too small ({length} bytes)",
                    "url": image_url,
                }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "reason": f"image HTTP {exc.code}", "url": image_url}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "reason": str(exc), "url": image_url}
    return {"ok": True, "url": image_url, "content_type": content_type}
