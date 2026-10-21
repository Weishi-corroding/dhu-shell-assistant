"""A small, deterministic intent/slot knowledge base, not a local language model."""

import re
import shlex
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Answer:
    text: str
    command: str = ""
    source: str = "offline"


@dataclass(frozen=True)
class Rule:
    pattern: str
    build: Callable[[re.Match], str]
    explanation: str
    example: str


def fixed(pattern: str, command: str, explanation: str, example: str) -> Rule:
    return Rule(pattern, lambda match: command, explanation, example)


RULES = (
    fixed(r"(?:查看|显示)?(?:磁盘|硬盘)(?:空间)?(?:使用情况|使用率|占用|空间)?|disk usage", "df -h", "按易读单位显示各文件系统的容量、已用和可用空间。", "查看磁盘使用情况"),
    fixed(r"(?:查看|显示)?内存(?:使用情况|使用率|占用|信息)?|memory usage", "free -h", "显示物理内存和交换分区；available 比 free 更能反映可用内存。", "查看内存使用情况"),
    fixed(r"(?:查看|显示)?(?:系统)?(?:负载|运行时间)|uptime", "uptime", "显示运行时间及最近 1、5、15 分钟的平均负载。", "查看系统负载"),
    fixed(r"(?:查看|显示)?(?:所有)?进程(?:列表|信息)?|list processes", "ps aux", "以 BSD 格式列出进程，包括用户、PID、CPU 和内存占用。", "查看所有进程"),
    fixed(r"(?:查看|显示)?(?:监听|开放)(?:的)?端口|list ports", "ss -tuln", "显示 TCP/UDP 监听套接字，使用数字地址和端口。", "查看监听端口"),
    fixed(r"(?:查看|显示)?(?:ip|IP|网络接口)(?:地址|信息)?|ip address", "ip -brief address show", "简洁显示网卡状态和 IP 地址。", "查看IP地址"),
    fixed(r"(?:查看|显示)?(?:路由表|默认路由)|show routes", "ip route show", "显示 IPv4 路由表，default 行表示默认路由。", "查看路由表"),
    fixed(r"(?:查看|显示)?当前用户(?:名)?|who am i", "whoami", "输出当前有效用户名，便于保留实验截图中的用户身份。", "查看当前用户名"),
    fixed(r"(?:查看|显示)?(?:系统|内核)版本|kernel version", "uname -a", "显示内核名称、版本和机器架构；发行版版本请查看 /etc/os-release。", "查看内核版本"),
    fixed(r"(?:查看|显示)?(?:发行版|操作系统)信息|os version", "cat /etc/os-release", "读取发行版的名称、版本等信息。", "查看发行版信息"),
    fixed(r"(?:查看|显示)?当前(?:工作)?目录|working directory", "pwd", "显示当前工作目录的绝对路径。", "查看当前目录"),
    fixed(r"(?:列出|查看|显示)(?:当前目录(?:下)?的?)?(?:所有文件|隐藏文件)|list all files", "ls -lah", "以长格式列出文件，包含隐藏文件，大小使用易读单位。", "列出隐藏文件"),
    fixed(r"(?:列出|查看|显示)(?:当前目录(?:下)?的?)?文件(?:列表)?|list files", "ls -lh", "以长格式列出当前目录的非隐藏文件。", "列出文件"),
    fixed(r"(?:查看|显示)?当前目录(?:的)?(?:大小|占用空间)|directory size", "du -sh .", "统计当前目录及子目录的磁盘占用；读取无权限目录时可能报错。", "查看当前目录大小"),
    fixed(r"(?:查看|显示)?(?:当前)?(?:登录用户|在线用户)|logged in users", "who", "显示当前登录会话。", "查看登录用户"),
    fixed(r"(?:查看|显示)?主机名|hostname", "hostname", "显示本机主机名。", "查看主机名"),
    fixed(r"(?:查看|显示)?(?:当前)?(?:日期|时间)|date", "date", "显示系统当前日期、时间和时区。", "查看当前时间"),
    Rule(r"(?:查找|寻找)(?:当前目录下)?(?:所有)?大于\s*(?P<size>[1-9]\d{0,6})\s*(?P<unit>[kKmMgG])(?:[bB])?(?:的)?文件", lambda m: f"find . -type f -size +{m['size']}{m['unit'].upper() if m['unit'].lower() != 'k' else 'k'}", "递归查找大于指定大小的普通文件；find 的 k/M/G 分别按 KiB/MiB/GiB 计。", "查找大于100MB的文件"),
    Rule(r'查找文件\s+"(?P<name>[^"\n]+)"', lambda m: f"find . -type f -name {shlex.quote(m['name'])}", "在当前目录递归按文件名通配符查找；模式由单引号保护，交给 find 匹配。", '查找文件 "*.log"'),
    Rule(r'在\s*"(?P<path>[^"\n]+)"\s*中查找文件\s*"(?P<name>[^"\n]+)"', lambda m: f"find {shlex.quote('./' + m['path'] if m['path'].startswith('-') else m['path'])} -type f -name {shlex.quote(m['name'])}", "在指定目录递归查找；路径和匹配模式均作为独立参数引用。", '在 "/var/log" 中查找文件 "*.log"'),
    Rule(r"查找(?:当前目录下)?(?:所有)?\.(?P<ext>[A-Za-z0-9]+)文件", lambda m: f"find . -type f -name '*.{m['ext']}'", "递归查找具有指定扩展名的普通文件。", "查找当前目录下所有.log文件"),
    Rule(r"(?:查看|查找)(?:占用)?端口\s*(?P<port>\d{1,5})(?:的)?(?:进程|占用情况)", lambda m: f"ss -ltnp 'sport = :{m['port']}'" if 1 <= int(m['port']) <= 65535 else "", "查看该 TCP 监听端口及关联进程；查看其他用户的进程信息可能需要额外权限。端口必须为 1–65535。", "查看占用端口8080的进程"),
    Rule(r'(?:查看|显示)文件\s*"(?P<path>[^"\n]+)"\s*(?:的)?(?:最后|末尾)\s*(?P<n>[1-9]\d{0,4})\s*行', lambda m: f"tail -n {m['n']} -- {shlex.quote(m['path'])}", "显示文件末尾指定行数，不持续跟踪。", '查看文件 "/var/log/syslog" 最后20行'),
    Rule(r'(?:创建|新建)目录\s*"(?P<path>[^"\n]+)"', lambda m: f"mkdir -p -- {shlex.quote(m['path'])}", "创建目录及缺失的父目录；这是写操作，仅提供命令供审核。", '创建目录 "./DHU-CS/backup"'),
    Rule(r'在文件\s*"(?P<path>[^"\n]+)"\s*中搜索\s*"(?P<word>[^"\n]+)"', lambda m: f"grep -nF -- {shlex.quote(m['word'])} {shlex.quote(m['path'])}", "以字面量搜索文本并显示行号；不将搜索内容解释为正则表达式。", '在文件 "/var/log/syslog" 中搜索 "error"'),
    Rule(r'(?:查看|显示)服务\s*"(?P<service>[A-Za-z0-9_.@-]+)"\s*状态', lambda m: f"systemctl --no-pager status -- {shlex.quote(m['service'])}", "查看 systemd 服务状态；适用于使用 systemd 的 Linux 系统。", '查看服务 "ssh" 状态'),
)

