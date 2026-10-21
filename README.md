# DHU-CS 终端智能助手

这是实验七“内容二：类 shell-gpt 智能助手功能的实现”的可运行项目。使用 Python 标准库实现终端界面、Linux 命令知识库、大模型接口和本地记忆，无运行时第三方依赖。借鉴 ShellGPT 的对话与记录保存思路，独立编写实现。

支持自然语言生成命令、命令解释、交互对话、SQLite 历史搜索和收藏。没有接口密钥时自动使用离线知识库；配置密钥后默认在线，也可以通过 `--offline` 或 `--online` 明确选择。

## 快速开始

需要 Python 3.10 或更新版本。把整个 lab7 文件夹放进 Linux 实验虚拟机，然后在该目录运行：

```bash
python3 -m lab_shell shell --offline "查看磁盘使用情况"
python3 -m lab_shell shell --offline "查找当前目录下大于100MB的文件"
python3 -m lab_shell explain --offline "find . -type f -name '*.log'"
python3 -m lab_shell chat --offline
```

首条命令会输出 `df -h`、中文解释以及执行检查结果。所有生成结果默认仅预览。Windows 也能生成、解释和管理历史，使用 `python` 替换 `python3`；执行功能仅开放给 Linux。

离线模式是**有限的意图匹配与模板生成**，不是本地大语言模型。仅接受知识库支持的完整句式，避免忽略不支持的条件后生成错误命令。查看全部 26 个句式：

```bash
python3 -m lab_shell examples
python3 -m lab_shell shell --offline '在 "/var/log" 中查找文件 "*.log"'
python3 -m lab_shell shell --offline '在文件 "/var/log/syslog" 中搜索 "error"'
python3 -m lab_shell shell --offline '创建目录 "./DHU-CS/backup"'
```

示例中的路径供演示，实际存在的目录和日志位置取决于你的虚拟机。离线模板使用英文双引号标记路径、文件名或搜索内容；中文引号不作为槽位分隔符。

## 安装终端命令

不安装也能通过 `python3 -m lab_shell` 使用所有功能。希望在任意目录使用 `lab-shell` 时，可安装到虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
lab-shell shell --offline "查看IP地址"
```

项目自身没有运行时依赖，pip 安装可能需要获取 setuptools 构建工具。无法联网时使用前面的模块启动方式。

## 配置在线模型

客户端使用 `POST {SHELL_AI_BASE_URL}/chat/completions`，请求包含 `model`、`messages` 和 `stream: false`，读取 `choices[0].message.content`。可连接兼容此协议的云服务或本地模型服务。

以下是 DeepSeek 配置示例，模型名以服务商当前文档和账户支持情况为准。不要把真实密钥写进代码、报告或截图：

```bash
read -rsp 'API Key: ' SHELL_AI_API_KEY; echo
export SHELL_AI_API_KEY
export SHELL_AI_BASE_URL='https://api.deepseek.com'
export SHELL_AI_MODEL='deepseek-flash'
export SHELL_AI_TIMEOUT='30'

python3 -m lab_shell ask --online "解释Linux文件权限755，并举例"
python3 -m lab_shell shell --online "在当前目录查找7天内修改过且大于10MB的日志文件"
python3 -m lab_shell chat --online
```

程序会自动读取**当前工作目录的 `.env`**；当前目录没有该文件且正在使用源码项目时，会读取 lab7 下的 `.env`。已有系统环境变量优先于文件；同一来源中 `SHELL_AI_*` 字段优先于别名。配置中的值只按文本读取，不执行 shell 命令或变量替换，无需 `source .env`。

你的配置也可使用以下字段（`BASEURL`、`API_KEY`、`MODEL` 分别对应 `SHELL_AI_BASE_URL`、`SHELL_AI_API_KEY`、`SHELL_AI_MODEL`）：

```dotenv
BASEURL=https://api.deepseek.com
API_KEY=你的密钥
MODEL=deepseek-flash
```

配置完成后直接运行 `python3 -m lab_shell chat` 即会选择在线模式，并显示当前模型。未填写模型时默认为 `deepseek-flash`。PowerShell 使用 `python -m lab_shell chat`。`--offline` 仍可显式选择离线知识库，该模式不读取 `.env`。

如果接口返回 HTTP 402，程序会提示“账户余额不足”，需要先在服务商账户中处理余额问题；程序不会将失败请求自动切换成其他模型。

本地接口可设置为 `http://127.0.0.1:11434/v1`，模型名填入本地已安装且支持聊天的模型。回环地址不强制要求密钥。BASE_URL 填 API 根路径，不要重复添加 `/chat/completions`；远程地址要求 HTTPS，HTTP 仅允许回环地址。程序拒绝重定向，以免将密钥发送到其他地址。

在线 `shell` 模式要求模型生成包含 `command`、`explanation` 的 JSON 对象；回答截断、格式错误或接口失败时明确报错，不把自由文本猜测成命令，也不自动回退后执行离线结果。

