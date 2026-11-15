@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" -m pip install pyinstaller
".venv\Scripts\python.exe" -m PyInstaller --noconsole --onefile --name ExamTrainer ^
    --collect-all pdfplumber --collect-all pypdfium2 --collect-submodules pdfminer main.py
echo.
echo Done: dist\ExamTrainer.exe
pause