COMMANDS = {
    "df": "查看文件系统磁盘空间。-h 使用易读单位。",
    "du": "统计文件/目录占用空间。-s 汇总，-h 使用易读单位。",
    "free": "查看内存和交换空间。-h 使用易读单位。",
    "uptime": "查看运行时间和平均负载。",
    "ps": "查看进程。aux 列出所有用户的进程。",
    "ss": "查看套接字。-t TCP，-u UDP，-l 监听，-n 数字格式，-p 进程。",
    "ip": "管理/查看网络。address show 查看地址，route show 查看路由。其他子命令可能修改网络。",
    "whoami": "显示当前有效用户的用户名。",
    "who": "显示当前登录会话。",
    "id": "显示用户的 UID、GID 和所属组。",
    "uname": "查看内核和机器信息。-a 显示全部。",
    "hostname": "无参数时查看主机名；带参数可能修改主机名。",
    "date": "无参数时显示时间；-s/--set 会修改时间。",
    "pwd": "显示当前工作目录。",
    "ls": "列出文件。-l 长格式，-a 包括隐藏文件，-h 易读大小。",
    "cat": "读取并拼接文件内容。重定向符 > 由 shell 处理，可能覆盖文件。",
    "find": "递归查找。-type f 普通文件，-name 名称模式，-size +100M 大于 100MiB。-delete/-exec 会产生副作用。",
    "grep": "搜索文本。-n 行号，-F 字面匹配，-i 忽略大小写，-r 递归。",
    "tail": "查看文件尾部。-n N 显示末尾 N 行，-f 持续跟踪。",
    "head": "查看文件开头。-n N 指定行数。",
    "wc": "统计行数、单词数和字节数。-l 仅统计行数。",
    "sort": "对文本行排序。-n 数值，-r 降序；-o 会写输出文件。",
    "mkdir": "创建目录。-p 创建缺失的父目录。",
    "cp": "复制文件或目录。可能覆盖目标文件；-i 覆盖前询问。",
    "mv": "移动或重命名文件。可能覆盖目标文件。",
    "rm": "删除文件。-r 递归，-f 强制；删除通常无法撤销。",
    "chmod": "修改文件权限。755 表示所有者 rwx，组和其他用户 r-x。",
    "chown": "修改文件所有者或所属组，通常需要管理员权限。",
    "tar": "归档工具。-c 创建，-x 解包，-t 列表，-z gzip，-f 指定归档文件。",
    "systemctl": "管理 systemd 服务。status 查看，start/stop/restart 会改变服务状态。",
    "sudo": "以其他用户身份执行命令，通常用于获取管理员权限。",
    "journalctl": "读取 systemd 日志。--no-pager 禁用分页。其他参数可能清理日志。",
    "xargs": "将输入转换成命令参数，实际风险取决于后续执行的程序。",
    "sh": "启动 shell 或执行脚本，脚本可以执行任意操作。",
    "bash": "启动 Bash 或执行脚本，脚本可以执行任意操作。",
}


