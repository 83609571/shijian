#!/bin/bash
# 赣鄱智轨 · macOS 现场一键启动
# 首次使用请先赋执行权限（只需一次）：chmod +x demo.command
# 之后在访达双击本文件，或在终端运行 ./demo.command（参数同 demo.py）：
#   ./demo.command --port 9000 --no-browser
cd "$(dirname "$0")" || exit 1
exec python3 demo.py "$@"
