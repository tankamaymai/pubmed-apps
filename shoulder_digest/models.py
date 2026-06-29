from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any


@dataclass(slots=True)
class Paper:
    pmid: str
    title: str
    abstract: str
    journal: str = ""
    publication_date: str = ""
    pubmed_url: str = ""
    article_types: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    relevance_score: float = 0.0
    evidence_type: str = ""

    def to_ai_dict(self) -> dict[str, Any]:
        return {
            "pmid": self.pmid,
            "title": self.title,
            "abstract": self.abstract,
            "journal": self.journal,
            "publication_date": self.publication_date,
            "pubmed_url": self.pubmed_url,
            "article_types": self.article_types,
            "topics": self.topics,
            "relevance_score": self.relevance_score,
            "evidence_type": self.evidence_type,
        }


@dataclass(slots=True)
class DigestPaper:
    pmid: str
    title: str
    japanese_title: str = ""
    japanese_summary: str = ""
    clinical_takeaway: str = ""
    topics: list[str] = field(default_factory=list)
    evidence_type: str = ""


@dataclass(slots=True)
class DigestResult:
    run_date: str
    papers: list[DigestPaper]
    digest_summary: str
    image_prompt: str
    image_path: str = ""
    image_url: str = ""
    raw_ai_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_date": self.run_date,
            "papers": [
                {
                    "pmid": paper.pmid,
                    "title": paper.title,
                    "japanese_title": paper.japanese_title,
                    "japanese_summary": paper.japanese_summary,
                    "clinical_takeaway": paper.clinical_takeaway,
                    "topics": paper.topics,
                    "evidence_type": paper.evidence_type,
                }
                for paper in self.papers
            ],
            "digest_summary": self.digest_summary,
            "image_prompt": self.image_prompt,
            "image_path": self.image_path,
            "image_url": self.image_url,
            "raw_ai_text": self.raw_ai_text,
        }


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_iso() -> str:
    return date.today().isoformat()
