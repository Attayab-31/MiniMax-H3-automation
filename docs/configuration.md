# Configuration reference

The application reads environment variables (and a local `.env` via `python-dotenv`). Copy `.env.example` to `.env` for local development. Do not commit `.env` or put production secrets into the example file.

| Variable | Required | Purpose and behavior |
| --- | --- | --- |
| `FLASK_SECRET_KEY` | Yes | Flask session signing key. Startup fails if missing. Keep stable across restarts and instances. |
| `ADMIN_USERNAME` | For first workspace migration | Username for the initial workspace user; defaults to `admin`. Existing account usernames/passwords are database records, so changing env values later does not reset them. |
| `ADMIN_PASSWORD` | For first workspace migration | Initial password for the migration-created workspace user. Migration fails if no usable password is available. |
| `ADMIN_CODE` | For initial admin-panel setup | Shared secret required to create the separate admin-panel account at `/admin/signup`. Configure it before first admin setup and keep it private. |
| `DATABASE_URL` | No, local default | SQLAlchemy URL; defaults to `sqlite:///h3_automation.db`. PostgreSQL URLs are normalized to psycopg2 and get `sslmode=require` if absent. Production should use managed PostgreSQL. |
| `FERNET_KEY` | Needed to save encrypted credentials | Encryption key used for Kaggle and platform credentials. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep the same key for the lifetime of encrypted records. |
| `SESSION_COOKIE_SECURE` | No | Set `true` behind HTTPS in production. Defaults to `false` for local HTTP. Cookies are also HTTP-only and SameSite Lax. |
| `SUPABASE_URL` | Optional, configure as a set | Supabase project URL. |
| `SUPABASE_SERVICE_ROLE_KEY` | Optional, configure as a set | Server-only service role key for private Storage operations. Never expose it to browsers or users. |
| `SUPABASE_STORAGE_BUCKET` | Optional, configure as a set | Storage bucket name; defaults to `h3-videos`. Create the bucket as private. |
| `KAGGLE_USERNAME`, `KAGGLE_KEY`, `KAGGLE_KERNEL_ID` | No | Legacy environment-level Kaggle account, exposed only in the configured admin workspace. Regular users should add their own accounts in Settings. The three settings must be usable together. |
| `KAGGLE_ENABLE_GPU` | No | Whether Kaggle notebook pushes request a GPU; defaults to `true`. |
| `KAGGLE_GPU_TYPE` | No | Requested Kaggle accelerator; defaults to `T4`. Actual availability depends on Kaggle account and platform quotas. |
| `KAGGLE_MAX_CONCURRENT_ACCOUNTS` | No | Maximum in-process worker threads, clamped to 1–32; defaults to `8` (Render blueprint sets `4`). Same-kernel work is serialized. This is not a distributed queue or a cluster-wide lock. |
| `KAGGLE_CALLBACK_URL`, `KAGGLE_CALLBACK_TOKEN` | No, paired | Public base URL and shared bearer token for optional notebook progress callbacks. The job UUID is appended to the URL. Configure both; keep the token secret. |
| `GEMINI_API_KEY` | No | Admin-only environment fallback. Users can set their own API key in Settings. |
| `GEMINI_MODEL` | No | Gemini model used by prompt generation; defaults to `gemini-2.0-flash`. |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` | For YouTube integration | Operator's YouTube OAuth application configuration. Each user supplies their own refresh token in Settings. |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | For TikTok integration | Operator's TikTok application configuration. Each user supplies their own refresh token in Settings. |
| `HOST`, `PORT` | No | Local development bind address and port; defaults to `127.0.0.1` and `5000`. |
| `FLASK_DEBUG` | No | Enables Flask debug mode only when the value is `true`; keep false in production. |

Use a fresh random value for `FLASK_SECRET_KEY`, a unique admin password, and a valid Fernet key. Configure Supabase variables together. The old global TikTok refresh token and YouTube client-secrets-file flow are not used by the current per-user setup.
