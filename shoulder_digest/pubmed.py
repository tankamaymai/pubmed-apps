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
    '"glenoid labrum"[Title/Abstract] OR "shoulder labrum"[Title/Abstract] OR '
    '("labrum"[Title/Abstract] AND shoulder[Title/Abstract]) OR '
    '("labral"[Title/Abstract] AND shoulder[Title/Abstract]) OR '
    '"adhesive capsulitis"[Title/Abstract] OR "frozen shoulder"[Title/Abstract] OR '
    'scapular[Title/Abstract] OR acromioclavicular[Title/Abstract] OR '
    '"shoulder rehabilitation"[Title/Abstract])'
)

NON_SHOULDER_JOINT_FILTER = (
    "NOT ("
    '"Hip Joint"[MeSH Terms] OR '
    'hip[Title/Abstract] OR '
    '"Knee Joint"[MeSH Terms] OR '
    'knee[Title/Abstract] OR '
    '"Ankle Joint"[MeSH Terms] OR '
    'ankle[Title/Abstract] OR '
    'patella[Title/Abstract] OR '
    '"femoral head"[Title/Abstract] OR '
    'acetabular[Title/Abstract] OR '
    'tibiofemoral[Title/Abstract]'
    ")"
)

CLINICAL_FILTER = (
    '(humans[MeSH Terms] NOT (animals[MeSH Terms] NOT humans[MeSH Terms])) AND ('
    '"Randomized Controlled Trial"[Publication Type] OR '
    '"Clinical Trial"[Publication Type] OR '
    '"Controlled Clinical Trial"[Publication Type] OR '
    '"Multicenter Study"[Publication Type] OR '
    '"Observational Study"[Publication Type] OR '
    '"Systematic Review"[Publication Type] OR '
    '"Meta-Analysis"[Publication Type] OR '
    '"Practice Guideline"[Publication Type] OR '
    '"Physical Therapy Modalities"[MeSH Terms] OR '
    '"Rehabilitation"[MeSH Terms] OR '
    '"Orthopedic Procedures"[MeSH Terms] OR '
    '"Treatment Outcome"[MeSH Terms] OR '
    '"Postoperative Care"[MeSH Terms] OR '
    'rehabilitation[Title/Abstract] OR '
    '"physical therapy"[Title/Abstract] OR '
    '"shoulder surgery"[Title/Abstract] OR '
    'postoperative[Title/Abstract] OR '
    'patients[Title/Abstract] OR '
    'hospital[Title/Abstract] OR '
    'outpatient[Title/Abstract]'
    ') AND NOT ('
    'occupational[Title/Abstract] OR '
    'ergonomics[Title/Abstract] OR '
    'workplace[Title/Abstract] OR '
    '"industrial workers"[Title/Abstract] OR '
    'exoskeleton[Title/Abstract] OR '
    'biomechanical[Title/Abstract] OR '
    'biomechanics[Title/Abstract] OR '
    'cadaveric[Title/Abstract] OR '
    '"in vitro"[Title/Abstract] OR '
    '"finite element"[Title/Abstract]'
    ')'
)

SHOULDER_CLINICAL_QUERY = f"({SHOULDER_QUERY}) AND {CLINICAL_FILTER} AND {NON_SHOULDER_JOINT_FILTER}"

TOPIC_WEIGHTS = {
    "rotator cuff": 5,
    "supraspinatus": 3,
    "glenohumeral": 4,
    "arthroplasty": 4,
    "reverse shoulder": 5,
    "shoulder instability": 4,
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
    "Randomized Controlled Trial": 8,
    "Clinical Trial": 7,
    "Meta-Analysis": 8,
    "Systematic Review": 8,
    "Practice Guideline": 7,
    "Multicenter Study": 6,
    "Observational Study": 5,
    "Comparative Study": 5,
    "Evaluation Study": 5,
    "Controlled Clinical Trial": 7,
    "Review": 3,
    "Case Reports": -2,
}

LOW_EVIDENCE_ARTICLE_TYPES = {
    "Letter",
    "Editorial",
    "Comment",
    "News",
    "Published Erratum",
    "Retraction of Publication",
}

