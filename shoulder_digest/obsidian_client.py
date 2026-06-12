from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any


def _yaml_scalar(value: str) -> str:
    if not value:
        return '""'
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_list(items: list[str], indent: int = 0) -> str:
    if not items:
        return "[]"
    prefix = "  " * indent
    lines = [f"{prefix}- {_yaml_scalar(item)}" for item in items]
    return "\n".join(lines)


class ObsidianVaultWriter:
    def __init__(self, vault_path: Path, notes_dir: str = "PubMed肩関節"):
        self.vault_path = vault_path
        self.notes_dir = notes_dir.strip("/\\")

    @property
    def configured(self) -> bool:
        return bool(str(self.vault_path).strip())

    def notes_root(self) -> Path:
        return self.vault_path / self.notes_dir

    def attachments_dir(self) -> Path:
        return self.notes_root() / "attachments"

    def note_path_for_run(self, run_date: str) -> Path:
        return self.notes_root() / f"{run_date}.md"

    def save_digest(
        self,
        run_date: str,
        digest_summary: str,
        image_prompt: str,
        papers: list[dict[str, Any]],
        source_image_path: str = "",
        status: str = "ready_for_approval",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if not self.configured:
            return {"skipped": True, "reason": "OBSIDIAN_VAULT is not configured"}

        note_path = self.note_path_for_run(run_date)
        image_ref = ""
        stored_image_path = ""
        if source_image_path:
            source = Path(source_image_path)
            if source.exists():
                attachment_name = f"{run_date}-{source.name}"
                target = self.attachments_dir() / attachment_name
                image_ref = f"attachments/{attachment_name}"
                stored_image_path = str(target)
                if not dry_run:
                    self.attachments_dir().mkdir(parents=True, exist_ok=True)
                    if source.resolve() != target.resolve():
                        shutil.copy2(source, target)

        content = self._render_note(
            run_date=run_date,
            digest_summary=digest_summary,
            image_prompt=image_prompt,
            papers=papers,
            image_ref=image_ref,
            status=status,
        )
        result = {
            "note_path": str(note_path),
            "image_path": stored_image_path,
            "image_ref": image_ref,
            "dry_run": dry_run,
        }
        if dry_run:
            result["content_preview"] = content[:500]
            return result

        self.notes_root().mkdir(parents=True, exist_ok=True)
        note_path.write_text(content, encoding="utf-8")
        return result

    def mark_delivered(self, run_date: str, dry_run: bool = False) -> dict[str, Any]:
        if not self.configured:
            return {"skipped": True, "reason": "OBSIDIAN_VAULT is not configured"}

        note_path = self.note_path_for_run(run_date)
        if not note_path.exists():
            return {"skipped": True, "reason": f"note not found: {note_path}"}

        content = note_path.read_text(encoding="utf-8")
        updated = re.sub(
            r"(?m)^status:\s*.+$",
            "status: delivered",
            content,
            count=1,
        )
        if updated == content:
            updated = f"---\nstatus: delivered\n---\n\n{content.lstrip()}"

        result = {"note_path": str(note_path), "dry_run": dry_run}
        if dry_run:
            return result

        note_path.write_text(updated, encoding="utf-8")
        return result

    def validate_vault(self) -> dict[str, Any]:
        if not self.configured:
            return {"checked": False, "reason": "OBSIDIAN_VAULT is not configured"}
        if not self.vault_path.exists():
            return {"checked": True, "ok": False, "error": f"vault path does not exist: {self.vault_path}"}
        if not self.vault_path.is_dir():
            return {"checked": True, "ok": False, "error": f"vault path is not a directory: {self.vault_path}"}
        return {
            "checked": True,
            "ok": True,
            "vault_path": str(self.vault_path),
            "notes_dir": self.notes_dir,
            "notes_root": str(self.notes_root()),
        }

    def _render_note(
        self,
        run_date: str,
        digest_summary: str,
        image_prompt: str,
        papers: list[dict[str, Any]],
        image_ref: str,
        status: str,
    ) -> str:
        pmids = [str(paper.get("pmid", "")) for paper in papers if paper.get("pmid")]
        frontmatter = [
            "---",
            f"run_date: {_yaml_scalar(run_date)}",
            f"status: {_yaml_scalar(status)}",
            "pmids:",
            _yaml_list(pmids, indent=1),
            "tags:",
            "  - shoulder-digest",
            "  - pubmed",
        ]
        if image_ref:
            frontmatter.append(f"image: {_yaml_scalar(image_ref)}")
        frontmatter.append("---")

        sections = [
            "\n".join(frontmatter),
            "",
            f"# 肩関節ダイジェスト {run_date}",
            "",
            "## 概要",
            digest_summary.strip() or "（要約なし）",
        ]
        if image_ref:
            sections.extend(["", "## グラレコ", f"![[{image_ref}]]"])
        if image_prompt.strip():
            sections.extend(["", "## 画像プロンプト", image_prompt.strip()])
        if papers:
            sections.extend(["", "## 論文"])
            for index, paper in enumerate(papers, start=1):
                title = paper.get("title") or "Untitled"
                pmid = paper.get("pmid") or ""
                pubmed_url = paper.get("pubmed_url") or f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                sections.extend(
                    [
                        "",
                        f"### {index}. {title}",
                        "",
                        f"- PMID: {pmid}",
                        f"- ジャーナル: {paper.get('journal', '')}",
                        f"- 公開日: {paper.get('publication_date', '')}",
                        f"- PubMed: {pubmed_url}",
                    ]
                )
                topics = paper.get("topics") or []
                if topics:
                    sections.append(f"- トピック: {', '.join(str(topic) for topic in topics)}")
                evidence_type = paper.get("evidence_type") or ""
                if evidence_type:
                    sections.append(f"- エビデンス: {evidence_type}")
                japanese_summary = paper.get("japanese_summary") or ""
                if japanese_summary:
                    sections.extend(["", "#### 要約", japanese_summary.strip()])
                clinical_takeaway = paper.get("clinical_takeaway") or ""
                if clinical_takeaway:
                    sections.extend(["", "#### 臨床的ポイント", clinical_takeaway.strip()])
                abstract = paper.get("abstract") or ""
                if abstract:
                    sections.extend(["", "#### Abstract", abstract.strip()])

        return "\n".join(sections).strip() + "\n"
