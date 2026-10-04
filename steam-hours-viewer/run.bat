@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  Steam Hours Viewer — запуск без сборки .exe (нужен Python)
REM ============================================================

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python не найден в PATH.
    echo     Скачайте и установите Python с https://www.python.org/downloads/
    echo     При установке ОБЯЗАТЕЛЬНО отметьте галочку "Add Python to PATH".
    pause
    exit /b 1
)

if not exist venv (
    echo [*] Создаю виртуальное окружение...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo [*] Проверяю/устанавливаю зависимости...
pip install --quiet --upgrade pip
pip install --quiet requests

echo [*] Запускаю Steam Hours Viewer...
python app.py

pause
