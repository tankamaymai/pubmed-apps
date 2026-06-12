from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import DigestResult, Paper, utc_now_iso


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def session(self) -> Any:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_date TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    digest_summary TEXT NOT NULL DEFAULT '',
                    image_prompt TEXT NOT NULL DEFAULT '',
                    image_path TEXT NOT NULL DEFAULT '',
                    image_url TEXT NOT NULL DEFAULT '',
                    raw_ai_text TEXT NOT NULL DEFAULT '',
                    line_payload TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS papers (
                    run_date TEXT NOT NULL,
                    pmid TEXT NOT NULL,
                    title TEXT NOT NULL,
                    abstract TEXT NOT NULL DEFAULT '',
                    journal TEXT NOT NULL DEFAULT '',
                    publication_date TEXT NOT NULL DEFAULT '',
                    pubmed_url TEXT NOT NULL DEFAULT '',
                    article_types TEXT NOT NULL DEFAULT '[]',
                    topics TEXT NOT NULL DEFAULT '[]',
                    relevance_score REAL NOT NULL DEFAULT 0,
                    evidence_type TEXT NOT NULL DEFAULT '',
                    japanese_summary TEXT NOT NULL DEFAULT '',
                    clinical_takeaway TEXT NOT NULL DEFAULT '',
                    notion_page_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (run_date, pmid)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS delivered_pmids (
                    pmid TEXT PRIMARY KEY,
                    delivered_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO delivered_pmids(pmid, delivered_at)
                SELECT p.pmid, r.updated_at
                FROM papers p
                JOIN runs r ON r.run_date = p.run_date
                WHERE p.status = 'delivered' OR r.status = 'delivered'
                """
            )

    def set_setting(self, key: str, value: str) -> None:
        with self.session() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self.session() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def known_pmids(self) -> set[str]:
        with self.session() as conn:
            rows = conn.execute("SELECT pmid FROM delivered_pmids").fetchall()
        return {row["pmid"] for row in rows}

    def mark_pmids_delivered(self, pmids: list[str]) -> None:
        now = utc_now_iso()
        with self.session() as conn:
            for pmid in pmids:
                if pmid:
                    conn.execute(
                        "INSERT OR IGNORE INTO delivered_pmids(pmid, delivered_at) VALUES(?, ?)",
                        (pmid, now),
                    )

    def upsert_run(self, run_date: str, status: str, dry_run: bool, error: str = "") -> None:
        now = utc_now_iso()
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO runs(run_date, status, dry_run, created_at, updated_at, error)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_date) DO UPDATE SET
                    status=excluded.status,
                    dry_run=excluded.dry_run,
                    updated_at=excluded.updated_at,
                    error=excluded.error
                """,
                (run_date, status, int(dry_run), now, now, error),
            )

    def clear_run_papers(self, run_date: str) -> None:
        with self.session() as conn:
            conn.execute("DELETE FROM papers WHERE run_date = ?", (run_date,))

    def save_candidates(self, run_date: str, papers: list[Paper]) -> None:
        with self.session() as conn:
            for paper in papers:
                conn.execute(
                    """
                    INSERT INTO papers(
                        run_date, pmid, title, abstract, journal, publication_date,
                        pubmed_url, article_types, topics, relevance_score, evidence_type, status
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_date, pmid) DO UPDATE SET
                        title=excluded.title,
                        abstract=excluded.abstract,
                        journal=excluded.journal,
                        publication_date=excluded.publication_date,
                        pubmed_url=excluded.pubmed_url,
                        article_types=excluded.article_types,
                        topics=excluded.topics,
                        relevance_score=excluded.relevance_score,
                        evidence_type=excluded.evidence_type
                    """,
                    (
                        run_date,
                        paper.pmid,
                        paper.title,
                        paper.abstract,
                        paper.journal,
                        paper.publication_date,
                        paper.pubmed_url,
                        json.dumps(paper.article_types, ensure_ascii=False),
                        json.dumps(paper.topics, ensure_ascii=False),
                        paper.relevance_score,
                        paper.evidence_type,
                        "candidate",
                    ),
                )

    def save_digest(self, digest: DigestResult) -> None:
        now = utc_now_iso()
        with self.session() as conn:
            conn.execute(
                """
                UPDATE runs SET
                    status = ?,
                    updated_at = ?,
                    digest_summary = ?,
                    image_prompt = ?,
                    image_path = ?,
                    image_url = ?,
                    raw_ai_text = ?,
                    error = ''
                WHERE run_date = ?
                """,
                (
                    "ready_for_approval",
                    now,
                    digest.digest_summary,
                    digest.image_prompt,
                    digest.image_path,
                    digest.image_url,
                    digest.raw_ai_text,
                    digest.run_date,
                ),
            )
            for paper in digest.papers:
                conn.execute(
                    """
                    UPDATE papers SET
                        japanese_summary = ?,
                        clinical_takeaway = ?,
                        topics = ?,
                        evidence_type = ?,
                        status = ?
                    WHERE run_date = ? AND pmid = ?
                    """,
                    (
                        paper.japanese_summary,
                        paper.clinical_takeaway,
                        json.dumps(paper.topics, ensure_ascii=False),
                        paper.evidence_type,
                        "summarized",
                        digest.run_date,
                        paper.pmid,
                    ),
                )

    def mark_notion_page(self, run_date: str, pmid: str, page_id: str) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE papers SET notion_page_id = ? WHERE run_date = ? AND pmid = ?",
                (page_id, run_date, pmid),
            )

    def save_line_payload(self, run_date: str, payload: dict[str, Any], delivered: bool) -> None:
        status = "delivered" if delivered else "ready_for_approval"
        delivered_pmids: list[str] = []
        with self.session() as conn:
            conn.execute(
                "UPDATE runs SET line_payload = ?, status = ?, updated_at = ? WHERE run_date = ?",
                (json.dumps(payload, ensure_ascii=False), status, utc_now_iso(), run_date),
            )
            if delivered:
                conn.execute("UPDATE papers SET status = ? WHERE run_date = ?", ("delivered", run_date))
                delivered_pmids = [
                    row["pmid"]
                    for row in conn.execute("SELECT pmid FROM papers WHERE run_date = ?", (run_date,)).fetchall()
                ]
        if delivered:
            self.mark_pmids_delivered(delivered_pmids)

    def mark_error(self, run_date: str, error: str) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE run_date = ?",
                ("error", error, utc_now_iso(), run_date),
            )

    def get_run(self, run_date: str) -> dict[str, Any] | None:
        with self.session() as conn:
            run = conn.execute("SELECT * FROM runs WHERE run_date = ?", (run_date,)).fetchone()
            if not run:
                return None
            papers = conn.execute(
                "SELECT * FROM papers WHERE run_date = ? ORDER BY relevance_score DESC, pmid DESC",
                (run_date,),
            ).fetchall()
        data = dict(run)
        data["papers"] = [self._paper_row_to_dict(row) for row in papers]
        return data

    def latest_run_date(self) -> str:
        with self.session() as conn:
            row = conn.execute("SELECT run_date FROM runs ORDER BY run_date DESC LIMIT 1").fetchone()
        return row["run_date"] if row else ""

    @staticmethod
    def _paper_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key in ("article_types", "topics"):
            try:
                data[key] = json.loads(data.get(key) or "[]")
            except json.JSONDecodeError:
                data[key] = []
        return data
