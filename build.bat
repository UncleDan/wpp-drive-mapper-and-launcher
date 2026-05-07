@echo off
REM build.bat  -  Compile both tools into monolithic Windows executables
REM Requires: pip install pyinstaller

echo === Building wpp-drive-mapper ===
python -m PyInstaller --onefile --windowed --name "wpp-drive-mapper" --clean wpp-drive-mapper.py
if %ERRORLEVEL% neq 0 ( echo ERROR: wpp-drive-mapper build failed. & pause & exit /b 1 )

echo.
echo === Building wpp-clean-drives ===
python -m PyInstaller --onefile --windowed --name "wpp-clean-drives" --clean wpp-clean-drives.py
if %ERRORLEVEL% neq 0 ( echo ERROR: wpp-clean-drives build failed. & pause & exit /b 1 )

echo.
echo Build successful:
echo   dist\wpp-drive-mapper.exe
echo   dist\wpp-clean-drives.exe
pause
