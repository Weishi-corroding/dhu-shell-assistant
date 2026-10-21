"""Run after starting the committed local Postman simulation on port 4900.

From lab7: python -m tests.postman_smoke
Does not call a real model or execute any generated shell command.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from lab_shell.client import AssistantError, ChatClient, Settings


class SimulationTests(unittest.TestCase):
    base = os.getenv("LAB_SHELL_SIM_URL", "http://127.0.0.1:4900")

    def test_application_cli_end_to_end(self):
        result = subprocess.run(
            [sys.executable, "-m", "lab_shell", "shell", "--online", "--no-history", "--json", "查看磁盘使用情况"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1", "SHELL_AI_BASE_URL": self.base + "/llm", "SHELL_AI_MODEL": "fixture-model", "SHELL_AI_API_KEY": "", "SHELL_AI_TIMEOUT": "2"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        answer = json.loads(result.stdout)
        self.assertEqual(answer["source"], "online")
        self.assertEqual(answer["command"], "df -h")
        self.assertTrue(answer["safety"]["executable"])

    def test_failure_conditions(self):
        for route, expected in (("limited", "429"), ("unavailable", "500"), ("slow", "超时")):
            with self.subTest(route=route):
                client = ChatClient(Settings(self.base + "/" + route, "fixture-model", timeout=0.1))
                with self.assertRaisesRegex(AssistantError, expected):
                    client.complete([{"role": "user", "content": "test"}])

    def test_fixture_rejects_invalid_contract(self):
        request = Request(self.base + "/llm/chat/completions", data=b'{}', headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
