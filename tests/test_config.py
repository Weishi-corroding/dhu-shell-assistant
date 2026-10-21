import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lab_shell.assistant import Assistant
from lab_shell.client import AssistantError, Settings
from lab_shell.config import ALIASES, ConfigError, read_dotenv
from tests.test_assistant import FixtureHandler
from http.server import ThreadingHTTPServer
import threading


CONFIG_KEYS = {key for name, aliases in ALIASES.items() for key in (name, *aliases)}


class ConfigTests(unittest.TestCase):
    def test_aliases_quotes_bom_comments_and_no_interpolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text('\ufeff# test\nexport BASEURL="https://example.com/v1/" # note\nAPI_KEY=\'literal-$(echo secret)#suffix\'\nMODEL=example-model\nTIMEOUT=2.5\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.from_env(path)
            self.assertEqual(settings.base_url, "https://example.com/v1")
            self.assertEqual(settings.api_key, "literal-$(echo secret)#suffix")
            self.assertEqual(settings.model, "example-model")
            self.assertEqual(settings.timeout, 2.5)
            self.assertNotIn("literal-", repr(settings))

    def test_environment_precedence_and_explicit_empty_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text('SHELL_AI_MODEL=file-model\nMODEL=file-alias\nAPI_KEY=file-key\n', encoding="utf-8")
            with patch.dict(os.environ, {"MODEL": "process-alias", "SHELL_AI_API_KEY": ""}, clear=True):
                settings = Settings.from_env(path)
            self.assertEqual(settings.model, "process-alias")
            self.assertEqual(settings.api_key, "")
            with patch.dict(os.environ, {"SHELL_AI_MODEL": "process-canonical", "MODEL": "process-alias"}, clear=True):
                self.assertEqual(Settings.from_env(path).model, "process-canonical")

    def test_missing_invalid_files_and_secret_free_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            self.assertEqual(read_dotenv(path), {})
            for content in ("secret-test-key-no-assignment", 'API_KEY="secret-test-key', "API_KEY=secret-test-key invalid"):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(AssistantError) as caught:
                    Settings.from_env(path)
                self.assertNotIn("secret-test-key", str(caught.exception))
            path.write_text("#" + "x" * 65537, encoding="utf-8")
            with self.assertRaises(ConfigError):
                read_dotenv(path)

    def test_offline_does_not_read_dotenv(self):
        with patch("lab_shell.client.read_dotenv", side_effect=AssertionError("must not read credentials")):
            self.assertFalse(Assistant("offline").online)

    def test_cli_dotenv_auto_mode_over_real_http(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / ".env"
                path.write_text(f'BASEURL=http://127.0.0.1:{server.server_port}/success\nAPI_KEY=fixture-key\nMODEL=dotenv-model\n', encoding="utf-8")
                root = Path(__file__).resolve().parents[1]
                environment = {key: value for key, value in os.environ.items() if key not in CONFIG_KEYS}
                environment.update({"PYTHONUTF8": "1", "PYTHONPATH": str(root)})
                result = subprocess.run([sys.executable, "-m", "lab_shell", "shell", "--no-history", "--json", "查看磁盘使用情况"], cwd=tmp, env=environment, capture_output=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["source"], "online")
                self.assertEqual(json.loads(result.stdout)["command"], "df -h")
                self.assertEqual(FixtureHandler.requests[-1][2]["model"], "dotenv-model")
                self.assertEqual(FixtureHandler.requests[-1][1]["Authorization"], "Bearer fixture-key")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
