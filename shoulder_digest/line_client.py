from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
import urllib.request
from typing import Any


class LineClient:
    def __init__(
        self,
        channel_access_token: str,
        channel_secret: str = "",
        api_base_url: str = "https://api.line.me",
    ):
        self.channel_access_token = channel_access_token
        self.channel_secret = channel_secret
        self.api_base_url = api_base_url.rstrip("/")

    def verify_signature(self, body: bytes, signature: str) -> bool:
        if not self.channel_secret or not signature:
            return False
        digest = hmac.new(self.channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode("ascii")
        return hmac.compare_digest(expected, signature)

    def push(self, to: str, messages: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
        payload = {"to": to, "messages": messages}
        if dry_run:
            return {"dryRun": True, "payload": payload}
        if not self.channel_access_token:
            raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is not configured")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.api_base_url}/v2/bot/message/push",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.channel_access_token}",
                "Content-Type": "application/json",
                "X-Line-Retry-Key": str(uuid.uuid4()),
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            response_body = response.read().decode("utf-8")
        return {"status": "sent", "response": response_body, "payload": payload}


def build_line_messages(
    run_date: str,
    image_url: str,
    digest_summary: str,
    papers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lines = [f"肩関節PubMedダイジェスト {run_date}", "", digest_summary, ""]
    for idx, paper in enumerate(papers, start=1):
        title = paper.get("title", "")
        pmid = paper.get("pmid", "")
        summary = paper.get("japanese_summary", "")
        pubmed_url = paper.get("pubmed_url") or f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        lines.extend([f"{idx}. {title}", f"PMID: {pmid}", summary, pubmed_url, ""])
    text = "\n".join(lines).strip()
    messages: list[dict[str, Any]] = []
    if image_url:
        messages.append(
            {
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            }
        )
    messages.append({"type": "text", "text": text[:4900]})
    return messages
