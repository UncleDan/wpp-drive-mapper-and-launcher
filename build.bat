@echo off
echo ============================================
echo  Build: folder_subst.exe (monolitico)
echo ============================================

REM --- Cartella Python personalizzata (primo tentativo) ---
set "PYTHON_CUSTOM=C:\laragon\bin\python"

REM --- Verifica se python e' gia' nel PATH di sistema ---
where python >nul 2>&1
if %ERRORLEVEL% == 0 goto :python_found

REM --- Primo tentativo: cartella personalizzata ---
echo Python non trovato nel PATH di sistema.
echo Ricerca nel percorso personalizzato: %PYTHON_CUSTOM%
if exist "%PYTHON_CUSTOM%\python.exe" (
    echo Trovato Python in: %PYTHON_CUSTOM%
    set "PATH=%PYTHON_CUSTOM%;%PYTHON_CUSTOM%\Scripts;%PATH%"
    goto :python_found
)

echo Ricerca nelle cartelle di installazione comuni...

REM --- Percorsi comuni dove Python potrebbe essere installato ---
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313"
    "%LOCALAPPDATA%\Programs\Python\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python310"
    "%LOCALAPPDATA%\Programs\Python\Python39"
    "%LOCALAPPDATA%\Programs\Python\Python38"
    "C:\Python313"
    "C:\Python312"
    "C:\Python311"
    "C:\Python310"
    "C:\Python39"
    "C:\Python38"
    "C:\Program Files\Python313"
    "C:\Program Files\Python312"
    "C:\Program Files\Python311"
    "C:\Program Files\Python310"
    "C:\Program Files\Python39"
    "C:\Program Files\Python38"
) do (
    if exist %%P\python.exe (
        echo Trovato Python in: %%P
        set "PATH=%%P;%%P\Scripts;%PATH%"
        goto :python_found
    )
)

echo ERRORE: Python non trovato. Installalo da https://www.python.org
pause
exit /b 1

:python_found
echo Utilizzo Python:
where python

echo.
REM Installa PyInstaller se non presente
pip install pyinstaller --quiet

REM Compila in EXE monolitico (--onefile)
pyinstaller --onefile --console --name "FolderSubst" folder_subst.py

echo.
echo Build completato!
echo Il file EXE si trova in: dist\FolderSubst.exe
echo.
echo NOTA: Copiare FolderSubst.exe nella cartella che contiene
echo       le sottocartelle da mappare come unita' di rete.
pause
