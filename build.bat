@echo off
setlocal
cd /d "%~dp0"

py -m pip install --upgrade pip
if errorlevel 1 goto error

py -m pip install -r requirements.txt
if errorlevel 1 goto error

py -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ExamTrainer ^
  --collect-all pypdfium2 ^
  --collect-all pdfplumber ^
  --collect-all PIL ^
  exam_app.py
if errorlevel 1 goto error

echo.
echo Build complete: dist\ExamTrainer.exe
pause
exit /b 0

:error
echo.
echo Build failed. Check the error messages above.
pause
exit /b 1
