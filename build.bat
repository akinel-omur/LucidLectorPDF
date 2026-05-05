@echo off
REM Build LucidLectorPDF as a single-file Windows executable.
setlocal

echo [1/3] Ensuring PyInstaller is installed...
python -m pip install --upgrade pyinstaller >nul

echo [2/3] Regenerating icon...
python tools\make_icon.py

echo [3/3] Building LucidLectorPDF.exe ...
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --onefile ^
    --name "LucidLectorPDF" ^
    --icon "resources\icon.ico" ^
    --add-data "resources\icon.ico;resources" ^
    main.py

echo.
if exist "dist\LucidLectorPDF.exe" (
    echo Build OK: dist\LucidLectorPDF.exe
) else (
    echo BUILD FAILED.
    exit /b 1
)
endlocal
