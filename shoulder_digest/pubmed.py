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
    'scapular[Title/Abstract] OR scapulothoracic[Title/Abstract] OR '
    'acromioclavicular[Title/Abstract] OR '
    '"shoulder rehabilitation"[Title/Abstract] OR '
    'physiotherapy[Title/Abstract] OR "physical therapy"[Title/Abstract] OR '
    '"range of motion"[Title/Abstract] OR kinematics[Title/Abstract] OR '
    'biomechanics[Title/Abstract] OR anatomy[Title/Abstract])'
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

OCCUPATIONAL_EXCLUDE_FILTER = (
    "NOT ("
    "occupational[Title/Abstract] OR "
    "ergonomics[Title/Abstract] OR "
    "workplace[Title/Abstract] OR "
    '"industrial workers"[Title/Abstract] OR '
    "exoskeleton[Title/Abstract] OR "
    "chiropractor[Title/Abstract]"
    ")"
)

HUMAN_FILTER = (
    "(humans[MeSH Terms] NOT (animals[MeSH Terms] NOT humans[MeSH Terms]))"
)

SHOULDER_CONTENT_QUERY = f"({SHOULDER_QUERY}) AND {HUMAN_FILTER} AND {NON_SHOULDER_JOINT_FILTER}"

TOPIC_WEIGHTS = {
    "rotator cuff": 5,
    "supraspinatus": 3,
    "glenohumeral": 4,
    "arthroplasty": 1,
    "reverse shoulder": 1,
    "shoulder instability": 4,
    "labrum": 3,
    "labral": 3,
    "adhesive capsulitis": 5,
    "frozen shoulder": 5,
    "rehabilitation": 6,
    "physiotherapy": 6,
    "physical therapy": 6,
    "exercise therapy": 5,
    "manual therapy": 4,
    "proprioception": 4,
    "motor control": 4,
    "scapular": 4,
    "scapulothoracic": 4,
    "acromioclavicular": 3,
    "shoulder": 2,
    "anatomy": 5,
    "kinematics": 5,
    "biomechanics": 4,
    "range of motion": 5,
    "shoulder function": 5,
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

REHAB_TEXT_WEIGHTS = {
    "rehabilitation protocol": 5,
    "rehabilitation program": 5,
    "rehabilitation programme": 5,
    "physical therapy": 5,
    "physiotherapy": 5,
    "physiotherapist": 4,
    "physical therapist": 4,
    "exercise therapy": 5,
    "therapeutic exercise": 5,
    "home exercise": 4,
    "stretching": 3,
    "strengthening": 3,
    "manual therapy": 4,
    "proprioceptive": 4,
    "proprioception": 4,
    "motor control": 4,
    "scapular dyskinesis": 4,
    "scapular stabilization": 4,
    "scapular stabilisation": 4,
    "range of motion": 4,
    "functional outcome": 4,
    "patient-reported": 3,
    "activities of daily living": 3,
    "conservative treatment": 4,
    "nonoperative": 3,
    "non-operative": 3,
}

SURGICAL_TEXT_PENALTIES = {
    "reverse total shoulder arthroplasty": 4,
    "total shoulder arthroplasty": 4,
    "shoulder arthroplasty": 3,
    "shoulder replacement": 3,
    "hemiarthroplasty": 3,
    "reverse shoulder": 2,
    "postoperative rehabilitation": -2,
}

FOUNDATIONAL_TEXT_WEIGHTS = {
    "anatomy": 4,
    "anatomic": 4,
    "anatomical": 4,
    "kinesiology": 4,
    "kinematics": 4,
    "biomechanics": 3,
    "range of motion": 3,
    "shoulder function": 4,
    "scapulothoracic": 3,
    "muscle activation": 3,
    "glenohumeral joint": 3,
    "shoulder mechanics": 4,
    "muscular balance": 3,
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
        "chiropractor",
    }
)

