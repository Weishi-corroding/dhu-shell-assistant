"""Minimal Chat Completions client using real HTTP and a configurable endpoint."""

import json
import math
import os
import socket
from http.client import HTTPException
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import ALIASES, ConfigError, read_dotenv


class AssistantError(Exception):
    """An error safe to display without including API keys or server payloads."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    api_key: str = field(default="", repr=False)
    timeout: float = 30.0

    @classmethod
    def from_env(cls, env_file=None):
        try:
            dotenv = read_dotenv(env_file)
        except ConfigError as exc:
            raise AssistantError(str(exc)) from exc

        def value(name, default):
            for source in (os.environ, dotenv):
                for key in (name, *ALIASES[name]):
                    if key in source:
                        return source[key]
            return default

        try:
            timeout = float(value("SHELL_AI_TIMEOUT", "30"))
        except ValueError as exc:
            raise AssistantError("SHELL_AI_TIMEOUT 必须为数字。") from exc
        if not math.isfinite(timeout) or not 0.1 <= timeout <= 120:
            raise AssistantError("SHELL_AI_TIMEOUT 必须介于 0.1 和 120 秒之间。")
        return cls(
            value("SHELL_AI_BASE_URL", "https://api.deepseek.com").strip().rstrip("/"),
            value("SHELL_AI_MODEL", "deepseek-flash").strip(),
            value("SHELL_AI_API_KEY", ""), timeout,
        )

    @property
    def local(self):
        try:
            return urlsplit(self.base_url).hostname in {"localhost", "127.0.0.1", "::1"}
        except ValueError:
            return False

    def validate(self):
        try:
            url = urlsplit(self.base_url)
            _ = url.port
        except ValueError as exc:
            raise AssistantError("SHELL_AI_BASE_URL 不是有效 URL。") from exc
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise AssistantError("接口 URL 必须含主机，且不能包含用户名、密码、查询或片段。")
        if url.scheme != "https" and not (url.scheme == "http" and self.local):
            raise AssistantError("远程接口必须使用 HTTPS；HTTP 仅允许本机回环地址。")
        if not self.local and not self.api_key:
            raise AssistantError("在线模式需要 SHELL_AI_API_KEY；也可使用 --offline。")
        if not self.model.strip():
            raise AssistantError("SHELL_AI_MODEL 不能为空。")


class ChatClient:
    def __init__(self, settings: Settings):
        settings.validate()
        self.settings = settings

    def complete(self, messages: list[dict[str, str]]) -> str:
        body = json.dumps({
            "model": self.settings.model, "messages": messages, "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = "Bearer " + self.settings.api_key
        try:
            request = Request(self.settings.base_url + "/chat/completions", data=body, headers=headers, method="POST")
            with build_opener(NoRedirect()).open(request, timeout=self.settings.timeout) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise AssistantError("接口响应超过 1 MiB，已拒绝处理。")
            data = json.loads(raw)
            choice = data["choices"][0]
            if choice.get("finish_reason") not in (None, "stop"):
                raise AssistantError("接口未完整返回回答（可能达到长度限制或拒绝回答），未采用结果。")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty content")
            return content.strip()
        except HTTPError as exc:
            exc.close()
            hints = {401: "密钥无效", 402: "账户余额不足", 403: "权限不足", 429: "请求受限或额度不足"}
            hint = hints.get(exc.code, "服务暂不可用" if exc.code >= 500 else "请求失败")
            raise AssistantError(f"接口 HTTP {exc.code}：{hint}。请检查配置后重试。") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AssistantError("接口请求超时，请稍后重试或使用 --offline。") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise AssistantError("接口请求超时，请稍后重试或使用 --offline。") from exc
            raise AssistantError("无法连接接口，请检查地址、网络和证书。") from exc
        except (OSError, HTTPException) as exc:
            raise AssistantError("无法连接接口，请检查地址、网络和证书。") from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AssistantError("接口响应格式无效，需要 choices[0].message.content 文本。") from exc
