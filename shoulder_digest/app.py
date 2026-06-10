from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .ai_pipeline import generate_image_with_codex, summarize_with_codex
from .codex_client import CodexAppServerClient
from .config import Settings
from .image_watcher import ImageWatcher
from .line_client import LineClient, build_line_messages
from .models import DigestResult
from .notion_client import NotionClient
from .pubmed import PubMedClient, default_run_date, select_top_papers
from .storage import Storage


class ShoulderDigestApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings.db_path)
        self.pubmed = PubMedClient(settings.ncbi_api_key, settings.ncbi_email, settings.ncbi_tool)
        self.codex = CodexAppServerClient(settings.codex_bin, settings.codex_model, Path.cwd())
        self.watcher = ImageWatcher(settings.codex_generated_images_dir)
        self.line = LineClient(
            settings.line_channel_access_token,
            settings.line_channel_secret,
            settings.line_api_base_url,
        )
        self.notion = NotionClient(
            settings.notion_token,
            settings.notion_database_id,
            settings.notion_version,
            settings.notion_api_base_url,
        )

    def run_daily(self, run_date: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        run_date = run_date or default_run_date()
        existing = self.storage.get_run(run_date)
        if existing and existing.get("status") == "delivered" and not dry_run:
            return {"runDate": run_date, "status": "already_delivered", "run": existing}
        self.storage.upsert_run(run_date, "running", dry_run)
        try:
            pmids = self.pubmed.search_recent(run_date, lookback_days=self.settings.pubmed_lookback_days)
            papers = self.pubmed.fetch_details(pmids)
            selected = select_top_papers(
                papers,
                self.storage.known_pmids(exclude_run_date=run_date),
                limit=self.settings.top_paper_count,
            )
            self.storage.save_candidates(run_date, selected)
            if not selected:
                self.storage.upsert_run(run_date, "no_candidates", dry_run)
                return {"runDate": run_date, "status": "no_candidates", "pmids": pmids}

            digest = summarize_with_codex(run_date, selected, self.codex, mock=self.settings.mock_ai)
            image_path = generate_image_with_codex(
                digest,
                self.codex,
                self.watcher,
                mock=self.settings.mock_ai,
            )
            if image_path:
                stored_image = self._store_image_for_run(run_date, image_path)
                digest.image_path = str(stored_image)
                digest.image_url = self.public_image_url(stored_image)
            elif self.settings.mock_ai:
                digest.image_path = ""
                digest.image_url = ""
            self.storage.save_digest(digest)
            self._archive_to_notion(digest, selected, dry_run=dry_run)
            response = {"runDate": run_date, "status": "ready_for_approval", "digest": digest.to_dict()}
            if self.settings.auto_send and not dry_run:
                response["lineDelivery"] = self.approve_send(run_date, dry_run=False)
                response["status"] = "delivered"
            return response
        except Exception as exc:
            self.storage.mark_error(run_date, str(exc))
            raise

    def approve_send(self, run_date: str, dry_run: bool = False) -> dict[str, Any]:
        run = self.storage.get_run(run_date)
        if not run:
            raise RuntimeError(f"Run not found: {run_date}")
        if run.get("status") == "delivered" and not dry_run:
            return {"status": "already_delivered", "runDate": run_date}
        group_id = self.settings.line_group_id or self.storage.get_setting("line_group_id")
        if not group_id:
            raise RuntimeError("LINE group ID is not configured. Add the bot to a group and receive a webhook first.")
        image_url = run.get("image_url") or ""
        if not image_url and not dry_run:
            raise RuntimeError("Image URL is empty. Set SHOULDER_DIGEST_PUBLIC_BASE_URL before LINE image delivery.")
        messages = build_line_messages(
            run_date,
            image_url,
            run.get("digest_summary", ""),
            run.get("papers", []),
        )
        result = self.line.push(group_id, messages, dry_run=dry_run)
        self.storage.save_line_payload(run_date, result.get("payload", result), delivered=not dry_run)
        if not dry_run and self.notion.configured:
            for paper in run.get("papers", []):
                page_id = paper.get("notion_page_id")
                if page_id:
                    self.notion.mark_delivered(page_id)
        return result

    def handle_line_webhook(self, body: bytes, signature: str) -> dict[str, Any]:
        if self.settings.line_channel_secret and not self.line.verify_signature(body, signature):
            raise RuntimeError("Invalid LINE signature")
        payload = json.loads(body.decode("utf-8") or "{}")
        saved: list[str] = []
        for event in payload.get("events", []):
            source = event.get("source", {})
            group_id = source.get("groupId")
            if group_id:
                self.storage.set_setting("line_group_id", group_id)
                saved.append(group_id)
        return {"ok": True, "savedGroupIds": saved}

    def get_run(self, run_date: str) -> dict[str, Any] | None:
        return self.storage.get_run(run_date)

    def latest_run_date(self) -> str:
        return self.storage.latest_run_date()

    def public_image_url(self, path: Path) -> str:
        if not self.settings.public_base_url:
            return ""
        return f"{self.settings.public_base_url}/generated-images/{path.name}"

    def image_path_for_name(self, name: str) -> Path:
        return self.settings.media_dir() / Path(name).name

    def _store_image_for_run(self, run_date: str, source: Path) -> Path:
        media_dir = self.settings.media_dir()
        media_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in source.name)
        target = media_dir / f"{run_date}-{safe_name}"
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return target

    def _archive_to_notion(self, digest: DigestResult, selected: list[Any], dry_run: bool) -> None:
        if not self.notion.configured:
            return
        selected_by_pmid = {paper.pmid: paper for paper in selected}
        for digest_paper in digest.papers:
            source = selected_by_pmid.get(digest_paper.pmid)
            paper_dict = source.to_ai_dict() if source else {"pmid": digest_paper.pmid, "title": digest_paper.title}
            paper_dict.update(
                {
                    "japanese_summary": digest_paper.japanese_summary,
                    "clinical_takeaway": digest_paper.clinical_takeaway,
                    "topics": digest_paper.topics or paper_dict.get("topics", []),
                    "evidence_type": digest_paper.evidence_type or paper_dict.get("evidence_type", ""),
                    "status": "summarized",
                }
            )
            response = self.notion.create_paper_page(
                digest.run_date,
                paper_dict,
                digest.digest_summary,
                digest.image_prompt,
                digest.image_url,
                dry_run=dry_run,
            )
            page_id = response.get("id") if isinstance(response, dict) else ""
            if page_id and not dry_run:
                self.storage.mark_notion_page(digest.run_date, digest_paper.pmid, page_id)
