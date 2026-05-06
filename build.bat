@echo off
REM build.bat  -  Compile wpp-drive-mapper.py into a monolithic Windows executable

set EXE_NAME=wpp-drive-mapper

echo === Building %EXE_NAME% ===

python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "%EXE_NAME%" ^
    --clean ^
    wpp-drive-mapper.py

if %ERRORLEVEL% == 0 (
    echo.
    echo Build successful: dist\%EXE_NAME%.exe
) else (
    echo.
    echo ERROR: build failed.
)

pause