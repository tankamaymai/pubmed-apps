from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import DigestResult, Paper, utc_now_iso
from .pubmed import is_arthroplasty_text

PMID_PATTERN = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", re.IGNORECASE)


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
                    delivered_at TEXT NOT NULL,
                    run_date TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS line_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_date TEXT NOT NULL,
                    pmid TEXT NOT NULL,
                    delivered_at TEXT NOT NULL,
                    line_payload TEXT NOT NULL DEFAULT '',
                    UNIQUE(pmid)
                );
                """
            )
            try:
                conn.execute("ALTER TABLE delivered_pmids ADD COLUMN run_date TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            self._backfill_delivered_run_dates(conn)
            conn.execute("DELETE FROM line_deliveries WHERE pmid GLOB '????-??-??'")
            self._backfill_delivered_pmids_from_history(conn)
            self._sync_delivered_pmids_to_line_history(conn)

    @staticmethod
    def extract_pmids_from_text(text: str) -> list[str]:
        if not text:
            return []
        return list(dict.fromkeys(PMID_PATTERN.findall(text)))

    @classmethod
    def extract_pmids_from_run(cls, run: dict[str, Any]) -> list[str]:
        pmids: list[str] = []
        for paper in run.get("papers", []):
            pmid = str(paper.get("pmid", "")).strip()
            if pmid:
                pmids.append(pmid)
        if pmids:
            return list(dict.fromkeys(pmids))

        raw_ai_text = str(run.get("raw_ai_text", ""))
        if raw_ai_text:
            try:
                payload = json.loads(raw_ai_text)
            except json.JSONDecodeError:
                pmids.extend(cls.extract_pmids_from_text(raw_ai_text))
            else:
                for paper in payload.get("papers", []):
                    pmid = str(paper.get("pmid", "")).strip()
                    if pmid:
                        pmids.append(pmid)
        line_payload = str(run.get("line_payload", ""))
        if line_payload:
            try:
                payload = json.loads(line_payload)
            except json.JSONDecodeError:
                pmids.extend(cls.extract_pmids_from_text(line_payload))
            else:
                pmids.extend(cls.extract_pmids_from_text(json.dumps(payload, ensure_ascii=False)))
        return list(dict.fromkeys(pmids))

    def _backfill_delivered_pmids_from_history(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT run_date, line_payload, raw_ai_text, updated_at FROM runs "
            "WHERE line_payload != '' OR raw_ai_text != ''"
        ).fetchall()
        for row in rows:
            pmids = self.extract_pmids_from_run(dict(row))
            if not pmids:
                continue
            delivered_at = row["updated_at"] or utc_now_iso()
            for pmid in pmids:
                conn.execute(
                    """
                    INSERT INTO delivered_pmids(pmid, delivered_at, run_date)
                    VALUES(?, ?, ?)
                    ON CONFLICT(pmid) DO NOTHING
                    """,
                    (pmid, delivered_at, row["run_date"]),
                )
                conn.execute(
                    """
                    INSERT INTO line_deliveries(run_date, pmid, delivered_at, line_payload)
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(pmid) DO NOTHING
                    """,
                    (row["run_date"], pmid, delivered_at, row["line_payload"] or ""),
                )

    def _sync_delivered_pmids_to_line_history(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "DELETE FROM delivered_pmids WHERE pmid NOT IN (SELECT pmid FROM line_deliveries)"
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO delivered_pmids(pmid, delivered_at, run_date)
            SELECT pmid, delivered_at, run_date FROM line_deliveries
            """
        )

    def _record_line_delivery(self, run_date: str, pmids: list[str], payload: dict[str, Any]) -> None:
        if not pmids:
            return
        now = utc_now_iso()
        payload_text = json.dumps(payload, ensure_ascii=False)
        with self.session() as conn:
            for pmid in pmids:
                if not pmid:
                    continue
                conn.execute(
                    """
                    INSERT INTO line_deliveries(run_date, pmid, delivered_at, line_payload)
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(pmid) DO NOTHING
                    """,
                    (run_date, pmid, now, payload_text),
                )
        self.mark_pmids_delivered(pmids, run_date)

    def already_delivered_pmids(self, pmids: list[str]) -> list[str]:
        if not pmids:
            return []
        known = self.known_pmids()
        return [pmid for pmid in pmids if pmid in known]

    def _backfill_delivered_run_dates(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT pmid FROM delivered_pmids WHERE run_date = '' OR run_date IS NULL"
        ).fetchall()
        for row in rows:
            pmid = row["pmid"]
            match = conn.execute(
                """
                SELECT run_date FROM runs
                WHERE line_payload LIKE ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (f"%{pmid}%",),
            ).fetchone()
            if match:
                conn.execute(
                    "UPDATE delivered_pmids SET run_date = ? WHERE pmid = ?",
                    (match["run_date"], pmid),
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
            rows = conn.execute("SELECT pmid FROM line_deliveries").fetchall()
        return {row["pmid"] for row in rows}

    def mark_pmids_delivered(self, pmids: list[str], run_date: str = "") -> None:
        now = utc_now_iso()
        with self.session() as conn:
            for pmid in pmids:
                if pmid:
                    conn.execute(
                        """
                        INSERT INTO delivered_pmids(pmid, delivered_at, run_date)
                        VALUES(?, ?, ?)
                        ON CONFLICT(pmid) DO UPDATE SET
                            delivered_at = excluded.delivered_at,
                            run_date = excluded.run_date
                        """,
                        (pmid, now, run_date),
                    )

    def arthroplasty_deliveries_in_month(self, run_date: str) -> int:
        month_prefix = run_date[:7]
        with self.session() as conn:
            run_dates = [
                row["run_date"]
                for row in conn.execute(
                    """
                    SELECT DISTINCT run_date FROM delivered_pmids
                    WHERE run_date LIKE ? AND run_date != ''
                    """,
                    (f"{month_prefix}%",),
                ).fetchall()
            ]
        return sum(1 for delivered_run_date in run_dates if self._run_was_arthroplasty_delivery(delivered_run_date))

    def _run_was_arthroplasty_delivery(self, run_date: str) -> bool:
        with self.session() as conn:
            papers = conn.execute(
                "SELECT title, abstract FROM papers WHERE run_date = ?",
                (run_date,),
            ).fetchall()
            if papers:
                return any(
                    is_arthroplasty_text(f"{row['title']}\n{row['abstract'] or ''}") for row in papers
                )
            run = conn.execute("SELECT raw_ai_text FROM runs WHERE run_date = ?", (run_date,)).fetchone()
        if not run or not run["raw_ai_text"]:
            return False
        try:
            payload = json.loads(run["raw_ai_text"])
        except json.JSONDecodeError:
            return is_arthroplasty_text(run["raw_ai_text"])
        for paper in payload.get("papers", []):
            text = f"{paper.get('title', '')}\n{paper.get('japanese_summary', '')}"
            if is_arthroplasty_text(text):
                return True
        return is_arthroplasty_text(str(payload.get("digest_summary", "")))

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

    def update_image_url(self, run_date: str, image_url: str) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE runs SET image_url = ?, updated_at = ? WHERE run_date = ?",
                (image_url, utc_now_iso(), run_date),
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
                cur = conn.execute(
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
                if cur.rowcount == 0:
                    conn.execute(
                        """
                        INSERT INTO papers(
                            run_date, pmid, title, abstract, journal, publication_date,
                            pubmed_url, article_types, topics, relevance_score, evidence_type,
                            japanese_summary, clinical_takeaway, status
                        )
                        VALUES(?, ?, ?, '', '', '', ?, '[]', ?, 0, ?, ?, ?, ?)
                        """,
                        (
                            digest.run_date,
                            paper.pmid,
                            paper.title,
                            f"https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/",
                            json.dumps(paper.topics, ensure_ascii=False),
                            paper.evidence_type,
                            paper.japanese_summary,
                            paper.clinical_takeaway,
                            "summarized",
                        ),
                    )
            digest_pmids = [paper.pmid for paper in digest.papers if paper.pmid]
            if digest_pmids:
                placeholders = ",".join("?" for _ in digest_pmids)
                conn.execute(
                    f"DELETE FROM papers WHERE run_date = ? AND pmid NOT IN ({placeholders})",
                    (digest.run_date, *digest_pmids),
                )

    def mark_notion_page(self, run_date: str, pmid: str, page_id: str) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE papers SET notion_page_id = ?, error = '' WHERE run_date = ? AND pmid = ?",
                (page_id, run_date, pmid),
            )

    def mark_notion_error(self, run_date: str, pmid: str, error: str) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE papers SET error = ? WHERE run_date = ? AND pmid = ?",
                (error[:2000], run_date, pmid),
            )

    def save_line_payload(self, run_date: str, payload: dict[str, Any], delivered: bool) -> None:
        status = "delivered" if delivered else "ready_for_approval"
        with self.session() as conn:
            conn.execute(
                "UPDATE runs SET line_payload = ?, status = ?, updated_at = ? WHERE run_date = ?",
                (json.dumps(payload, ensure_ascii=False), status, utc_now_iso(), run_date),
            )
            if delivered:
                conn.execute("UPDATE papers SET status = ? WHERE run_date = ?", ("delivered", run_date))
        if delivered:
            run = self.get_run(run_date) or {}
            delivered_pmids = self.extract_pmids_from_run(run)
            self._record_line_delivery(run_date, delivered_pmids, payload)

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
        db_papers = {str(row["pmid"]): self._paper_row_to_dict(row) for row in papers}
        raw_papers = self._papers_from_raw_ai(str(data.get("raw_ai_text", "")))
        if raw_papers:
            merged: list[dict[str, Any]] = []
            for raw_paper in raw_papers:
                pmid = str(raw_paper.get("pmid", "")).strip()
                base = db_papers.get(pmid, {})
                merged.append({**base, **raw_paper})
            data["papers"] = merged
        else:
            data["papers"] = list(db_papers.values())
        return data

    @staticmethod
    def _papers_from_raw_ai(raw_ai_text: str) -> list[dict[str, Any]]:
        if not raw_ai_text:
            return []
        try:
            payload = json.loads(raw_ai_text)
        except json.JSONDecodeError:
            return []
        papers: list[dict[str, Any]] = []
        for item in payload.get("papers", []):
            pmid = str(item.get("pmid", "")).strip()
            if not pmid:
                continue
            papers.append(
                {
                    "pmid": pmid,
                    "title": str(item.get("title", "")),
                    "japanese_summary": str(item.get("japanese_summary", "")),
                    "clinical_takeaway": str(item.get("clinical_takeaway", "")),
                    "pubmed_url": str(item.get("pubmed_url") or f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"),
                }
            )
        return papers

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
