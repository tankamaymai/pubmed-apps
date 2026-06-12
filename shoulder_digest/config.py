from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    db_path: Path = Path(".pubmed_digest/digest.sqlite3")
    daily_time: str = "07:00"
    public_base_url: str = ""
    top_paper_count: int = 1
    pubmed_lookback_days: int = 30
    pubmed_max_lookback_days: int = 365
    auto_send: bool = False

    ncbi_api_key: str = ""
    ncbi_email: str = ""
    ncbi_tool: str = "shoulder-digest"

    codex_bin: str = "codex"
    codex_model: str = ""
    codex_generated_images_dir: Path = Path.home() / ".codex" / "generated_images"
    codex_turn_timeout_seconds: int = 600
    codex_image_turn_timeout_seconds: int = 1800
    codex_image_wait_seconds: int = 120
    mock_ai: bool = False

    notion_token: str = ""
    notion_database_id: str = ""
    notion_version: str = "2022-06-28"
    notion_api_base_url: str = "https://api.notion.com"

    line_channel_access_token: str = ""
    line_channel_secret: str = ""
    line_group_id: str = ""
    line_api_base_url: str = "https://api.line.me"

    obsidian_vault: Path = Path("")
    obsidian_notes_dir: str = "PubMed肩関節"

    def media_dir(self) -> Path:
        return self.db_path.parent / "images"

    @classmethod
    def from_env(cls) -> "Settings":
        generated = os.environ.get("CODEX_GENERATED_IMAGES_DIR")
        return cls(
            host=os.environ.get("SHOULDER_DIGEST_HOST", "127.0.0.1"),
            port=int(os.environ.get("SHOULDER_DIGEST_PORT", "8765")),
            db_path=Path(os.environ.get("SHOULDER_DIGEST_DB", ".pubmed_digest/digest.sqlite3")),
            daily_time=os.environ.get("SHOULDER_DIGEST_DAILY_TIME", "07:00"),
            public_base_url=os.environ.get("SHOULDER_DIGEST_PUBLIC_BASE_URL", "").rstrip("/"),
            top_paper_count=max(1, int(os.environ.get("SHOULDER_DIGEST_TOP_PAPER_COUNT", "1"))),
            pubmed_lookback_days=(lookback := max(1, int(os.environ.get("SHOULDER_DIGEST_PUBMED_LOOKBACK_DAYS", "30")))),
            pubmed_max_lookback_days=max(
                lookback,
                max(1, int(os.environ.get("SHOULDER_DIGEST_PUBMED_MAX_LOOKBACK_DAYS", "365"))),
            ),
            auto_send=_bool_env("SHOULDER_DIGEST_AUTO_SEND"),
            ncbi_api_key=os.environ.get("NCBI_API_KEY", ""),
            ncbi_email=os.environ.get("NCBI_EMAIL", ""),
            ncbi_tool=os.environ.get("NCBI_TOOL", "shoulder-digest"),
            codex_bin=os.environ.get("CODEX_BIN") or default_codex_bin(),
            codex_model=os.environ.get("CODEX_MODEL", ""),
            codex_generated_images_dir=Path(generated) if generated else Path.home() / ".codex" / "generated_images",
            codex_turn_timeout_seconds=max(60, int(os.environ.get("CODEX_TURN_TIMEOUT_SECONDS", "600"))),
            codex_image_turn_timeout_seconds=max(60, int(os.environ.get("CODEX_IMAGE_TURN_TIMEOUT_SECONDS", "1800"))),
            codex_image_wait_seconds=max(10, int(os.environ.get("CODEX_IMAGE_WAIT_SECONDS", "120"))),
            mock_ai=_bool_env("SHOULDER_DIGEST_MOCK_AI"),
            notion_token=os.environ.get("NOTION_TOKEN", ""),
            notion_database_id=os.environ.get("NOTION_DATABASE_ID", ""),
            notion_version=os.environ.get("NOTION_VERSION", "2022-06-28"),
            notion_api_base_url=os.environ.get("NOTION_API_BASE_URL", "https://api.notion.com").rstrip("/"),
            line_channel_access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
            line_channel_secret=os.environ.get("LINE_CHANNEL_SECRET", ""),
            line_group_id=os.environ.get("LINE_GROUP_ID", ""),
            line_api_base_url=os.environ.get("LINE_API_BASE_URL", "https://api.line.me").rstrip("/"),
            obsidian_vault=Path(os.environ.get("OBSIDIAN_VAULT", "")),
            obsidian_notes_dir=os.environ.get("OBSIDIAN_NOTES_DIR", "PubMed肩関節"),
        )


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def default_codex_bin() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        standalone = Path(local_app_data) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
        if standalone.exists():
            return str(standalone)
    return "codex"
