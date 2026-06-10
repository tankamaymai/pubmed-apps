import unittest

from shoulder_digest.ai_pipeline import parse_digest_json


class AiPipelineTests(unittest.TestCase):
    def test_parse_digest_json_accepts_fenced_json(self):
        parsed = parse_digest_json(
            """```json
{"digest_summary":"summary","image_prompt":"prompt","papers":[]}
```"""
        )
        self.assertEqual(parsed["digest_summary"], "summary")


if __name__ == "__main__":
    unittest.main()

