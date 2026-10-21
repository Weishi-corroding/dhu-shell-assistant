import argparse
import getpass
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from . import __version__
from .assistant import Assistant
from .client import AssistantError
from .knowledge import RULES
from .safety import assess
from .storage import History, default_data_dir


def terminal_text(value):
    """Strip terminal escape/control sequences from untrusted generated output."""
    value = str(value)
    value = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", value)
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    return "".join(ch for ch in value if ch in "\n\t" or (ord(ch) >= 32 and not 0x7F <= ord(ch) <= 0x9F))


def say(value="", file=None):
    print(terminal_text(value), file=file or sys.stdout)


def emit(answer, as_json=False, record_id=None):
    risk = assess(answer.command) if answer.command else None
    if as_json:
        print(json.dumps({
            "source": answer.source, "answer": answer.text, "command": answer.command,
            "history_id": record_id,
            "safety": None if risk is None else {"executable": risk.executable, "label": risk.label, "reason": risk.reason},
        }, ensure_ascii=False))
        return
    say(f"[{answer.source}]" + (f" 记录 #{record_id}" if record_id is not None else ""))
    if answer.command:
        say("\n建议命令（尚未执行）：\n  " + answer.command)
    say("\n" + answer.text)
    if risk:
        say(f"\n执行检查：{risk.label}。{risk.reason}")


def execute(command):
    risk = assess(command)
    if not risk.executable:
        raise AssistantError("拒绝执行：" + risk.reason)
    if not sys.platform.startswith("linux"):
        raise AssistantError("执行功能仅支持 Linux。当前平台可生成和解释命令，请在 Linux 虚拟机内执行。")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise AssistantError("执行需要交互终端，不能通过管道自动确认。")
    # Resolve a trusted system executable, ignoring aliases and the caller's PATH.
    executable = shutil.which(risk.argv[0], path="/usr/bin:/bin:/usr/sbin:/sbin")
    if not executable:
        raise AssistantError(f"系统未安装 {risk.argv[0]}。请先安装对应的 Linux 工具。")
    say("即将执行：" + command)
    try:
        confirmation = input("输入 EXECUTE 确认，其他输入取消：")
    except EOFError:
        confirmation = ""
    if confirmation != "EXECUTE":
        say("已取消。")
        return 0
    try:
        return subprocess.run([executable, *risk.argv[1:]], shell=False, stdin=subprocess.DEVNULL, timeout=30, check=False).returncode
    except subprocess.TimeoutExpired as exc:
        raise AssistantError("命令超过 30 秒，已停止直接子进程。") from exc


def parser():
    common = argparse.ArgumentParser(add_help=False)
    backend = common.add_mutually_exclusive_group()
    backend.add_argument("--offline", action="store_true", help="只使用内置知识库，不访问网络")
    backend.add_argument("--online", action="store_true", help="强制使用配置的大模型接口")
    common.add_argument("--context", action="store_true", help="在线请求附带当前路径及最多30个文件名（不读文件内容）")
    common.add_argument("--no-history", action="store_true", help="不保存本次问答")
    common.add_argument("--data-dir", type=Path, default=default_data_dir(), help="历史数据库目录")
    common.add_argument("--json", action="store_true", help="输出 JSON")
    root = argparse.ArgumentParser(prog="lab-shell", description="DHU-CS Linux 终端智能助手；默认仅预览命令。")
    root.add_argument("--version", action="version", version=__version__)
    sub = root.add_subparsers(dest="action", required=True)
    for name, help_text in (("ask", "询问 Linux 问题"), ("shell", "将自然语言转为命令"), ("explain", "解释一条命令")):
        cmd = sub.add_parser(name, parents=[common], help=help_text)
        cmd.add_argument("prompt", nargs="+", help="问题或命令，请用引号包裹")
        if name == "shell":
            cmd.add_argument("--execute", action="store_true", help="仅对白名单命令提示确认后执行（仅 Linux）")
    sub.add_parser("chat", parents=[common], help="启动交互会话")
    hist = sub.add_parser("history", help="查看、搜索和清空本地历史")
    hist.add_argument("--data-dir", type=Path, default=default_data_dir())
    hist.add_argument("--search", default="")
    hist.add_argument("--favorites", action="store_true")
    hist.add_argument("--limit", type=int, default=20)
    hist.add_argument("--json", action="store_true")
    hist.add_argument("--clear", action="store_true")
    hist.add_argument("--confirm", choices=["CLEAR"], help="清空需同时传入 --confirm CLEAR")
    fav = sub.add_parser("favorite", help="按历史 ID 收藏命令/问答")
    fav.add_argument("id", type=int)
    fav.add_argument("--remove", action="store_true")
    fav.add_argument("--data-dir", type=Path, default=default_data_dir())
    sub.add_parser("examples", help="列出离线知识库支持的完整句式")
    return root


