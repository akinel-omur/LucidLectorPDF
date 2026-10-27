@echo off
REM Serve the web reader locally.
REM
REM Opening index.html straight from disk does not work: browsers block ES
REM modules and web workers loaded over file://. serve.py is a small static
REM server that also pins the JavaScript MIME type, which `python -m
REM http.server` gets wrong on Windows whenever the registry maps .js to
REM text/plain -- a browser then refuses to run the app at all.

setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python serve.py %1
    goto :done
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 serve.py %1
    goto :done
)

echo.
echo Python bulunamadi.
echo Node kuruluysa sunu deneyin:   npx serve .
echo.

:done
pause
