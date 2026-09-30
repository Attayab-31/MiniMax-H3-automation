# H3 Video Automation

A Flask application for creating short videos with a private Kaggle notebook running MiniMax H3. Users manage their own prompts, GPU accounts, schedules, provider credentials, job history, and video library.

## What it does

- Self-service signup and login with per-user workspaces.
- Manual and scheduled video generation on one or more user-configured Kaggle accounts.
- Per-user Gemini credentials for prompt writing and publishing metadata, with a deterministic prompt fallback.
- Per-user YouTube and TikTok credentials. YouTube uploads default to private; TikTok publishing is restricted to self-only visibility.
- Job progress, retry actions, video previews and downloads, and deletion of prompts or stored videos.
- PostgreSQL persistence and optional private Supabase Storage for generated video files.

## Start here

- [Complete Word project guide](H3_Video_Automation_Complete_Guide.docx)
- [Architecture and data flow](docs/architecture.md)
- [User guide](docs/user-guide.md)
- [Configuration reference](docs/configuration.md)
- [Deployment guide](docs/deployment.md)
- [Development guide](docs/development.md)
- [Operations and recovery](docs/operations.md)
- [Security model and limitations](docs/security.md)

## Quick local setup

Requires Python 3.10 or newer. From the repository root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`: set `FLASK_SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and a valid `FERNET_KEY`. Generate the two secrets with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Apply schema migrations and start the app:

```powershell
flask --app run db upgrade
python run.py
```

Open <http://127.0.0.1:5000>. The migration creates the configured admin user; sign in with `ADMIN_USERNAME` and `ADMIN_PASSWORD`. Other users can create accounts from **Create an account**. Each user adds their own credentials under **Settings**.

When upgrading an existing database, the workspace migrations assign the existing jobs, schedules, Kaggle accounts, and platform credentials to the configured initial admin user. Keep a database backup before production upgrades.

## Production deployment

Render deployment is configured in [`render.yaml`](render.yaml). It runs migrations before starting Gunicorn. Production needs PostgreSQL, a stable `FLASK_SECRET_KEY`, `ADMIN_PASSWORD`, and `FERNET_KEY`. Configure private Supabase Storage for durable videos. See [Deployment](docs/deployment.md) for setup, migration recovery, and service limits.

## Repository map

| Path | Responsibility |
| --- | --- |
| `app/routes/` | Authentication, dashboard, generation, jobs, schedules, and settings routes |
| `app/models.py` | Users, generation jobs, schedules, Kaggle accounts, and provider credentials |
| `app/pipeline.py` | Background job lifecycle, retries, and publishing orchestration |
| `app/kaggle_client.py` | Notebook parameter injection, Kaggle submission, status polling, and output retrieval |
| `app/storage.py` | Private Supabase Storage uploads, signed access, downloads, and deletion |
| `app/*_client.py` | Kaggle, Gemini, YouTube, and TikTok integrations |
| `notebook/` | Source Kaggle notebook; a clean copy is submitted per job |
| `migrations/versions/` | Alembic schema history; do not edit deployed revisions |
| `tests/` | Local route and Kaggle client checks, plus an explicitly live Kaggle smoke check |

## Operational caveat

The scheduler and job executor run in the web process. The Render blueprint uses one Gunicorn worker because the scheduler is in-process. This is suitable for a small deployment, but it is not a durable queue: restarts can interrupt web-side work, and Render's free service may sleep. See [Operations](docs/operations.md) before relying on unattended schedules.
