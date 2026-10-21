import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from lab_shell.assistant import Assistant
from lab_shell.cli import execute, main, terminal_text
from lab_shell.client import AssistantError, ChatClient, Settings
from lab_shell.knowledge import RULES, explain, generate
from lab_shell.safety import assess
from lab_shell.storage import History


class KnowledgeTests(unittest.TestCase):
    def test_every_documented_example_matches(self):
        for rule in RULES:
            with self.subTest(example=rule.example):
                self.assertTrue(generate(rule.example).command)

    def test_specific_constraints_not_silently_dropped(self):
        self.assertEqual(generate("查找当前目录下大于100MB的文件").command, "find . -type f -size +100M")
        self.assertEqual(generate("查看内存使用情况并删除所有日志").command, "")
        self.assertEqual(generate("查找大于100MB且7天未修改的文件").command, "")
        self.assertEqual(generate("查看端口99999的进程").command, "")

    def test_arguments_are_quoted(self):
        import shlex
        answer = generate('在 "/tmp/lab data" 中查找文件 "$(touch nope)*.log"')
        self.assertEqual(shlex.split(answer.command), ["find", "/tmp/lab data", "-type", "f", "-name", "$(touch nope)*.log"])
        self.assertFalse(assess(answer.command).executable)
        mkdir = generate('创建目录 "-danger"')
        self.assertEqual(shlex.split(mkdir.command), ["mkdir", "-p", "--", "-danger"])

    def test_unknown_and_explanation(self):
        self.assertIn("暂不支持", generate("请分析任意未知问题").text)
        self.assertIn("-r 递归", explain("rm -rf ./demo").text)
        self.assertIn("组合符", explain("ps aux | grep python").text)
        self.assertIn("引号不匹配", explain("ls '").text)


class SafetyTests(unittest.TestCase):
    def test_read_only_grammars(self):
        for command in ("df -h", "free -h", "ps aux", "ip -brief address show", "ss -ltnp 'sport = :8080'", "find . -type f -name '*.log'", "tail -n 20 -- '/tmp/lab file'", "cat /etc/os-release"):
            with self.subTest(command=command):
                self.assertTrue(assess(command).executable)

    def test_reject_side_effects_and_bypasses(self):
        for command in (
            "rm -rf /", "sudo ls", "ls; id", "ls\nrm -rf /", "echo $(id)",
            "cat /etc/passwd", "date -s tomorrow", "hostname new-host", "ip link delete eth0",
            "find . -type f -delete", "find . -exec sh x", "find . -type f -name x -delete",
            "grep -nF -- test --help -f secret", "tail -n 20 -- x y", "du --files0-from=secret",
            "sh -c ls", "python -c pass", "ls > important", "ls `id`", "ls --color=always",
            "/tmp/ls", "PATH=/tmp ls", "ls 'unterminated", "", "df\x1b[31m",
        ):
            with self.subTest(command=command):
                self.assertFalse(assess(command).executable)

    def test_execute_refuses_noninteractive_and_dangerous(self):
        with self.assertRaisesRegex(AssistantError, "拒绝执行"):
            execute("rm -rf /tmp/anything")
        with patch("lab_shell.cli.sys.platform", "linux"), patch("lab_shell.cli.sys.stdin.isatty", return_value=False):
            with self.assertRaisesRegex(AssistantError, "交互终端"):
                execute("df -h")

    def test_execution_requires_confirmation_and_never_uses_shell(self):
        with patch("lab_shell.cli.sys.platform", "linux"), patch("lab_shell.cli.sys.stdin") as stdin, patch("lab_shell.cli.sys.stdout") as stdout, patch("lab_shell.cli.shutil.which", return_value="/usr/bin/df") as lookup, patch("lab_shell.cli.subprocess.run") as run, patch("builtins.input", side_effect=["no", "EXECUTE"]):
            stdin.isatty.return_value = stdout.isatty.return_value = True
            self.assertEqual(execute("df -h"), 0)
            run.assert_not_called()
            run.return_value.returncode = 7
            self.assertEqual(execute("df -h"), 7)
            lookup.assert_called_with("df", path="/usr/bin:/bin:/usr/sbin:/sbin")
            run.assert_called_once_with(["/usr/bin/df", "-h"], shell=False, stdin=subprocess.DEVNULL, timeout=30, check=False)

    def test_terminal_controls_removed(self):
        self.assertEqual(terminal_text("\x1b[31mred\x1b[0m\x07\r\x9b"), "red")
        self.assertEqual(terminal_text("\x1b]0;title\x07hello"), "hello")


class HistoryTests(unittest.TestCase):
    def test_persistence_search_favorites_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = History(Path(tmp))
            try:
                record = store.add("shell", "查看磁盘使用情况", generate("查看磁盘使用情况"))
                self.assertTrue(store.favorite(record))
                self.assertEqual(store.list(favorites=True)[0]["command"], "df -h")
                self.assertEqual(len(store.list("磁盘")), 1)
                self.assertEqual(store.list("' OR 1=1 --"), [])
                self.assertEqual(store.list("%"), [])
                self.assertFalse(store.favorite(9999))
            finally:
                store.close()
            store = History(Path(tmp))
            try:
                self.assertEqual(len(store.list()), 1)
                store.favorite(record, remove=True)
                self.assertEqual(store.list(favorites=True), [])
                store.clear()
                self.assertEqual(store.list(), [])
            finally:
                store.close()


class FixtureHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.path, dict(self.headers), body))
        route = self.path.split("/")[1]
        if route == "slow":
            time.sleep(0.25)
        if route in {"401", "402", "429", "500"}:
            self.send_response(int(route))
            payload = b"<html>secret-test-key must never be displayed</html>"
        elif route == "redirect":
            self.send_response(307)
            self.send_header("Location", "/success/chat/completions")
            payload = b""
        else:
            self.send_response(200)
            content = '{"command":"df -h","explanation":"查看磁盘空间"}'
            if route == "badcommand":
                content = "```bash\nrm -rf /\n```"
            if route == "badtypes":
                content = '{"command": ["df"], "explanation": 42}'
            if route == "refusal":
                content = '{"command":"","explanation":"请补充目标目录"}'
            if route == "truncated":
                reason = "length"
            else:
                reason = "stop"
            payload = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": reason}]}).encode()
            if route == "badjson":
                payload = b"<html>not JSON</html>"
            if route == "badshape":
                payload = b'{"choices": []}'
            if route == "large":
                payload = b"x" * (1024 * 1024 + 1)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def assistant(self, route="success"):
        with patch.dict(os.environ, {"SHELL_AI_BASE_URL": self.base + "/" + route, "SHELL_AI_API_KEY": "secret-test-key", "SHELL_AI_MODEL": "fixture-model", "SHELL_AI_TIMEOUT": "2"}):
            return Assistant("online")

    def test_full_http_command_request_and_response(self):
        answer = self.assistant().answer("查看磁盘空间", "shell")
        self.assertEqual((answer.command, answer.source), ("df -h", "online"))
        path, headers, body = FixtureHandler.requests[-1]
        self.assertEqual(path, "/success/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer secret-test-key")
        self.assertEqual(body["model"], "fixture-model")
        self.assertFalse(body["stream"])
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "查看磁盘空间"})
        self.assertNotIn(str(Path.cwd()), body["messages"][0]["content"])

    def test_chat_context_is_bounded_and_explicit(self):
        assistant = self.assistant()
        previous = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(20)]
        assistant.answer("继续", "ask", previous)
        messages = FixtureHandler.requests[-1][2]["messages"]
        self.assertEqual(len(messages), 14)
        self.assertEqual(messages[1]["content"], "8")
        assistant.context = True
        assistant.answer("继续", "ask")
        system = FixtureHandler.requests[-1][2]["messages"][0]["content"]
        context = json.loads(system.split("（不包含文件内容）：", 1)[1])
        self.assertEqual(context["cwd"], str(Path.cwd()))

    def test_errors_do_not_expose_body_or_key(self):
        for route in ("401", "402", "429", "500", "badjson", "badshape", "badcommand", "badtypes", "truncated", "large", "redirect"):
            with self.subTest(route=route):
                with self.assertRaises(AssistantError) as caught:
                    self.assistant(route).answer("test", "shell")
                self.assertNotIn("secret-test-key", str(caught.exception))
        self.assertEqual(self.assistant("refusal").answer("test", "shell").command, "")

    def test_payment_required_has_actionable_message(self):
        with self.assertRaisesRegex(AssistantError, "HTTP 402：账户余额不足"):
            self.assistant("402").answer("查看磁盘使用情况", "shell")

    def test_real_timeout(self):
        client = ChatClient(Settings(self.base + "/slow", "fixture", timeout=0.1))
        with self.assertRaisesRegex(AssistantError, "超时"):
            client.complete([{"role": "user", "content": "test"}])

    def test_cli_uses_real_http(self):
        result = subprocess.run(
            [sys.executable, "-m", "lab_shell", "shell", "--online", "--no-history", "--json", "查看磁盘空间"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1", "SHELL_AI_BASE_URL": self.base + "/success", "SHELL_AI_API_KEY": "", "SHELL_AI_MODEL": "fixture-model", "SHELL_AI_TIMEOUT": "2"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["command"], "df -h")


class CLITests(unittest.TestCase):
    def call(self, *args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(list(args))
        return status, output.getvalue(), error.getvalue()

    def test_json_no_history_and_invalid_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = str(Path(tmp) / "unused")
            status, out, _ = self.call("shell", "--offline", "--no-history", "--data-dir", data, "--json", "查看磁盘使用情况")
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(out)["command"], "df -h")
            self.assertFalse(Path(data).exists())
            status, out, _ = self.call("shell", "--offline", "--json", "--execute", "查看磁盘使用情况")
            self.assertEqual(status, 1)
            self.assertIn("error", json.loads(out))

    def test_chat_recovery_and_context_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("builtins.input", side_effect=["/shell 查看磁盘使用情况", "/explain rm -rf ./demo", "/unknown", "/history", "/clear", "/exit"]):
                status, out, _ = self.call("chat", "--offline", "--data-dir", tmp)
            self.assertEqual(status, 0)
            self.assertIn("df -h", out)
            self.assertIn("未知会话命令", out)
            self.assertIn("上下文已清除", out)

    def test_configuration_validation(self):
        for url in ("http://example.com", "file:///etc/passwd", "https://user:password@example.com", "https://example.com?key=secret", "http://[bad"):
            with self.subTest(url=url), self.assertRaises(AssistantError):
                Settings(url, api_key="test").validate()
        for value in ("nan", "inf", "0", "bad", "121"):
            with self.subTest(timeout=value), patch.dict(os.environ, {"SHELL_AI_TIMEOUT": value}), self.assertRaises(AssistantError):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
