@echo off
chcp 65001 >nul
title 作业提交批改系统

:: 配置 (可修改)
set PORT=5001
set TEACHER_CODE=zuoye2026
set SECRET_KEY=zuoye-system-secret-key-2026

:: 安装依赖 (首次运行)
pip install -r requirements.txt -q

echo.
echo ========================================
echo   作业提交批改系统 - 校园版
echo ========================================
echo.

python app.py

pause
