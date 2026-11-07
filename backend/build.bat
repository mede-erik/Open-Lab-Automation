@echo off
REM Copyright (C) 2025-2026 Erik Medeossi
REM This file is part of Open Lab Automation.
REM Licensed under the GNU General Public License v3.0; see the LICENSE file.

REM Build C backend as shared library (Windows/MinGW)
REM Requires: MinGW-w64 (gcc) in PATH
REM
REM Usage: build.bat
REM Output: backend.dll

echo === Building C Backend (Windows DLL) ===

set SRC=backend.c instrument.c platform.c sweep.c

where gcc >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: gcc not found. Install MinGW-w64 and add to PATH.
    exit /b 1
)

gcc -shared -o backend.dll %SRC% -I. -lm -lws2_32
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Build failed.
    exit /b %ERRORLEVEL%
)

echo Output: backend.dll
echo === Build complete ===
