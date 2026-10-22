@echo off
title Game Shop Auto Buyer

echo ========================================
echo   Auto Shop Buyer Tool
echo ========================================
echo.

py -3.14 --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.14 not found.
    pause
    exit /b 1
)

echo Checking dependencies...
py -3.14 -c "import pyautogui, mss, PIL, numpy, cv2, keyboard, winocr" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies, please wait...
    py -3.14 -m pip install pyautogui mss Pillow numpy opencv-python keyboard winocr
    if errorlevel 1 (
        echo [ERROR] Install failed.
        pause
        exit /b 1
    )
)

echo.
echo Starting tool...
echo.
echo Hotkeys:
echo   F9  = Start / Pause
echo   F10 = Emergency Stop
echo.
echo Note: Open the game shop window first!
echo.

py -3.14 "%~dp0shop_buyer.py"

pause
