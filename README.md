# MiniMax H3 Video Automation

Flask app for submitting H3 video jobs to Kaggle, scheduling generations, and storing job data in PostgreSQL. The checked-in Kaggle notebook runs the GPU work; this web service manages prompts, accounts, jobs, and results.

## Deploy on Render with Supabase

1. Create an empty GitHub repository, then push this initialized local repository (replace the URL with your repository):

   ```powershell
   git remote add origin https://github.com/<your-user>/<your-repository>.git
   git add .
   git commit -m "Prepare H3 automation for Render"
   git push -u origin main
   ```

2. Connect that repository to Render using **New > Blueprint**. Render reads `render.yaml` and creates a free web service.
3. Create a Supabase project. In **Project Settings > Database**, copy the **Transaction pooler** connection string from **Connect**. Enter that as `DATABASE_URL` when Render prompts for it. Keep the pooler username and URL exactly as Supabase provides them; URL-encode special characters in the database password.
4. In Supabase **Storage**, create a **private** bucket named `h3-videos`. Set its file size limit high enough for your generated videos and its MIME allowlist to include `video/mp4`. The app uploads videos using the service role key, so end users do not need public bucket access.
5. Add these Render Blueprint values when prompted:
   - `ADMIN_PASSWORD`: a unique, long password for the web app.
   - `FERNET_KEY`: generate one locally with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep this value safe and unchanged: it encrypts Kaggle API keys stored in Postgres, and changing it makes existing saved keys unreadable.
   - `SUPABASE_URL`: the project URL, such as `https://<project-ref>.supabase.co`.
   - `SUPABASE_SERVICE_ROLE_KEY`: the project service role key from Supabase API settings. Store it only in Render secrets; never commit it or put it in browser code.
   - `DATABASE_URL`: the Supabase Transaction pooler URL.
6. After deployment, open the Render service URL, sign in as `admin`, and add Kaggle accounts in **Settings**. Each account needs its Kaggle username and API key. You can optionally set Gemini and publishing integrations as Render environment variables.

The start command applies committed Flask-Migrate revisions before Gunicorn starts. Keep schema changes in new migration files (`flask --app run db migrate -m "describe change"`) and commit them with the code.

## Local development

Create a virtual environment, install `requirements.txt`, copy `.env.example` to `.env`, and set `FLASK_SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and a valid `FERNET_KEY`. Leave `DATABASE_URL` unset to use the local SQLite database. Initialize it with:

```powershell
.\.venv\Scripts\python.exe -m flask --app run db upgrade
.\.venv\Scripts\python.exe run.py
```

On macOS/Linux use `python -m flask --app run db upgrade` and `python run.py`.

## Free Render service limits

Supabase keeps database rows and video files across Render restarts. Render's free web service can sleep after inactivity and can restart at any time. Scheduled runs and jobs currently execute inside the web process, so they are not guaranteed to run on time or finish through sleep/restarts. For reliable unattended scheduling and long-running generation, use an always-on Render plan with a separate background worker/queue. Free service capacity also limits how many requests and uploads can be handled at once.

## Security and operations

- Do not commit `.env`, Kaggle keys, Supabase service role keys, generated videos, or the local database.
- Back up Supabase data and keep a secure copy of `FERNET_KEY`.
- `/health` checks database connectivity and is used by Render's health monitor.
