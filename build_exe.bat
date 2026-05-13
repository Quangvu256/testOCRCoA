@echo off
REM ══════════════════════════════════════════════════════════
REM  Build setup_project.py -> MaterialOCR_Setup.exe
REM  Yêu cầu: Python + PyInstaller
REM ══════════════════════════════════════════════════════════

echo.
echo ========================================
echo   Building MaterialOCR_Setup.exe
echo ========================================
echo.

REM Check PyInstaller
pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Build .exe
echo Building executable...
pyinstaller ^
    --onefile ^
    --name MaterialOCR_Setup ^
    --console ^
    --clean ^
    --noconfirm ^
    setup_project.py

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================
    echo   SUCCESS!
    echo   Output: dist\MaterialOCR_Setup.exe
    echo ========================================
    echo.
    echo Copy file .exe vao thu muc project cung voi:
    echo   - docker-compose.yml
    echo   - requirements.txt
    echo   - .env.example
    echo   - data\sample_materials.csv
    echo   - app.py, config.py, models.py, modules\
    echo   - init_db.py
) else (
    echo.
    echo BUILD FAILED! Check errors above.
)

pause
