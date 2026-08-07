@echo off
title Backtest Pro - NASDAQ
cd /d "%~dp0"
echo.
echo  Backtest Pro - Demarrage sur http://localhost:8501
echo.
".venv\Scripts\python.exe" -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false --server.headless false
echo.
echo  Application arretee.
pause