## 使用历史和收藏

```bash
python3 -m lab_shell history
python3 -m lab_shell history --search "磁盘"
python3 -m lab_shell favorite 1
python3 -m lab_shell history --favorites
python3 -m lab_shell favorite 1 --remove
python3 -m lab_shell history --clear --confirm CLEAR
```

默认路径为 `${XDG_DATA_HOME:-~/.local/share}/lab-shell/history.sqlite3`。可以在问答、交互或历史子命令后传入 `--data-dir ./my-data` 更换位置；操作同一组历史时应使用相同目录。

问答默认保存输入、回答、建议命令、来源和 UTC 时间，不保存接口密钥或命令执行输出。敏感问题请加 `--no-history`；该选项也会禁止为本次问答创建数据库。清空历史是逻辑删除，不保证存储介质上的物理擦除。

交互会话支持 `/shell 需求`、`/explain 命令`、`/history`、`/help`、`/clear` 和 `/exit`。在线普通问答保留最近 6 轮上下文；`/shell` 和 `/explain` 独立处理。`/clear` 仅清空内存上下文，数据库历史通过 `history --clear --confirm CLEAR` 管理。

在线请求默认不附带工作目录或文件列表。显式添加 `--context` 时，会发送当前路径、主机平台、shell 路径以及按名称排序的前 30 个目录项名称，不读取文件内容。用户直接输入的文字及当前会话上下文仍会发给配置的服务商。

## 确认执行

在 Linux 交互终端中使用：

```bash
python3 -m lab_shell shell --offline --execute "查看磁盘使用情况"
```

检查显示的完整命令后输入 `EXECUTE` 才执行，其他输入取消。程序只允许严格匹配白名单参数语法的部分只读命令，通过 `subprocess.run(..., shell=False)` 调用系统目录中的程序，不使用用户 PATH 中的同名程序。最长运行 30 秒，不接受管道输入自动确认，不提供跳过确认的选项。

写操作、提权、解释器、组合命令、重定向和替换均只能查看建议，需用户审核后自行在终端操作。例如 `mkdir` 和 `systemctl status` 的建议可以生成，但当前执行白名单不会放行。白名单是保守的交互防护，**不是安全沙箱**；只读命令仍可能暴露信息或消耗资源。不要把模型输出自动传给 `bash`、`eval` 或 `sh -c`。

支持自动化读取结果，但 JSON 模式不能与执行混用：

```bash
python3 -m lab_shell shell --offline --no-history --json "查看内存使用情况"
```

## 验证与实验演示

完整本地测试通过 Python 标准库运行，会在回环地址启动 HTTP 测试服务，不需要真实密钥：

```bash
python3 -m unittest discover -s tests -v
bash examples/demo.sh
```

另提供 Postman CLI 1.70+ 接口模拟。一个终端启动服务，另一个终端运行验证，用完在服务终端按 Ctrl+C 停止：

```bash
postman simulation run postman/simulations/assistant.sim.yaml --port 4900 --output ndjson --no-history
```

```bash
python3 -m tests.postman_smoke
```

模拟只在本机运行，测试的是实际客户端与本地固定响应之间的 HTTP 调用，不代表真实大模型的推理质量。`postman/chat-contract.json` 是依据官方接口文档编写的最小协议子集；mock 由该子集生成并加入请求校验，未使用服务商提供的现成 mock。限流、服务错误和延迟通过模拟条件注入。

实验步骤、实现原理、效果展示方法及当前验证范围见 [实验说明](docs/实验说明.md)。实验指导书要求命令行截图保留**姓名首字母缩写的用户名**；请使用本人 Linux 实验账户操作，不要伪造提示符或截图结果。

## 项目文件

- `lab_shell/cli.py`：参数、终端界面、交互会话和确认执行。
- `lab_shell/knowledge.py`：意图规则、参数槽位、Bash 引用和命令词典。
- `lab_shell/assistant.py`：在线/离线路由、上下文和结构化命令校验。
- `lab_shell/client.py`：可配置 HTTP 客户端、超时和异常处理。
- `lab_shell/config.py`：自动读取 `.env`、配置别名和优先级，不执行文件中的命令。
- `lab_shell/safety.py`：执行白名单及参数语法检查。
- `lab_shell/storage.py`：SQLite 历史、搜索和收藏。
- `tests/`：功能、HTTP 和接口模拟验证。

## 参考资料

- [指导书所给 ShellGPT 项目](https://github.com/akl7777777/ShellGPT)：其公开说明展示了对话上下文和记录保存功能；本项目选择实验内容二，不声称是该项目源码改进版。
- [DeepSeek Chat Completions 官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)：请求和响应协议参考。
- [Python subprocess 文档](https://docs.python.org/3/library/subprocess.html)、[shlex 文档](https://docs.python.org/3/library/shlex.html)、[sqlite3 文档](https://docs.python.org/3/library/sqlite3.html)：标准库实现参考。
