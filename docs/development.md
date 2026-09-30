# Development guide

## Local environment

Use Python 3.10 or newer. From the repository root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `FLASK_SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `FERNET_KEY`, then migrate and run:

```powershell
flask --app run db upgrade
python run.py
```

On macOS/Linux, use `python3 -m venv .venv`, `source .venv/bin/activate`, and copy `.env.example` to `.env` with the shell's normal copy command. `python run.py` also applies migrations before starting the development server.

## Source layout

| Path | Contents |
| --- | --- |
| `app/auth.py` | Signup, login, logout, and user loading |
| `app/routes/` | Authenticated UI and owner-scoped actions |
| `app/models.py` | SQLAlchemy model definitions |
| `app/pipeline.py` | Job lifecycle and publication/retry orchestration |
| `app/kaggle_client.py` | Kaggle push, polling, and output download |
| `app/scheduler.py` | APScheduler integration and scheduled job creation |
| `app/storage.py` | Private Supabase object operations |
| `app/*_client.py` | External provider clients |
| `notebook/` | Kaggle notebook source copied for each job |
| `migrations/versions/` | Ordered Alembic migrations |
| `tests/` | Local checks and optional live Kaggle smoke test |

## Database changes

Change SQLAlchemy models, then create and inspect a migration:

```powershell
flask --app run db migrate -m "describe schema change"
```

Review the generated file for PostgreSQL and SQLite behavior, data backfills, foreign keys, and downgrade handling. Never rewrite a migration already applied to a shared or production database. Apply locally with `flask --app run db upgrade`; deploy the reviewed migration through the configured startup sequence.

Every user-owned query and mutation must verify `user_id` from the authenticated session. External provider lookups must use the job owner ID. Add migrations for schema changes and consider foreign-key cascades and unique constraints within each workspace.

## Tests and live integrations

The repository includes local tests and `test_kaggle_live_smoke.py`, which makes real Kaggle API calls and needs credentials and a configured kernel. Run that live check only when you intentionally want to use the external Kaggle account. Tests that touch provider services, cloud resources, or user data should use isolated local fixtures and mocked clients. This guide does not claim the current suite passes; refresh fixtures when schema or ownership requirements change.

## Change checklist

- Keep secrets, local databases, notebooks' generated outputs, and runtime artifacts out of Git.
- Keep the notebook parameter contract synchronized with `app/kaggle_client.py` and the notebook itself.
- Keep schedule preset values synchronized between templates and `app/scheduler.py`.
- Update the relevant guide when environment variables, migrations, job states, or external provider behavior changes.
