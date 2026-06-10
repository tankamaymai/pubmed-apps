import unittest

from shoulder_digest.models import Paper
from shoulder_digest.pubmed import is_shoulder_focused, parse_pubmed_xml, pubmed_date_range, select_top_papers


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


if __name__ == "__main__":
    unittest.main()
