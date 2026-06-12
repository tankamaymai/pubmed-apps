import unittest
from pathlib import Path

from shoulder_digest.codex_client import (
    CodexAppServerClient,
    _dedupe_text,
    _extract_agent_text,
    _extract_image_saved_path,
    _find_thread_id,
    _server_request_response,
)


class CodexClientTests(unittest.TestCase):
    def test_find_thread_id(self):
        self.assertEqual(_find_thread_id({"thread": {"id": "thr_1"}}), "thr_1")
        self.assertEqual(_find_thread_id({"threadId": "thr_2"}), "thr_2")

    def test_dedupe_text(self):
        self.assertEqual(_dedupe_text("abcabc"), "abc")
        self.assertEqual(_dedupe_text("abc"), "abc")

    def test_turn_start_params_use_current_schema_names(self):
        client = CodexAppServerClient(model="gpt-test", cwd=Path("C:/work"))
        params = client._turn_start_params("thread_1", "hello")
        self.assertEqual(params["threadId"], "thread_1")
        self.assertEqual(params["input"], [{"type": "text", "text": "hello"}])
        self.assertEqual(params["sandboxPolicy"], {"type": "readOnly", "networkAccess": False})
        self.assertNotIn("sandbox", params)
        self.assertEqual(params["model"], "gpt-test")

    def test_turn_start_params_allow_network_for_image_generation(self):
        client = CodexAppServerClient(cwd=Path("C:/work"))
        params = client._turn_start_params("thread_1", "draw", allow_network=True)
        self.assertEqual(params["sandboxPolicy"], {"type": "readOnly", "networkAccess": True})

    def test_thread_start_params_are_read_only_and_ephemeral(self):
        client = CodexAppServerClient(cwd=Path("C:/work"))
        params = client._thread_start_params()
        self.assertEqual(params["approvalPolicy"], "on-request")
        self.assertEqual(params["sandbox"], "read-only")
        self.assertTrue(params["ephemeral"])
        self.assertIn("Do not inspect local files", params["developerInstructions"])

    def test_server_request_denials_match_schema_variants(self):
        self.assertEqual(
            _server_request_response("item/commandExecution/requestApproval"),
            {"decision": "decline"},
        )
        self.assertEqual(_server_request_response("execCommandApproval"), {"decision": "denied"})
        self.assertEqual(_server_request_response("mcpServer/elicitation/request")["action"], "decline")
        self.assertEqual(_server_request_response("item/tool/requestUserInput"), {"answers": {}})
        self.assertEqual(
            _server_request_response("item/permissions/requestApproval", allow_network=True)["permissions"]["network"],
            {"enabled": True},
        )
        self.assertIsNone(_server_request_response("account/chatgptAuthTokens/refresh"))

    def test_extract_image_saved_path(self):
        payload = {
            "item": {
                "type": "imageGeneration",
                "savedPath": "C:/Users/test/.codex/generated_images/sample.png",
                "status": "completed",
            }
        }
        self.assertEqual(
            _extract_image_saved_path(payload),
            "C:/Users/test/.codex/generated_images/sample.png",
        )
        self.assertEqual(_extract_image_saved_path({"item": {"type": "agentMessage", "text": "x"}}), "")

    def test_extract_agent_text_ignores_user_messages(self):
        user = {"item": {"type": "userMessage", "content": [{"type": "text", "text": "prompt"}]}}
        agent = {"item": {"type": "agentMessage", "text": "final", "phase": "final_answer"}}
        self.assertEqual(_extract_agent_text(user), "")
        self.assertEqual(_extract_agent_text(agent), "final")


if __name__ == "__main__":
    unittest.main()
