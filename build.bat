@echo off
REM Build AkinelPDF as a single-file Windows executable.
setlocal

echo [1/3] Ensuring PyInstaller is installed...
python -m pip install --upgrade pyinstaller >nul

echo [2/3] Regenerating icon...
python tools\make_icon.py

echo [3/3] Building AkinelPDF.exe ...
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --onefile ^
    --name "AkinelPDF" ^
    --icon "resources\icon.ico" ^
    --add-data "resources\icon.ico;resources" ^
    main.py

echo.
if exist "dist\AkinelPDF.exe" (
    echo Build OK: dist\AkinelPDF.exe
) else (
    echo BUILD FAILED.
    exit /b 1
)
endlocal
