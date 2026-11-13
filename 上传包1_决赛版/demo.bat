@echo off
rem 赣鄱智轨 - 现场一键启动（Windows）
rem 双击本文件即可；也可在命令行带参数运行：demo.bat --port 9000 --no-browser
chcp 65001 >nul
title 赣鄱智轨 - 现场一键启动
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 demo.py %*
  goto end
)
where python >nul 2>nul
if %errorlevel%==0 (
  python demo.py %*
  goto end
)
echo [错误] 未找到 Python。请先安装 Python 3.9+：https://www.python.org/downloads/
echo 安装时务必勾选 "Add Python to PATH"，装完后重新双击本文件。
echo 若仍失败，可改用自带解释器的便携版 Python（解压即用，无需管理员权限）。
:end
if %errorlevel% neq 0 pause
