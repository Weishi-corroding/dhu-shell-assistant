#!/usr/bin/env bash
# Run in the Linux lab VM: bash examples/demo.sh
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONUTF8=1
PYTHON_BIN="${PYTHON_BIN:-python3}"
DATA_DIR='.demo-data'

printf '实验用户：%s\n' "$(id -un)"
printf '请确认该账户名符合实验要求（本人姓名首字母缩写）。\n'

printf '\n1. 自然语言生成磁盘查询命令\n'
"$PYTHON_BIN" -m lab_shell shell --offline --data-dir "$DATA_DIR" "查看磁盘使用情况"
printf '\n2. 带数值参数的命令生成\n'
"$PYTHON_BIN" -m lab_shell shell --offline --data-dir "$DATA_DIR" "查找当前目录下大于100MB的文件"
printf '\n3. 带目录和文件名模式的命令生成\n'
"$PYTHON_BIN" -m lab_shell shell --offline --data-dir "$DATA_DIR" '在 "/var/log" 中查找文件 "*.log"'
printf '\n4. 解释管道命令（仅解释，不执行）\n'
"$PYTHON_BIN" -m lab_shell explain --offline --data-dir "$DATA_DIR" "ps aux | grep python"
printf '\n5. 展示近期历史\n'
"$PYTHON_BIN" -m lab_shell history --data-dir "$DATA_DIR" --limit 4
printf '\n6. 用 JSON 输出，且不保存历史\n'
"$PYTHON_BIN" -m lab_shell shell --offline --no-history --json "查看内存使用情况"
printf '\n演示完成。以上为命令生成效果；实际运行可另行使用 shell --execute 并人工确认。\n'
