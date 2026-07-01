#!/usr/bin/env bash
# Precinct -> Cloud Run (project political-app). For Cloud Shell / macOS / Linux.
set -e
cd "$(dirname "$0")"
KEY=""
[ -f "../claude api key.txt" ] && KEY="$(tr -d ' \r\n' < "../claude api key.txt")"
gcloud run deploy precinct --source . \
  --project political-app --region us-central1 \
  --allow-unauthenticated --set-env-vars "ANTHROPIC_API_KEY=$KEY"
echo "Look for 'Service URL: https://precinct-....run.app' above."
