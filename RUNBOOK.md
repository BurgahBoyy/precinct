# Precinct — Ops Runbook
*The "it's 3am and something's wrong" guide. Closes audit fix #9 (Observability). All commands use the connector: `S="$(ls -d /sessions/*/mnt/'Arian Biz')/Automation/precinct_gcp.sh"`.*

## First move for ANY incident
```
bash "$S" status        # is it up? which revision/image?
bash "$S" smoke         # does /health answer?
bash "$S" logs 60       # recent Cloud Run logs (5xx/slow are logged as JSON)
```
Alerting: a Cloud Monitoring uptime check hits `/health` every 5 min; **"Precinct is DOWN (/health failing)"** emails rob@sailwellness.app after 5 min of failure. (Verify the email channel once via the Google verification email so alerts deliver.)

## Incident 1 — the app is DOWN / 5xx
- `bash "$S" status` → if no ready revision, a bad deploy: **roll back** to the last good image: `bash "$S" deploy-image <previous-tag>` (tags in DEPLOY.md rev ledger, e.g. `director-2`).
- `bash "$S" logs 80` → look for the JSON `"lvl":"ERROR"` 5xx lines (path + status).
- If it's a DB error (see Incident 2), fix that first.

## Incident 2 — database errors / "authentication failed" / timeouts
- Cloud SQL instance: `bash "$S"` won't touch SQL directly. Check the instance is RUNNABLE in console, or the connector's env: `bash "$S" env` (PRECINCT_PG_* names present?).
- db.py retries once on a dropped connection automatically. Sustained failures → instance may be down or over connection cap (known Thin: single-connection design). Restart the service revision to reset the pool: re-`deploy-image` the current tag.

## Incident 3 — cold-start data loss (tags/lists/contributions vanished)
- Root cause if it happens: the app fell back to per-instance SQLite instead of Postgres. Confirm `bash "$S" env` shows `PRECINCT_PG_SOCKET/DB/USER/PASSWORD`. If missing, re-set them (creds in `Arian Biz/precinct-db-credentials.txt`, never printed) and redeploy. Durable data REQUIRES the PG env present.

## Incident 4 — a voter-file / ballot-file load went wrong
- Loads are admin-gated and idempotent (upserts). A bad file: re-run the load with the corrected file (it overwrites by voter_id). To wipe a bad load, delete from the `voters` / `ballot_status` tables for that batch (DB access via the deployer key — do NOT print creds).
- If turnout scores look off after a partial county load: the universe auto-rescores on growth (audit fix #5), but a manual `_rescore_all(universe)` can be triggered by reloading any county.

## Escalation / human gates (never automate)
Anything touching IAM, making the service public/private, spend, or sending mail to real people stays with Rob (see `AUTONOMY_MANIFEST.md` + `_Logs/HUMAN_GATES_CHECKLIST.md`).
