@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "import flask, waitress, docx, pymupdf, pythainlp" 2>nul || python -m pip install -r requirements.txt
python run.py
pause