CLINICAL_TEXT_WEIGHTS = {
    "randomized controlled trial": 4,
    "randomised controlled trial": 4,
    "prospective cohort": 3,
    "retrospective cohort": 3,
    "clinical outcomes": 3,
    "functional outcomes": 3,
    "patient-reported": 3,
    "patients underwent": 3,
    "rehabilitation protocol": 4,
    "physical therapy": 4,
    "postoperative": 3,
    "surgical treatment": 3,
    "conservative treatment": 3,
    "outpatient": 2,
    "hospital": 2,
}

NON_CLINICAL_TEXT_PENALTIES = {
    "in vitro": 8,
    "in vivo study": 6,
    "animal model": 8,
    "mouse model": 8,
    "rat model": 8,
    "cadaveric": 8,
    "cadaver study": 8,
    "finite element analysis": 8,
    "biomechanical analysis": 6,
    "biomechanics": 6,
    "anatomic study": 6,
    "anatomical study": 6,
    "exoskeleton": 10,
    "ergonomics": 10,
    "workplace": 8,
    "industrial worker": 8,
    "drilling performance": 10,
}

HARD_NON_CLINICAL_TEXT_TERMS = frozenset(
    {
        "in vitro",
        "animal model",
        "mouse model",
        "rat model",
        "cadaveric",
        "cadaver study",
        "finite element analysis",
        "exoskeleton",
        "drilling performance",
    }
)

STRONG_CLINICAL_ARTICLE_TYPES = {
    "Randomized Controlled Trial",
    "Clinical Trial",
    "Controlled Clinical Trial",
    "Meta-Analysis",
    "Systematic Review",
    "Practice Guideline",
    "Multicenter Study",
    "Observational Study",
    "Comparative Study",
    "Evaluation Study",
}

HEALTHCARE_PRACTICE_PATTERN = re.compile(
    r"\b("
    r"patient[s]?|"
    r"hospital|"
    r"outpatient|"
    r"clinic|"
    r"rehabilitation|"
    r"physical therapy|"
    r"surgery|"
    r"surgical|"
    r"arthroscopic|"
    r"postoperative|"
    r"conservative treatment|"
    r"operative treatment|"
    r"shoulder replacement|"
    r"rotator cuff repair|"
    r"shoulder instability|"
    r"adhesive capsulitis|"
    r"frozen shoulder|"
    r"shoulder pain"
    r")\b",
    re.IGNORECASE,
)

STRONG_SHOULDER_TERMS = {
    "rotator cuff",
    "supraspinatus",
    "glenohumeral",
    "arthroplasty",
    "reverse shoulder",
    "shoulder instability",
    "labrum",
    "labral",
    "adhesive capsulitis",
    "frozen shoulder",
    "acromioclavicular",
    "shoulder",
}

NON_SHOULDER_JOINT_PATTERN = re.compile(
    r"\b("
    r"hip|"
    r"knee|"
    r"ankle|"
    r"patella|"
    r"femoral head|"
    r"acetabular|"
    r"tibiofemoral|"
    r"hip joint|"
    r"knee joint"
    r")\b",
    re.IGNORECASE,
)

SHOULDER_TITLE_PATTERN = re.compile(
    r"\b("
    r"shoulder|"
    r"glenohumeral|"
    r"rotator cuff|"
    r"supraspinatus|"
    r"infraspinatus|"
    r"subscapularis|"
    r"shoulder arthroplasty|"
    r"reverse shoulder|"
    r"shoulder instability|"
    r"glenoid|"
    r"adhesive capsulitis|"
    r"frozen shoulder|"
    r"acromioclavicular|"
    r"scapular|"
    r"shoulder labrum|"
    r"glenoid labrum|"
    r"labrum|"
    r"labral"
    r")\b",
    re.IGNORECASE,
)


