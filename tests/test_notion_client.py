import unittest
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from shoulder_digest.notion_client import EXPECTED_PROPERTIES, NotionClient


class FakeNotionClient(NotionClient):
    def __init__(self, properties):
        super().__init__("token", "database")
        self.properties = properties

    def fetch_database(self):
        return {"properties": self.properties}


class NotionClientTests(unittest.TestCase):
    def test_validate_database_accepts_expected_schema(self):
        properties = {name: {"type": type_name} for name, type_name in EXPECTED_PROPERTIES.items()}
        result = FakeNotionClient(properties).validate_database()
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["mismatched"], [])

    def test_validate_database_reports_missing_and_mismatch(self):
        properties = {name: {"type": type_name} for name, type_name in EXPECTED_PROPERTIES.items()}
        properties.pop("Topics")
        properties["Status"] = {"type": "select"}
        result = FakeNotionClient(properties).validate_database()
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"], ["Topics"])
        self.assertEqual(result["mismatched"], [{"property": "Status", "expected": "rich_text", "actual": "select"}])

    def test_create_page_and_mark_delivered_hit_expected_notion_endpoints(self):
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self._capture()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"page_1"}')

            def do_PATCH(self):
                self._capture()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"page_1"}')

            def _capture(self):
                length = int(self.headers.get("Content-Length", "0"))
                captured.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "notion_version": self.headers.get("Notion-Version"),
                        "body": json.loads(self.rfile.read(length).decode("utf-8")),
                    }
                )

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = NotionClient(
                "token",
                "database_1",
                notion_version="2022-06-28",
                api_base_url=f"http://127.0.0.1:{server.server_address[1]}",
            )
            create = client.create_paper_page(
                "2026-06-09",
                {
                    "pmid": "123",
                    "title": "Rotator cuff trial",
                    "journal": "J Shoulder",
                    "publication_date": "2026-06-08",
                    "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
                    "topics": ["rotator cuff"],
                    "evidence_type": "RCT",
                    "relevance_score": 10,
                    "japanese_summary": "要約",
                    "clinical_takeaway": "臨床ポイント",
                    "abstract": "Abstract text",
                },
                "全体要約",
                "画像プロンプト",
                "https://example.com/image.png",
            )
            delivered = client.mark_delivered("page_1")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(create["id"], "page_1")
        self.assertEqual(delivered["id"], "page_1")
        self.assertEqual(captured[0]["method"], "POST")
        self.assertEqual(captured[0]["path"], "/v1/pages")
        self.assertEqual(captured[0]["authorization"], "Bearer token")
        self.assertEqual(captured[0]["notion_version"], "2022-06-28")
        self.assertEqual(captured[0]["body"]["parent"], {"database_id": "database_1"})
        self.assertEqual(captured[0]["body"]["properties"]["PMID"]["rich_text"][0]["text"]["content"], "123")
        self.assertEqual(captured[1]["method"], "PATCH")
        self.assertEqual(captured[1]["path"], "/v1/pages/page_1")
        self.assertTrue(captured[1]["body"]["properties"]["LINE Delivered"]["checkbox"])
        self.assertEqual(
            captured[1]["body"]["properties"]["Status"]["rich_text"][0]["text"]["content"],
            "delivered",
        )


if __name__ == "__main__":
    unittest.main()