def show_history(rows, as_json=False):
    if as_json:
        print(json.dumps(rows, ensure_ascii=False))
    elif not rows:
        say("暂无记录。")
    else:
        for row in rows:
            say(f"#{row['id']} {'*' if row['favorite'] else '-'} {row['created_at']} [{row['source']}/{row['mode']}] {row['prompt']}")
            say("  " + (row["command"] or row["answer"]))


def chat(assistant, history, args):
    if args.json:
        raise AssistantError("chat 为交互界面；JSON 输出请使用 ask、shell 或 explain。")
    conversation = []
    say(f"DHU-CS Shell Assistant {__version__} | {'online' if assistant.online else 'offline'}")
    if assistant.online:
        say("当前模型：" + assistant.settings.model)
    say("/shell 需求  /explain 命令  /history  /clear  /help  /exit")
    say("生成命令仅预览；/clear 清除本轮对话上下文，历史记录另行管理。")
    while True:
        try:
            prompt = input(terminal_text(f"{getpass.getuser()}@lab-shell> ")).strip()
        except (EOFError, KeyboardInterrupt):
            say("\n会话已结束。")
            return 0
        if not prompt:
            continue
        if prompt in {"/exit", "/quit"}:
            return 0
        if prompt == "/clear":
            conversation.clear()
            say("本轮对话上下文已清除。")
            continue
        if prompt == "/help":
            say("普通文字：问答；/shell 需求：生成命令；/explain 命令：解释命令。")
            say("/history：最近历史；/clear：清空本轮上下文；/exit：退出。")
            continue
        if prompt == "/history":
            show_history(history.list() if history else [])
            continue
        mode = "ask"
        if prompt.startswith("/"):
            verb, _, rest = prompt.partition(" ")
            if verb not in {"/shell", "/explain"}:
                say("未知会话命令，请输入 /help。")
                continue
            mode, prompt = verb[1:], rest.strip()
        try:
            answer = assistant.answer(prompt, mode, conversation)
            record_id = history.add(mode, prompt, answer) if history else None
            emit(answer, record_id=record_id)
            if mode == "ask":
                conversation.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": answer.text}])
                conversation[:] = conversation[-12:]
        except AssistantError as exc:
            say("错误：" + str(exc), file=sys.stderr)


def main(argv=None):
    if sys.platform == "win32":
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    history = None
    try:
        if args.action == "examples":
            say("离线模式支持以下完整句式，可替换示例中的数字和双引号内容：")
            for rule in RULES:
                say("  " + rule.example)
            return 0
        if args.action in {"history", "favorite"}:
            history = History(args.data_dir)
            if args.action == "favorite":
                if not history.favorite(args.id, args.remove):
                    raise AssistantError("未找到该历史 ID。")
                say("已取消收藏。" if args.remove else "已收藏。")
            elif args.clear:
                if args.confirm != "CLEAR":
                    raise AssistantError("清空历史需要显式传入 --confirm CLEAR。")
                history.clear()
                say("历史记录已清空。")
            else:
                if not 1 <= args.limit <= 1000:
                    raise AssistantError("--limit 必须介于 1 和 1000。")
                show_history(history.list(args.search, args.limit, args.favorites), args.json)
            return 0
        if getattr(args, "execute", False) and args.json:
            raise AssistantError("--execute 不能与 --json 同时使用。")
        mode = "offline" if args.offline else "online" if args.online else "auto"
        assistant = Assistant(mode, args.context)
        if not args.no_history:
            history = History(args.data_dir)
        if args.action == "chat":
            return chat(assistant, history, args)
        prompt = " ".join(args.prompt)
        answer = assistant.answer(prompt, args.action)
        record_id = history.add(args.action, prompt, answer) if history else None
        emit(answer, args.json, record_id)
        if getattr(args, "execute", False):
            return execute(answer.command)
        return 0
    except (AssistantError, OSError, sqlite3.Error) as exc:
        message = str(exc) if isinstance(exc, AssistantError) else "本地文件、数据库或系统操作失败，请检查路径与权限。"
        if getattr(args, "json", False):
            print(json.dumps({"error": message}, ensure_ascii=False))
        else:
            say("错误：" + message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        say("\n已取消。", file=sys.stderr)
        return 130
    finally:
        if history:
            history.close()
