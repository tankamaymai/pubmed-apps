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
from .obsidian_client import ObsidianVaultWriter
from .ngrok_sync import rebuild_image_url, sync_public_base_url, verify_image_url
from .pubmed import PubMedClient, default_run_date, search_top_papers
from .storage import Storage


class ShoulderDigestApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings.db_path)
        self.pubmed = PubMedClient(settings.ncbi_api_key, settings.ncbi_email, settings.ncbi_tool)
        self.codex = CodexAppServerClient(
            settings.codex_bin,
            settings.codex_model,
            Path.cwd(),
            turn_timeout_seconds=settings.codex_turn_timeout_seconds,
            image_turn_timeout_seconds=settings.codex_image_turn_timeout_seconds,
        )
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
        self.obsidian = ObsidianVaultWriter(settings.obsidian_vault, settings.obsidian_notes_dir)

    def run_daily(
        self,
        run_date: str | None = None,
        dry_run: bool = False,
        pmid: str = "",
    ) -> dict[str, Any]:
        run_date = run_date or default_run_date()
        public_url_sync = self._sync_public_base_url()
        self.storage.upsert_run(run_date, "running", dry_run)
        try:
            if pmid:
                if pmid in self.storage.known_pmids():
                    self.storage.upsert_run(run_date, "delivered", dry_run)
                    return {
                        "runDate": run_date,
                        "status": "already_delivered",
                        "pmid": pmid,
                    }
                selected = self.pubmed.fetch_details([pmid])
                lookback_used = 0
                pmids = [pmid] if selected else []
            else:
                selected, lookback_used, pmids = search_top_papers(
                    self.pubmed,
                    run_date,
                    self.storage.known_pmids(),
                    limit=self.settings.top_paper_count,
                    lookback_days=self.settings.pubmed_lookback_days,
                    max_lookback_days=self.settings.pubmed_max_lookback_days,
                    arthroplasty_deliveries_this_month=self.storage.arthroplasty_deliveries_in_month(run_date),
                )
            self.storage.clear_run_papers(run_date)
            self.storage.save_candidates(run_date, selected)
            if not selected:
                self.storage.upsert_run(run_date, "no_candidates", dry_run)
                return {"runDate": run_date, "status": "no_candidates", "pmids": pmids, "lookbackDays": lookback_used}

            digest = summarize_with_codex(run_date, selected, self.codex, mock=self.settings.mock_ai)
            image_path = generate_image_with_codex(
                digest,
                self.codex,
                self.watcher,
                mock=self.settings.mock_ai,
                image_wait_seconds=self.settings.codex_image_wait_seconds,
            )
            if image_path:
                stored_image = self._store_image_for_run(run_date, image_path)
                digest.image_path = str(stored_image)
                digest.image_url = self.public_image_url(stored_image)
            elif self.settings.mock_ai:
                digest.image_path = ""
                digest.image_url = ""
            self.storage.save_digest(digest)
            notion_archive = self.archive_notion_for_run(run_date, dry_run=dry_run, mark_delivered=False)
            self._archive_to_obsidian(digest, selected, dry_run=dry_run)
            response = {
                "runDate": run_date,
                "status": "ready_for_approval",
                "digest": digest.to_dict(),
                "lookbackDays": lookback_used,
                "notionArchive": notion_archive,
                "publicUrlSync": public_url_sync,
            }
            if self.settings.auto_send and not dry_run:
                line_delivery = self.approve_send(run_date, dry_run=False)
                response["lineDelivery"] = line_delivery
                if line_delivery.get("status") != "skipped":
                    response["status"] = "delivered"
            return response
        except Exception as exc:
            self.storage.mark_error(run_date, str(exc))
            raise

    def approve_send(self, run_date: str, dry_run: bool = False) -> dict[str, Any]:
        run = self.storage.get_run(run_date)
        if not run:
            raise RuntimeError(f"Run not found: {run_date}")
        if run.get("status") not in {"ready_for_approval", "delivered"}:
            raise RuntimeError(
                f"Run {run_date} is not ready to send (status={run.get('status', 'unknown')}). Run the daily job first."
            )
        pmids = self.storage.extract_pmids_from_run(run)
        already_delivered = self.storage.already_delivered_pmids(pmids)
        if already_delivered and not dry_run:
            return {
                "status": "skipped",
                "reason": "already_delivered",
                "pmids": already_delivered,
            }
        group_id = self.settings.line_group_id or self.storage.get_setting("line_group_id")
        if not group_id:
            raise RuntimeError("LINE group ID is not configured. Add the bot to a group and receive a webhook first.")
        public_url_sync = self._sync_public_base_url()
        image_url = self._current_image_url(run)
        if not image_url and not dry_run:
            raise RuntimeError("Image URL is empty. Set SHOULDER_DIGEST_PUBLIC_BASE_URL before LINE image delivery.")
        if image_url and not dry_run:
            image_check = verify_image_url(image_url)
            if not image_check.get("ok"):
                raise RuntimeError(
                    "Image URL is not publicly reachable for LINE: "
                    f"{image_check.get('reason', 'unknown error')}. "
                    "Start ngrok with scripts/start_shoulder_digest.ps1 and retry."
                )
        messages = build_line_messages(
            run_date,
            image_url,
            run.get("digest_summary", ""),
            run.get("papers", []),
        )
        result = self.line.push(group_id, messages, dry_run=dry_run)
        result["publicUrlSync"] = public_url_sync
        self.storage.save_line_payload(run_date, result.get("payload", result), delivered=not dry_run)
        notion_archive = self.archive_notion_for_run(run_date, dry_run=dry_run, mark_delivered=not dry_run)
        if notion_archive.get("results"):
            result["notionArchive"] = notion_archive
        if not dry_run and self.obsidian.configured:
            self.obsidian.mark_delivered(run_date, dry_run=False)
        return result

    def resend_image(self, run_date: str, dry_run: bool = False) -> dict[str, Any]:
        run = self.storage.get_run(run_date)
        if not run:
            raise RuntimeError(f"Run not found: {run_date}")
        if not str(run.get("image_path") or "").strip():
            raise RuntimeError(f"Run {run_date} has no generated image.")
        group_id = self.settings.line_group_id or self.storage.get_setting("line_group_id")
        if not group_id:
            raise RuntimeError("LINE group ID is not configured.")
        public_url_sync = self._sync_public_base_url()
        image_url = self._current_image_url(run)
        if not image_url and not dry_run:
            raise RuntimeError("Image URL is empty. Start ngrok and sync the public URL first.")
        if image_url and not dry_run:
            image_check = verify_image_url(image_url)
            if not image_check.get("ok"):
                raise RuntimeError(
                    "Image URL is not publicly reachable for LINE: "
                    f"{image_check.get('reason', 'unknown error')}"
                )
        messages = [
            {
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            }
        ]
        result = self.line.push(group_id, messages, dry_run=dry_run)
        result["publicUrlSync"] = public_url_sync
        result["imageUrl"] = image_url
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

    def _sync_public_base_url(self) -> dict[str, Any]:
        try:
            result = sync_public_base_url(env_path=Path(".env"), port=self.settings.port)
        except FileNotFoundError as exc:
            return {"ok": False, "reason": str(exc)}
        except OSError as exc:
            return {"ok": False, "reason": str(exc)}
        if result.get("ok") and result.get("url"):
            self.settings.public_base_url = str(result["url"])
        return result

    def _current_image_url(self, run: dict[str, Any]) -> str:
        image_path = str(run.get("image_path") or "")
        if image_path and self.settings.public_base_url:
            refreshed = rebuild_image_url(self.settings.public_base_url, image_path)
            if refreshed and refreshed != run.get("image_url"):
                self.storage.update_image_url(str(run.get("run_date", "")), refreshed)
            return refreshed
        return str(run.get("image_url") or "")

    def public_image_url(self, path: Path) -> str:
        if not self.settings.public_base_url:
            return ""
        return rebuild_image_url(self.settings.public_base_url, str(path))

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

    def archive_notion_for_run(
        self,
        run_date: str,
        dry_run: bool = False,
        mark_delivered: bool | None = None,
    ) -> dict[str, Any]:
        if not self.notion.configured:
            return {"skipped": True, "reason": "NOTION_TOKEN or NOTION_DATABASE_ID is not configured"}

        run = self.storage.get_run(run_date)
        if not run or not run.get("papers"):
            return {"skipped": True, "reason": f"No papers found for run {run_date}"}

        if mark_delivered is None:
            mark_delivered = run.get("status") == "delivered"

        results: list[dict[str, Any]] = []
        for paper in run["papers"]:
            page_id = paper.get("notion_page_id") or ""
            if page_id:
                if mark_delivered and not dry_run:
                    try:
                        self.notion.mark_delivered(page_id, dry_run=False)
                        results.append({"pmid": paper.get("pmid", ""), "status": "delivered", "page_id": page_id})
                    except Exception as exc:
                        self.storage.mark_notion_error(run_date, paper.get("pmid", ""), str(exc))
                        results.append({"pmid": paper.get("pmid", ""), "status": "error", "error": str(exc)})
                else:
                    results.append({"pmid": paper.get("pmid", ""), "status": "exists", "page_id": page_id})
                continue

            paper_dict = dict(paper)
            paper_dict["status"] = "delivered" if mark_delivered else paper_dict.get("status") or "summarized"
            try:
                response = self.notion.create_paper_page(
                    run_date,
                    paper_dict,
                    run.get("digest_summary", ""),
                    run.get("image_prompt", ""),
                    run.get("image_url", ""),
                    dry_run=dry_run,
                )
                page_id = response.get("id") if isinstance(response, dict) else ""
                if page_id and not dry_run:
                    self.storage.mark_notion_page(run_date, paper.get("pmid", ""), page_id)
                    if mark_delivered:
                        self.notion.mark_delivered(page_id, dry_run=False)
                results.append(
                    {
                        "pmid": paper.get("pmid", ""),
                        "status": "created" if page_id or dry_run else "missing_id",
                        "page_id": page_id,
                        "dry_run": dry_run,
                    }
                )
            except Exception as exc:
                self.storage.mark_notion_error(run_date, paper.get("pmid", ""), str(exc))
                results.append({"pmid": paper.get("pmid", ""), "status": "error", "error": str(exc)})

        ok = all(item.get("status") in {"created", "exists", "delivered"} or item.get("dry_run") for item in results)
        return {"runDate": run_date, "ok": ok, "results": results}

    def _archive_to_obsidian(self, digest: DigestResult, selected: list[Any], dry_run: bool) -> None:
        if not self.obsidian.configured:
            return
        selected_by_pmid = {paper.pmid: paper for paper in selected}
        papers: list[dict[str, Any]] = []
        for digest_paper in digest.papers:
            source = selected_by_pmid.get(digest_paper.pmid)
            paper_dict = source.to_ai_dict() if source else {"pmid": digest_paper.pmid, "title": digest_paper.title}
            paper_dict.update(
                {
                    "japanese_title": digest_paper.japanese_title,
                    "japanese_summary": digest_paper.japanese_summary,
                    "clinical_takeaway": digest_paper.clinical_takeaway,
                    "topics": digest_paper.topics or paper_dict.get("topics", []),
                    "evidence_type": digest_paper.evidence_type or paper_dict.get("evidence_type", ""),
                }
            )
            papers.append(paper_dict)
        self.obsidian.save_digest(
            digest.run_date,
            digest.digest_summary,
            digest.image_prompt,
            papers,
            source_image_path=digest.image_path,
            status="ready_for_approval",
            dry_run=dry_run,
        )