class PubMedClient:
    def __init__(self, api_key: str = "", email: str = "", tool: str = "shoulder-digest"):
        self.api_key = api_key
        self.email = email
        self.tool = tool

    def search_recent(self, run_date: str, retmax: int = 80, lookback_days: int = 1) -> list[str]:
        mindate, maxdate = pubmed_date_range(run_date, lookback_days)
        params = {
            "db": "pubmed",
            "term": build_pubmed_search_query(),
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


def build_pubmed_search_query() -> str:
    return SHOULDER_CLINICAL_QUERY


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
        if article_type in LOW_EVIDENCE_ARTICLE_TYPES:
            score -= 8
        for key, weight in ARTICLE_TYPE_WEIGHTS.items():
            if key.lower() == article_type.lower():
                score += weight
                if not paper.evidence_type and weight > 0:
                    paper.evidence_type = key
    for phrase, weight in CLINICAL_TEXT_WEIGHTS.items():
        if phrase in haystack:
            score += weight
    for phrase, penalty in NON_CLINICAL_TEXT_PENALTIES.items():
        if phrase in haystack:
            score -= penalty
    if re.search(r"\b(randomi[sz]ed|trial|cohort|registry|meta-analysis|systematic review)\b", haystack):
        score += 3
    if re.search(r"\b(patient[s]?|rehabilitation|outcomes?|operative|arthroscopic)\b", haystack):
        score += 2
    if len(paper.abstract) >= 500:
        score += 1
    paper.topics = topics
    paper.relevance_score = score
    if not paper.evidence_type:
        paper.evidence_type = paper.article_types[0] if paper.article_types else "Article"
    return paper


LOOKBACK_MILESTONES = (365, 730, 1825)


def lookback_search_steps(lookback_days: int, max_lookback_days: int) -> list[int]:
    maximum = max(1, max_lookback_days)
    initial = max(1, min(lookback_days, maximum))
    candidates = [initial, max(initial * 3, 90)]
    for milestone in LOOKBACK_MILESTONES:
        if milestone <= maximum:
            candidates.append(milestone)
    candidates.append(maximum)
    steps: list[int] = []
    for candidate in candidates:
        value = min(candidate, maximum)
        if value not in steps:
            steps.append(value)
    return steps


def search_retmax_for_lookback(lookback_days: int) -> int:
    return min(200, max(80, lookback_days * 2))


def search_top_papers(
    client: PubMedClient,
    run_date: str,
    seen_pmids: set[str],
    *,
    limit: int = 1,
    lookback_days: int = 90,
    max_lookback_days: int = 1825,
) -> tuple[list[Paper], int, list[str]]:
    last_pmids: list[str] = []
    last_lookback = lookback_days
    for lookback in lookback_search_steps(lookback_days, max_lookback_days):
        last_lookback = lookback
        last_pmids = client.search_recent(
            run_date,
            retmax=search_retmax_for_lookback(lookback),
            lookback_days=lookback,
        )
        papers = client.fetch_details(last_pmids)
        selected = select_top_papers(papers, seen_pmids, limit=limit)
        if selected:
            return selected, lookback, last_pmids
    return [], last_lookback, last_pmids


def select_top_papers(papers: list[Paper], seen_pmids: set[str], limit: int = 1) -> list[Paper]:
    candidates = [
        paper
        for paper in papers
        if paper.pmid not in seen_pmids
        and len(paper.abstract.strip()) >= 80
        and paper.relevance_score > 0
        and is_shoulder_focused(paper)
        and is_clinically_oriented(paper)
    ]
    return sorted(candidates, key=lambda paper: (paper.relevance_score, paper.publication_date, paper.pmid), reverse=True)[
        :limit
    ]


def is_clinically_oriented(paper: Paper) -> bool:
    if any(article_type in LOW_EVIDENCE_ARTICLE_TYPES for article_type in paper.article_types):
        return False
    haystack = f"{paper.title}\n{paper.abstract}".lower()
    has_strong_type = any(article_type in STRONG_CLINICAL_ARTICLE_TYPES for article_type in paper.article_types)
    if any(term in haystack for term in HARD_NON_CLINICAL_TEXT_TERMS):
        return False
    if not has_strong_type and any(term in haystack for term in NON_CLINICAL_TEXT_PENALTIES):
        return False
    if not has_strong_type and not HEALTHCARE_PRACTICE_PATTERN.search(haystack):
        return False

    if has_strong_type:
        return True
    if any(article_type.lower() == "case reports" for article_type in paper.article_types):
        return paper.relevance_score >= 8
    return bool(
        re.search(
            r"\b(patient[s]?|rehabilitation|physical therapy|outcomes?|randomi[sz]ed|prospective|retrospective|operative|arthroscopic|postoperative)\b",
            haystack,
        )
    )


def is_shoulder_focused(paper: Paper) -> bool:
    title = paper.title.lower()

    if NON_SHOULDER_JOINT_PATTERN.search(title) and not re.search(r"\bshoulder\b", title):
        return False

    return bool(SHOULDER_TITLE_PATTERN.search(title))