FOUNDATIONAL_HARD_EXCLUDE_TERMS = frozenset(
    {
        "in vitro",
        "animal model",
        "mouse model",
        "rat model",
        "finite element analysis",
        "exoskeleton",
        "drilling performance",
        "chiropractor",
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

REHAB_PRACTICE_PATTERN = re.compile(
    r"\b("
    r"rehabilitation|"
    r"physiotherapy|"
    r"physical therapy|"
    r"physical therapist|"
    r"physiotherapist|"
    r"exercise therapy|"
    r"therapeutic exercise|"
    r"home exercise|"
    r"range of motion|"
    r"stretching|"
    r"strengthening|"
    r"manual therapy|"
    r"proprioception|"
    r"proprioceptive|"
    r"motor control|"
    r"scapular dyskinesis|"
    r"scapular stabilization|"
    r"scapular stabilisation|"
    r"functional outcome|"
    r"patient-reported|"
    r"activities of daily living|"
    r"conservative treatment|"
    r"nonoperative|"
    r"non-operative|"
    r"shoulder pain|"
    r"adhesive capsulitis|"
    r"frozen shoulder|"
    r"rotator cuff|"
    r"shoulder instability"
    r")\b",
    re.IGNORECASE,
)

ARTHROPLASTY_PATTERN = re.compile(
    r"\b("
    r"reverse total shoulder arthroplasty|"
    r"total shoulder arthroplasty|"
    r"shoulder arthroplasty|"
    r"shoulder replacement|"
    r"hemiarthroplasty|"
    r"reverse shoulder arthroplasty|"
    r"\brtsa\b|"
    r"\btsa\b"
    r")\b",
    re.IGNORECASE,
)

ARTHROPLASTY_MAX_PER_MONTH = 1

FOUNDATIONAL_SHOULDER_PATTERN = re.compile(
    r"\b("
    r"anatomy|"
    r"anatomic|"
    r"anatomical|"
    r"kinesiology|"
    r"kinematics|"
    r"biomechanics|"
    r"range of motion|"
    r"muscle strength|"
    r"shoulder function|"
    r"scapulothoracic|"
    r"shoulder mechanics|"
    r"shoulder movement|"
    r"muscle activation|"
    r"glenohumeral joint|"
    r"morphology|"
    r"muscular balance|"
    r"structural"
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

    def search_recent(
        self,
        run_date: str,
        retmax: int = 80,
        lookback_days: int = 1,
        retstart: int = 0,
    ) -> list[str]:
        mindate, maxdate = pubmed_date_range(run_date, lookback_days)
        params = {
            "db": "pubmed",
            "term": build_pubmed_search_query(),
            "retmode": "json",
            "retmax": str(retmax),
            "retstart": str(max(0, retstart)),
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
    return SHOULDER_CONTENT_QUERY


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
    for phrase, weight in REHAB_TEXT_WEIGHTS.items():
        if phrase in haystack:
            score += weight
    for phrase, penalty in SURGICAL_TEXT_PENALTIES.items():
        if phrase in haystack:
            score -= penalty
    if is_surgery_only_arthroplasty(paper):
        score -= 6
    for phrase, weight in FOUNDATIONAL_TEXT_WEIGHTS.items():
        if phrase in haystack:
            score += weight
    for phrase, penalty in NON_CLINICAL_TEXT_PENALTIES.items():
        if phrase in haystack:
            score -= penalty
    if re.search(r"\b(randomi[sz]ed|trial|cohort|registry|meta-analysis|systematic review)\b", haystack):
        score += 3
    if REHAB_PRACTICE_PATTERN.search(haystack):
        score += 4
    elif re.search(r"\b(patient[s]?|rehabilitation|outcomes?)\b", haystack):
        score += 1
    if len(paper.abstract) >= 500:
        score += 1
    paper.topics = topics
    paper.relevance_score = score
    if not paper.evidence_type:
        paper.evidence_type = paper.article_types[0] if paper.article_types else "Article"
    return paper


SEARCH_PAGE_SIZE = 200
SEARCH_MAX_PAGES = 10

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
    return min(SEARCH_PAGE_SIZE, max(80, lookback_days * 2))


def search_top_papers(
    client: PubMedClient,
    run_date: str,
    seen_pmids: set[str],
    *,
    limit: int = 1,
    lookback_days: int = 90,
    max_lookback_days: int = 1825,
    arthroplasty_deliveries_this_month: int = 0,
    max_arthroplasty_per_month: int = ARTHROPLASTY_MAX_PER_MONTH,
) -> tuple[list[Paper], int, list[str]]:
    last_pmids: list[str] = []
    last_lookback = lookback_days
    arthroplasty_allowed = arthroplasty_deliveries_this_month < max_arthroplasty_per_month
    for lookback in lookback_search_steps(lookback_days, max_lookback_days):
        last_lookback = lookback
        page_size = search_retmax_for_lookback(lookback)
        for page in range(SEARCH_MAX_PAGES):
            retstart = page * page_size
            last_pmids = client.search_recent(
                run_date,
                retmax=page_size,
                lookback_days=lookback,
                retstart=retstart,
            )
            if not last_pmids:
                break
            papers = client.fetch_details(last_pmids)
            selected = select_top_papers(
                papers,
                seen_pmids,
                limit=limit,
                arthroplasty_allowed=arthroplasty_allowed,
            )
            if selected:
                return selected, lookback, last_pmids
    return [], last_lookback, last_pmids


def select_top_papers(
    papers: list[Paper],
    seen_pmids: set[str],
    limit: int = 1,
    *,
    arthroplasty_allowed: bool = True,
) -> list[Paper]:
    def base_filters(paper: Paper) -> bool:
        if not arthroplasty_allowed and is_arthroplasty_paper(paper):
            return False
        return (
            paper.pmid not in seen_pmids
            and len(paper.abstract.strip()) >= 80
            and paper.relevance_score > 0
            and is_shoulder_focused(paper)
        )

    strict = [paper for paper in papers if base_filters(paper) and is_digest_worthy(paper)]
    if strict:
        return _top_ranked(strict, limit)

    relaxed = [paper for paper in papers if base_filters(paper) and is_digest_worthy_fallback(paper)]
    return _top_ranked(relaxed, limit)


def _top_ranked(papers: list[Paper], limit: int) -> list[Paper]:
    return sorted(papers, key=lambda paper: (paper.relevance_score, paper.publication_date, paper.pmid), reverse=True)[
        :limit
    ]


def is_digest_worthy(paper: Paper) -> bool:
    return is_clinically_oriented(paper) or is_foundational_shoulder_content(paper)


def is_digest_worthy_fallback(paper: Paper) -> bool:
    return is_clinically_relevant_fallback(paper) or is_foundational_shoulder_content(paper)


def is_foundational_shoulder_content(paper: Paper) -> bool:
    if any(article_type in LOW_EVIDENCE_ARTICLE_TYPES for article_type in paper.article_types):
        return False
    if not is_shoulder_focused(paper):
        return False
    haystack = f"{paper.title}\n{paper.abstract}".lower()
    if any(term in haystack for term in FOUNDATIONAL_HARD_EXCLUDE_TERMS):
        return False
    return bool(FOUNDATIONAL_SHOULDER_PATTERN.search(haystack))


def has_rehab_focus(haystack: str) -> bool:
    return bool(REHAB_PRACTICE_PATTERN.search(haystack))


def is_surgery_only_arthroplasty(paper: Paper) -> bool:
    haystack = f"{paper.title}\n{paper.abstract}".lower()
    return bool(ARTHROPLASTY_PATTERN.search(haystack)) and not has_rehab_focus(haystack)


def is_arthroplasty_paper(paper: Paper) -> bool:
    haystack = f"{paper.title}\n{paper.abstract}".lower()
    return bool(ARTHROPLASTY_PATTERN.search(haystack))


def is_arthroplasty_text(text: str) -> bool:
    return bool(ARTHROPLASTY_PATTERN.search(text.lower()))


def is_clinically_relevant_fallback(paper: Paper) -> bool:
    if any(article_type in LOW_EVIDENCE_ARTICLE_TYPES for article_type in paper.article_types):
        return False
    haystack = f"{paper.title}\n{paper.abstract}".lower()
    if any(term in haystack for term in HARD_NON_CLINICAL_TEXT_TERMS):
        return False
    if any(term in haystack for term in ("biomechanical analysis", "kinematic assessment", "chiropractor")):
        return False
    if is_surgery_only_arthroplasty(paper):
        return False
    return has_rehab_focus(haystack)


def is_clinically_oriented(paper: Paper) -> bool:
    if any(article_type in LOW_EVIDENCE_ARTICLE_TYPES for article_type in paper.article_types):
        return False
    haystack = f"{paper.title}\n{paper.abstract}".lower()
    if any(term in haystack for term in HARD_NON_CLINICAL_TEXT_TERMS):
        return False
    if is_surgery_only_arthroplasty(paper):
        return False
    if has_rehab_focus(haystack):
        return True
    if is_foundational_shoulder_content(paper):
        return True

    has_strong_type = any(article_type in STRONG_CLINICAL_ARTICLE_TYPES for article_type in paper.article_types)
    if not has_strong_type and any(term in haystack for term in NON_CLINICAL_TEXT_PENALTIES):
        return False
    if has_strong_type and is_shoulder_focused(paper):
        return True
    if any(article_type.lower() == "case reports" for article_type in paper.article_types):
        return paper.relevance_score >= 8 and has_rehab_focus(haystack)
    return bool(
        re.search(
            r"\b(rehabilitation|physical therapy|physiotherapy|range of motion|exercise|shoulder pain)\b",
            haystack,
        )
    )


def is_shoulder_focused(paper: Paper) -> bool:
    title = paper.title.lower()

    if NON_SHOULDER_JOINT_PATTERN.search(title) and not re.search(r"\bshoulder\b", title):
        return False

    return bool(SHOULDER_TITLE_PATTERN.search(title))
