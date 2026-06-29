import unittest

from shoulder_digest.models import Paper
from shoulder_digest.pubmed import (
    build_pubmed_search_query,
    is_arthroplasty_paper,
    is_clinically_oriented,
    is_digest_worthy,
    is_foundational_shoulder_content,
    is_shoulder_focused,
    lookback_search_steps,
    parse_pubmed_xml,
    pubmed_date_range,
    score_paper,
    search_retmax_for_lookback,
    search_top_papers,
    select_top_papers,
)


PUBMED_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>123</PMID>
      <Article>
        <ArticleTitle>Rotator cuff repair after shoulder injury</ArticleTitle>
        <Journal><ISOAbbreviation>J Shoulder Elbow Surg</ISOAbbreviation>
          <JournalIssue><PubDate><Year>2026</Year><Month>Jun</Month><Day>01</Day></PubDate></JournalIssue>
        </Journal>
        <Abstract>
          <AbstractText Label="BACKGROUND">Rotator cuff tears cause shoulder pain.</AbstractText>
          <AbstractText Label="METHODS">A randomized controlled trial evaluated repair and rehabilitation outcomes in patients with shoulder symptoms.</AbstractText>
        </Abstract>
        <PublicationTypeList>
          <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>456</PMID>
      <Article>
        <ArticleTitle>General knee paper</ArticleTitle>
        <Abstract><AbstractText>Knee abstract without relevant terms.</AbstractText></Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


