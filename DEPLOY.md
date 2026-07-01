# Precinct — Deploy to Cloud Run (your GCP project: political-app)

The app is ready to ship: `Dockerfile`, `.dockerignore`, and `.github/workflows/deploy.yml` (keyless WIF → Cloud Run) are all in this folder. Because you already deploy VFE/FFC to Cloud Run, you have the WIF provider + deploy service account to reuse.

## The short path (you have connectors + a GCP project already)
1. **Clean the partial git folder** (I couldn't remove it from my sandbox):
   - In this folder, delete the `.git` folder.
2. **Create the repo + push** (GitHub user `BurgahBoyy`):
   ```
   cd "C:\Users\rober\OneDrive\Documents\Arian Biz\precinct"
   git init
   git add -A
   git commit -m "Precinct v0.2"
   git branch -M main
   git remote add origin https://github.com/BurgahBoyy/precinct.git
   git push -u origin main
   ```
   (Create the empty `precinct` repo at github.com/new first, or use your GitHub connector to create+push.)
3. **Set the deploy config** in the repo → Settings → Secrets and variables → Actions:
   - **Variables:** `GCP_PROJECT=political-app`, `GCP_REGION=us-central1` (or your region), `SERVICE=precinct`, `WIF_PROVIDER=<reuse your VFE provider>`, `DEPLOY_SA=<reuse your VFE deploy service account>`.
   - **Secret:** `ANTHROPIC_API_KEY` = your Claude key (so document-reading works live).
4. **Grant the reused WIF binding** access to the new repo + confirm the deploy SA has `run.admin` + `cloudbuild.builds.editor` on `political-app` (your VFE SA likely already does at the org level).
5. **Deploy:** the push to `main` triggers the workflow → builds the container → deploys to Cloud Run → prints a public `*.run.app` URL. (Or run it manually: repo → Actions → "deploy" → Run workflow.)

## First-time WIF (only if you're NOT reusing an existing provider)
One-time in Cloud Shell: create a Workload Identity Pool + provider for GitHub, a deploy service account, and bind them. Your `VFE_GCP_CONNECTOR` / `FFC_DEPLOY_CONNECTOR` docs already contain this exact setup — copy it, swapping the project to `political-app`, repo to `BurgahBoyy/precinct`, service to `precinct`.

## Notes
- **Data on Cloud Run:** the SQLite DB is per-instance and resets on cold starts — perfect for a demo Arian pokes at. For durable multi-user data, point the store at Cloud SQL (a follow-up; the seam is `db.py`).
- **Public access:** `--allow-unauthenticated` makes it clickable for Arian. Add auth before real voter data.
