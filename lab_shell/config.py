"""Read literal .env assignments without executing or interpolating their values."""

import re
import shlex
from pathlib import Path


class ConfigError(ValueError):
    pass


ALIASES = {
    "SHELL_AI_BASE_URL": ("BASEURL", "BASE_URL", "OPENAI_BASE_URL"),
    "SHELL_AI_API_KEY": ("API_KEY", "OPENAI_API_KEY"),
    "SHELL_AI_MODEL": ("MODEL", "MODEL_NAME", "OPENAI_MODEL"),
    "SHELL_AI_TIMEOUT": ("TIMEOUT",),
}


def read_dotenv(path=None):
    if path is None:
        path = Path.cwd() / ".env"
        project = Path(__file__).resolve().parents[1]
        if not path.exists() and (project / "pyproject.toml").is_file():
            path = project / ".env"
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            text = stream.read(65537)
        if len(text) > 65536:
            raise ConfigError(".env 超过 64 KiB，请精简配置。")
    except (OSError, UnicodeError) as exc:
        raise ConfigError("无法读取 .env，请检查 UTF-8 编码和文件权限。") from exc
    result = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line)
        if not match:
            raise ConfigError(f".env 第 {number} 行格式无效，应为 NAME=value。")
        name, value = match.groups()
        lexer = shlex.shlex(value, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        try:
            parts = list(lexer)
        except ValueError as exc:
            raise ConfigError(f".env 第 {number} 行引号不匹配。") from exc
        if len(parts) > 1:
            raise ConfigError(f".env 第 {number} 行的值含空格，请使用引号。")
        result[name] = parts[0] if parts else ""
    return result
