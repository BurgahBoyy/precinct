@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Precinct - deploy to Google Cloud Run (project: political-app)
echo ============================================================
echo.

REM --- read the Claude API key from the folder above (never printed) ---
set "KEY="
if exist "..\claude api key.txt" (
  for /f "usebackq delims=" %%A in ("..\claude api key.txt") do set "KEY=%%A"
)
if defined KEY (echo [ok] Claude key loaded.) else (echo [!!] Claude key not found - the app will still deploy, AI intake will fall back to rules.)
echo.

echo Building and deploying from source ^(uses the Dockerfile^). First run may take ~3-5 min...
echo.
call gcloud run deploy precinct --source . --project political-app --region us-central1 --allow-unauthenticated --set-env-vars "ANTHROPIC_API_KEY=!KEY!"

echo.
echo ============================================================
echo  Look for a line like:   Service URL: https://precinct-xxxxx.run.app
echo  Copy that URL into Rob's chat - that's the live link for Arian.
echo ============================================================
pause