class PubMedTests(unittest.TestCase):
    def test_parse_pubmed_xml_extracts_articles(self):
        papers = parse_pubmed_xml(PUBMED_XML)
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0].pmid, "123")
        self.assertIn("Randomized Controlled Trial", papers[0].article_types)
        self.assertEqual(papers[0].publication_date, "2026-06-01")
        self.assertGreater(papers[0].relevance_score, papers[1].relevance_score)

    def test_select_top_papers_filters_seen_and_abstractless(self):
        papers = parse_pubmed_xml(PUBMED_XML)
        selected = select_top_papers(papers, seen_pmids=set(), limit=3)
        self.assertEqual([paper.pmid for paper in selected], ["123"])
        selected = select_top_papers(papers, seen_pmids={"123"}, limit=3)
        self.assertEqual(selected, [])

    def test_is_shoulder_focused_rejects_broad_non_title_mentions(self):
        broad = Paper(
            pmid="999",
            title="General occupational musculoskeletal injury cohort",
            abstract="Shoulder injuries were included among many injury locations. " * 3,
            topics=["shoulder"],
            relevance_score=2,
        )
        focused = Paper(
            pmid="1000",
            title="Massive rotator cuff tear repair",
            abstract="Shoulder outcomes were evaluated. " * 3,
            topics=["rotator cuff", "shoulder"],
            relevance_score=8,
        )
        self.assertFalse(is_shoulder_focused(broad))
        self.assertTrue(is_shoulder_focused(focused))

    def test_pubmed_date_range_uses_lookback_days(self):
        self.assertEqual(pubmed_date_range("2026-06-09", lookback_days=1), ("2026/06/09", "2026/06/09"))
        self.assertEqual(pubmed_date_range("2026-06-09", lookback_days=3), ("2026/06/07", "2026/06/09"))

    def test_is_clinically_oriented_rejects_surgery_only_arthroplasty(self):
        arthroplasty = Paper(
            pmid="9",
            title="Reverse total shoulder arthroplasty outcomes in patients",
            abstract="Patients underwent reverse total shoulder arthroplasty with implant survivorship analysis. " * 3,
            article_types=["Systematic Review"],
            topics=["reverse shoulder", "arthroplasty"],
        )
        score_paper(arthroplasty)
        self.assertFalse(is_clinically_oriented(arthroplasty))

    def test_rehab_paper_scores_higher_than_surgery_only_arthroplasty(self):
        rehab = Paper(
            pmid="10",
            title="Scapular stabilization exercise program for shoulder pain",
            abstract=(
                "Patients received a rehabilitation protocol with physical therapy, "
                "range of motion exercises, and scapular dyskinesis training. " * 3
            ),
            article_types=["Randomized Controlled Trial"],
        )
        arthroplasty = Paper(
            pmid="11",
            title="Reverse total shoulder arthroplasty survivorship review",
            abstract="Patients underwent reverse total shoulder arthroplasty with implant analysis. " * 3,
            article_types=["Systematic Review"],
        )
        score_paper(rehab)
        score_paper(arthroplasty)
        self.assertGreater(rehab.relevance_score, arthroplasty.relevance_score)
        self.assertTrue(is_clinically_oriented(rehab))
        self.assertFalse(is_clinically_oriented(arthroplasty))

    def test_select_top_papers_respects_monthly_arthroplasty_limit(self):
        rehab = Paper(
            pmid="20",
            title="Shoulder rehabilitation exercise for rotator cuff pain",
            abstract="Patients completed a physical therapy rehabilitation protocol with range of motion training. " * 3,
            article_types=["Randomized Controlled Trial"],
        )
        arthroplasty = Paper(
            pmid="21",
            title="Postoperative rehabilitation after reverse total shoulder arthroplasty",
            abstract=(
                "Patients underwent reverse total shoulder arthroplasty and completed a physical therapy "
                "rehabilitation protocol with range of motion exercises. " * 3
            ),
            article_types=["Systematic Review"],
        )
        score_paper(rehab)
        score_paper(arthroplasty)
        blocked = select_top_papers([arthroplasty, rehab], set(), limit=1, arthroplasty_allowed=False)
        self.assertEqual([paper.pmid for paper in blocked], ["20"])
        self.assertEqual(select_top_papers([arthroplasty], set(), limit=1, arthroplasty_allowed=False), [])
        allowed = select_top_papers([arthroplasty], set(), limit=1, arthroplasty_allowed=True)
        self.assertEqual([paper.pmid for paper in allowed], ["21"])

    def test_is_arthroplasty_paper_detects_rtsa(self):
        paper = Paper(
            pmid="22",
            title="Postoperative rehabilitation after reverse total shoulder arthroplasty",
            abstract="Physical therapy began after RTSA. " * 3,
        )
        self.assertTrue(is_arthroplasty_paper(paper))

    def test_build_pubmed_search_query_includes_rehab_terms(self):
        query = build_pubmed_search_query()
        self.assertIn("physiotherapy[Title/Abstract]", query)
        self.assertIn('"physical therapy"[Title/Abstract]', query)
        self.assertIn("kinematics[Title/Abstract]", query)

    def test_build_pubmed_search_query_includes_foundational_terms(self):
        query = build_pubmed_search_query()
        self.assertIn("humans[MeSH Terms]", query)
        self.assertIn("shoulder[Title/Abstract]", query)
        self.assertIn("humans[MeSH Terms]", query)
        self.assertIn("hip[Title/Abstract]", query)
        self.assertIn("NOT (", query)

    def test_is_foundational_shoulder_content_accepts_anatomy_review(self):
        review = Paper(
            pmid="41655196",
            title="Glenohumeral stability and scapular kinematics: an anatomical review of shoulder function.",
            abstract=(
                "This review summarizes glenohumeral joint anatomy, rotator cuff function, "
                "scapulothoracic kinematics, and shoulder range of motion for clinicians. " * 3
            ),
            article_types=["Review"],
            topics=["shoulder"],
        )
        score_paper(review)
        self.assertTrue(is_foundational_shoulder_content(review))
        self.assertTrue(is_digest_worthy(review))

    def test_is_shoulder_focused_rejects_hip_instability_paper(self):
        hip = Paper(
            pmid="41910967",
            title=(
                "What Are the Biomechanical Features and Metrics for Native Hip Instability? "
                "Consensus Statements From a Scoping Review and an International Multidisciplinary Delphi Study."
            ),
            abstract="Patients with hip instability were evaluated. " * 3,
            topics=["labrum", "instability"],
            relevance_score=10,
        )
        self.assertFalse(is_shoulder_focused(hip))

    def test_is_clinically_oriented_rejects_non_clinical_and_accepts_rct(self):
        rct = Paper(
            pmid="1",
            title="Randomized trial of rotator cuff rehabilitation outcomes in patients",
            abstract="Patients were randomized to two rehabilitation protocols with clinical outcomes. " * 3,
            article_types=["Randomized Controlled Trial"],
            topics=["rotator cuff", "rehabilitation"],
        )
        score_paper(rct)
        self.assertTrue(is_clinically_oriented(rct))

        biomechanics = Paper(
            pmid="2",
            title="Finite element analysis of rotator cuff repair",
            abstract="A cadaveric biomechanical analysis was performed in vitro. " * 3,
            article_types=["Journal Article"],
            topics=["rotator cuff"],
        )
        score_paper(biomechanics)
        self.assertFalse(is_clinically_oriented(biomechanics))

        exoskeleton = Paper(
            pmid="3",
            title="Influence of a passive shoulder exoskeleton on drilling performance in women",
            abstract="Industrial workers performed drilling tasks while wearing an exoskeleton. " * 3,
            article_types=["Journal Article"],
            topics=["shoulder"],
        )
        score_paper(exoskeleton)
        self.assertFalse(is_clinically_oriented(exoskeleton))

    def test_is_clinically_oriented_accepts_systematic_review_with_biomechanical_terms(self):
        review = Paper(
            pmid="39652591",
            title="Thinking outside the shoulder: A systematic review and metanalysis of kinetic chain characteristics in non-athletes with shoulder pain.",
            abstract=(
                "Although biomechanical impairments in components of the kinetic chain have already been reported, "
                "this systematic review synthesized evidence in non-athlete individuals with shoulder pain. " * 3
            ),
            article_types=["Systematic Review", "Meta-Analysis"],
            topics=["shoulder"],
        )
        score_paper(review)
        self.assertTrue(is_clinically_oriented(review))

    def test_lookback_search_steps_expands_when_needed(self):
        self.assertEqual(lookback_search_steps(30, 365), [30, 90, 365])
        self.assertEqual(lookback_search_steps(30, 730), [30, 90, 365, 730])
        self.assertEqual(lookback_search_steps(90, 1825), [90, 270, 365, 730, 1825])
        self.assertEqual(lookback_search_steps(7, 30), [7, 30])

    def test_search_retmax_for_lookback_scales_with_window(self):
        self.assertEqual(search_retmax_for_lookback(30), 80)
        self.assertEqual(search_retmax_for_lookback(120), 200)

    def test_search_top_papers_expands_lookback_until_match(self):
        class ExpandingPubMed:
            def __init__(self):
                self.calls: list[int] = []

            def search_recent(self, run_date, retmax=80, lookback_days=1, retstart=0):
                self.calls.append(lookback_days)
                return ["1"] if lookback_days >= 90 else []

            def fetch_details(self, pmids):
                if not pmids:
                    return []
                return [
                    Paper(
                        pmid="1",
                        title="Rotator cuff repair outcomes in patients",
                        abstract="Patients underwent shoulder surgery with rehabilitation outcomes. " * 4,
                        article_types=["Randomized Controlled Trial"],
                        topics=["rotator cuff", "shoulder"],
                        relevance_score=10,
                    )
                ]

        client = ExpandingPubMed()
        selected, lookback_used, pmids = search_top_papers(
            client,
            "2026-06-09",
            set(),
            limit=1,
            lookback_days=30,
            max_lookback_days=365,
        )
        self.assertEqual([paper.pmid for paper in selected], ["1"])
        self.assertEqual(lookback_used, 90)
        self.assertEqual(client.calls, [30, 90])


if __name__ == "__main__":
    unittest.main()
