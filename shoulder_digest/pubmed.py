from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Iterable

from .models import Paper

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

SHOULDER_QUERY = (
    '("Shoulder Joint"[MeSH Terms] OR shoulder[Title/Abstract] OR '
    'glenohumeral[Title/Abstract] OR "rotator cuff"[Title/Abstract] OR '
    'supraspinatus[Title/Abstract] OR infraspinatus[Title/Abstract] OR '
    'subscapularis[Title/Abstract] OR "shoulder arthroplasty"[Title/Abstract] OR '
    '"reverse shoulder"[Title/Abstract] OR "shoulder instability"[Title/Abstract] OR '
    'labrum[Title/Abstract] OR labral[Title/Abstract] OR '
    '"adhesive capsulitis"[Title/Abstract] OR "frozen shoulder"[Title/Abstract] OR '
    'scapular[Title/Abstract] OR acromioclavicular[Title/Abstract] OR '
    '"shoulder rehabilitation"[Title/Abstract])'
)

TOPIC_WEIGHTS = {
    "rotator cuff": 5,
    "supraspinatus": 3,
    "glenohumeral": 4,
    "arthroplasty": 4,
    "reverse shoulder": 5,
    "instability": 4,
    "labrum": 3,
    "labral": 3,
    "adhesive capsulitis": 4,
    "frozen shoulder": 4,
    "rehabilitation": 3,
    "physical therapy": 3,
    "scapular": 2,
    "acromioclavicular": 2,
    "shoulder": 2,
}

ARTICLE_TYPE_WEIGHTS = {
    "Randomized Controlled Trial": 5,
    "Clinical Trial": 4,
    "Meta-Analysis": 5,
    "Systematic Review": 5,
    "Review": 2,
    "Practice Guideline": 4,
}

STRONG_SHOULDER_TERMS = {
    "rotator cuff",
    "supraspinatus",
    "glenohumeral",
    "arthroplasty",
    "reverse shoulder",
    "instability",
    "labrum",
    "labral",
    "adhesive capsulitis",
    "frozen shoulder",
    "acromioclavicular",
}


class PubMedClient:
    def __init__(self, api_key: str = "", email: str = "", tool: str = "shoulder-digest"):
        self.api_key = api_key
        self.email = email
        self.tool = tool

    def search_recent(self, run_date: str, retmax: int = 50, lookback_days: int = 1) -> list[str]:
        mindate, maxdate = pubmed_date_range(run_date, lookback_days)
        params = {
            "db": "pubmed",
            "term": SHOULDER_QUERY,
            "retmode": "json",
            "retmax": str(retmax),
            "sort": "pub+date",
            "datetype": "edat",
            "mindate": mindate,
            "maxdate": maxdate,
            "tool": self.tool,
        }
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{EUTILS_BASE}/esearch.fcgi?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": self.tool})
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("esearchresult", {}).get("idlist", [])

    def fetch_details(self, pmids: Iterable[str]) -> list[Paper]:
        ids = [pmid for pmid in pmids if pmid]
        if not ids:
            return []
        params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "xml",
            "rettype": "abstract",
            "tool": self.tool,
        }
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{EUTILS_BASE}/efetch.fcgi?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": self.tool})
        with urllib.request.urlopen(req, timeout=30) as response:
            xml_text = response.read().decode("utf-8")
        return parse_pubmed_xml(xml_text)


def _format_pubmed_date(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d").strftime("%Y/%m/%d")


def pubmed_date_range(run_date: str, lookback_days: int = 1) -> tuple[str, str]:
    end = datetime.strptime(run_date, "%Y-%m-%d").date()
    start = end - timedelta(days=max(1, lookback_days) - 1)
    return start.strftime("%Y/%m/%d"), end.strftime("%Y/%m/%d")


def default_run_date() -> str:
    # PubMed indexing can lag; yesterday is a pragmatic daily default.
    return (date.today() - timedelta(days=1)).isoformat()


def parse_pubmed_xml(xml_text: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = _text(article.find(".//PMID"))
        title = _flatten_text(article.find(".//ArticleTitle"))
        abstract = _abstract_text(article)
        journal = _text(article.find(".//Journal/ISOAbbreviation")) or _text(article.find(".//Journal/Title"))
        publication_date = _publication_date(article)
        article_types = [_text(node) for node in article.findall(".//PublicationType") if _text(node)]
        paper = Paper(
            pmid=pmid,
            title=title,
            abstract=abstract,
            journal=journal,
            publication_date=publication_date,
            pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            article_types=article_types,
        )
        score_paper(paper)
        papers.append(paper)
    return papers


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return " ".join(node.text.split())


def _flatten_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _abstract_text(article: ET.Element) -> str:
    parts = []
    for node in article.findall(".//Abstract/AbstractText"):
        label = node.attrib.get("Label", "").strip()
        text = _flatten_text(node)
        if not text:
            continue
        parts.append(f"{label}: {text}" if label else text)
    return "\n".join(parts)


def _publication_date(article: ET.Element) -> str:
    article_date = article.find(".//ArticleDate")
    if article_date is not None:
        year = _text(article_date.find("Year"))
        month = _text(article_date.find("Month")) or "01"
        day = _text(article_date.find("Day")) or "01"
        return _safe_date(year, month, day)
    pub_date = article.find(".//JournalIssue/PubDate")
    if pub_date is None:
        return ""
    year = _text(pub_date.find("Year"))
    month = _month_to_number(_text(pub_date.find("Month"))) or "01"
    day = _text(pub_date.find("Day")) or "01"
    return _safe_date(year, month, day)


def _safe_date(year: str, month: str, day: str) -> str:
    if not year:
        return ""
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return year


def _month_to_number(value: str) -> str:
    if not value:
        return ""
    if value.isdigit():
        return value.zfill(2)
    months = {
        "jan": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "may": "05",
        "jun": "06",
        "jul": "07",
        "aug": "08",
        "sep": "09",
        "oct": "10",
        "nov": "11",
        "dec": "12",
    }
    return months.get(value[:3].lower(), "")


def score_paper(paper: Paper) -> Paper:
    haystack = f"{paper.title}\n{paper.abstract}".lower()
    topics: list[str] = []
    score = 0.0
    for topic, weight in TOPIC_WEIGHTS.items():
        if topic in haystack:
            topics.append(topic)
            score += weight
    for article_type in paper.article_types:
        for key, weight in ARTICLE_TYPE_WEIGHTS.items():
            if key.lower() == article_type.lower():
                score += weight
                if not paper.evidence_type:
                    paper.evidence_type = key
    if re.search(r"\b(randomi[sz]ed|trial|cohort|registry|meta-analysis|systematic review)\b", haystack):
        score += 2
    if len(paper.abstract) >= 500:
        score += 1
    paper.topics = topics
    paper.relevance_score = score
    if not paper.evidence_type:
        paper.evidence_type = paper.article_types[0] if paper.article_types else "Article"
    return paper


def select_top_papers(papers: list[Paper], seen_pmids: set[str], limit: int = 3) -> list[Paper]:
    candidates = [
        paper
        for paper in papers
        if paper.pmid not in seen_pmids
        and len(paper.abstract.strip()) >= 80
        and paper.relevance_score > 0
        and is_shoulder_focused(paper)
    ]
    return sorted(candidates, key=lambda paper: (paper.relevance_score, paper.publication_date, paper.pmid), reverse=True)[
        :limit
    ]


def is_shoulder_focused(paper: Paper) -> bool:
    title = paper.title.lower()
    if any(term in title for term in TOPIC_WEIGHTS):
        return True
    return any(topic in STRONG_SHOULDER_TERMS for topic in paper.topics)
