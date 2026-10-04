@echo off
chcp 65001 >nul
setlocal

REM ==========================================================================
REM  Сборка Steam Hours Viewer в один исполняемый файл .exe (PyInstaller)
REM  Запускать на Windows, двойным кликом по этому файлу.
REM  Результат появится в папке dist\SteamHoursViewer.exe
REM ==========================================================================

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

echo [*] Устанавливаю зависимости (requests, pyinstaller)...
pip install --quiet --upgrade pip
pip install --quiet requests pyinstaller

echo [*] Собираю SteamHoursViewer.exe ...
set ICON_ARG=
if exist assets\app.ico set ICON_ARG=--icon=assets\app.ico

pyinstaller --noconfirm --onefile --windowed --name SteamHoursViewer %ICON_ARG% app.py

echo.
if exist dist\SteamHoursViewer.exe (
    echo [OK] Готово! Файл находится здесь:
    echo      %cd%\dist\SteamHoursViewer.exe
) else (
    echo [!] Что-то пошло не так, .exe не создан. Смотрите вывод выше.
)

pause