def generate(prompt: str) -> Answer:
    clean = prompt.strip().rstrip("。？?")
    for rule in RULES:
        match = re.fullmatch(rule.pattern, clean, re.IGNORECASE)
        if match:
            command = rule.build(match)
            return Answer(rule.explanation, command)
    return Answer(
        "离线知识库暂不支持这个完整请求，未猜测命令。请运行 examples 查看支持的句式，"
        "或配置接口后使用 --online。路径/文件名请使用英文双引号，例如：查找文件 \"*.log\"。"
    )


def explain(command: str) -> Answer:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;()<>")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as exc:
        return Answer(f"命令引号不匹配：{exc}")
    descriptions = []
    for token in tokens:
        if token in COMMANDS and token not in [item[0] for item in descriptions]:
            descriptions.append((token, COMMANDS[token]))
    if not descriptions:
        return Answer("离线词典没有识别到已知命令。可使用 man 命令名，或配置接口后在线解释。")
    lines = [f"{name}: {description}" for name, description in descriptions]
    if any(token in ("|", "||", "&&", ";", ">", ">>", "<") for token in tokens):
        lines.append("组合符：| 传递输出；&& 前一条成功才继续；|| 失败才继续；; 顺序执行；> 覆盖，>> 追加。")
    lines.append("离线解释为词典提示，不是完整 shell 语法分析；请结合 man 手册核对全部参数。")
    return Answer("\n".join(lines))
