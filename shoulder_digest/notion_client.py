from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


EXPECTED_PROPERTIES = {
    "Title": "title",
    "PMID": "rich_text",
    "PubMed URL": "url",
    "Publication Date": "date",
    "Journal": "rich_text",
    "Topics": "multi_select",
    "Evidence Type": "rich_text",
    "Relevance Score": "number",
    "Japanese Summary": "rich_text",
    "Image Prompt": "rich_text",
    "Image Path/URL": "url",
    "Run Date": "date",
    "Status": "rich_text",
    "LINE Delivered": "checkbox",
    "Error": "rich_text",
}


class NotionClient:
    def __init__(
        self,
        token: str,
        database_id: str,
        notion_version: str = "2022-06-28",
        api_base_url: str = "https://api.notion.com",
    ):
        self.token = token
        self.database_id = database_id
        self.notion_version = notion_version
        self.api_base_url = api_base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.token and self.database_id)

    def create_paper_page(
        self,
        run_date: str,
        paper: dict[str, Any],
        digest_summary: str,
        image_prompt: str,
        image_url: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": {
                "Title": {"title": [{"text": {"content": paper.get("title", "Untitled")[:2000]}}]},
                "PMID": {"rich_text": [{"text": {"content": str(paper.get("pmid", ""))}}]},
                "PubMed URL": {"url": paper.get("pubmed_url") or f"https://pubmed.ncbi.nlm.nih.gov/{paper.get('pmid', '')}/"},
                "Publication Date": {"date": {"start": paper.get("publication_date") or run_date}},
                "Journal": {"rich_text": [{"text": {"content": paper.get("journal", "")[:2000]}}]},
                "Relevance Score": {"number": float(paper.get("relevance_score") or 0)},
                "Japanese Summary": {"rich_text": [{"text": {"content": paper.get("japanese_summary", "")[:2000]}}]},
                "Image Prompt": {"rich_text": [{"text": {"content": image_prompt[:2000]}}]},
                "Image Path/URL": {"url": image_url or None},
                "Run Date": {"date": {"start": run_date}},
                "Status": {"rich_text": [{"text": {"content": paper.get("status", "summarized")}}]},
                "LINE Delivered": {"checkbox": False},
                "Error": {"rich_text": [{"text": {"content": paper.get("error", "")[:2000]}}]},
            },
            "children": self._build_page_blocks(paper, digest_summary, image_url),
        }
        topics = paper.get("topics") or []
        if topics:
            payload["properties"]["Topics"] = {
                "multi_select": [{"name": str(topic)[:100]} for topic in topics[:10]]
            }
        evidence_type = paper.get("evidence_type")
        if evidence_type:
            payload["properties"]["Evidence Type"] = {
                "rich_text": [{"text": {"content": str(evidence_type)[:2000]}}]
            }
        if dry_run:
            return {"dryRun": True, "payload": payload}
        return self._request(f"{self.api_base_url}/v1/pages", payload)

    def mark_delivered(self, page_id: str, dry_run: bool = False) -> dict[str, Any]:
        payload = {
            "properties": {
                "LINE Delivered": {"checkbox": True},
                "Status": {"rich_text": [{"text": {"content": "delivered"}}]},
            }
        }
        if dry_run:
            return {"dryRun": True, "payload": payload}
        return self._request(f"{self.api_base_url}/v1/pages/{page_id}", payload, method="PATCH")

    @staticmethod
    def _build_page_blocks(paper: dict[str, Any], digest_summary: str, image_url: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        sections = [
            ("概要", digest_summary),
            ("要約", paper.get("japanese_summary", "")),
            ("臨床的ポイント", paper.get("clinical_takeaway", "")),
            ("Abstract", paper.get("abstract", "")),
        ]
        for heading, text in sections:
            content = str(text or "").strip()
            if not content:
                continue
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": [{"type": "text", "text": {"content": heading}}]},
                }
            )
            blocks.extend(_paragraph_blocks(content))
        if image_url:
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": [{"type": "text", "text": {"content": "グラレコ"}}]},
                }
            )
            blocks.append(
                {
                    "object": "block",
                    "type": "image",
                    "image": {"type": "external", "external": {"url": image_url}},
                }
            )
        if not blocks:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": "（内容なし）"}}]},
                }
            )
        return blocks

    def fetch_database(self) -> dict[str, Any]:
        return self._request(f"{self.api_base_url}/v1/databases/{self.database_id}", None, method="GET")

    def validate_database(self) -> dict[str, Any]:
        database = self.fetch_database()
        properties = database.get("properties", {})
        missing: list[str] = []
        mismatched: list[dict[str, str]] = []
        for name, expected_type in EXPECTED_PROPERTIES.items():
            prop = properties.get(name)
            if not prop:
                missing.append(name)
                continue
            actual_type = prop.get("type", "")
            if actual_type != expected_type:
                mismatched.append({"property": name, "expected": expected_type, "actual": actual_type})
        return {"ok": not missing and not mismatched, "missing": missing, "mismatched": mismatched}

    def _request(self, url: str, payload: dict[str, Any] | None, method: str = "POST") -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("NOTION_TOKEN and NOTION_DATABASE_ID are required")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Notion-Version": self.notion_version,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Notion API {exc.code}: {body}") from exc


def _paragraph_blocks(text: str, chunk_size: int = 1800) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    remaining = text.strip()
    while remaining:
        chunk = remaining[:chunk_size]
        remaining = remaining[chunk_size:]
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
            }
        )
    return blocks
