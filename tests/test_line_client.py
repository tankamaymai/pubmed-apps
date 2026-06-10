import base64
import hashlib
import hmac
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from shoulder_digest.line_client import LineClient, build_line_messages


class LineClientTests(unittest.TestCase):
    def test_verify_signature(self):
        body = b'{"events":[]}'
        secret = "secret"
        signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        self.assertTrue(LineClient("", secret).verify_signature(body, signature))
        self.assertFalse(LineClient("", secret).verify_signature(body, "bad"))

    def test_build_line_messages_includes_image_and_text(self):
        messages = build_line_messages(
            "2026-06-08",
            "https://example.com/image.png",
            "digest",
            [{"pmid": "123", "title": "Title", "japanese_summary": "Summary", "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/123/"}],
        )
        self.assertEqual(messages[0]["type"], "image")
        self.assertEqual(messages[1]["type"], "text")
        self.assertIn("PMID", messages[1]["text"])

    def test_push_posts_expected_payload_to_line_api(self):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                captured["path"] = self.path
                captured["authorization"] = self.headers.get("Authorization")
                captured["content_type"] = self.headers.get("Content-Type")
                captured["retry_key"] = self.headers.get("X-Line-Retry-Key")
                captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            client = LineClient("token", "secret", api_base_url=base_url)
            result = client.push("C123", [{"type": "text", "text": "hello"}])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(result["status"], "sent")
        self.assertEqual(captured["path"], "/v2/bot/message/push")
        self.assertEqual(captured["authorization"], "Bearer token")
        self.assertEqual(captured["content_type"], "application/json")
        self.assertTrue(captured["retry_key"])
        self.assertEqual(captured["body"], {"to": "C123", "messages": [{"type": "text", "text": "hello"}]})


if __name__ == "__main__":
    unittest.main()
