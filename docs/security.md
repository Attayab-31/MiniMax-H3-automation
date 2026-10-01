# Security model and limitations

## Workspace ownership

Passwords are stored as Werkzeug password hashes. Authenticated views scope jobs, schedules, Kaggle accounts, and platform credentials to the current user. Routes that act on a row should query by both its identifier and the current user's ID. Jobs retain their owner so provider clients can select that user's credentials. Database foreign keys cascade user-owned data where configured.

User signup is open to anyone who can reach the application. The code does not currently implement email verification, password reset, account recovery, or configurable invitations. A separate admin-panel account is created using the operator-configured `ADMIN_CODE`, and admin routes check for that account type. Protect a public deployment accordingly, keep the setup code private, and monitor account creation.

## Secrets and sessions

`FLASK_SECRET_KEY` signs sessions. Cookies are HTTP-only and SameSite Lax; set `SESSION_COOKIE_SECURE=true` behind HTTPS. Provider refresh tokens and Kaggle API keys are encrypted at rest using `FERNET_KEY`. Environment fallback credentials are available only in the designated admin workspace. Supabase's service role key is server-side and must never be sent to the browser.

Do not commit `.env`, database dumps, API keys, or tokens. If a secret has been exposed, revoke it at its provider and replace it in the hosting configuration. Fernet key replacement requires re-encryption of stored rows.

## Request protections and integrations

Flask-WTF CSRF protection is enabled for form posts. The notebook progress callback is exempt from browser CSRF and uses a shared configured token; treat it as a secret and use HTTPS. The callback token authorizes progress updates for the submitted job UUID, so keep the endpoint URL and token restricted.

Video objects use a private Supabase bucket and short-lived signed URLs. YouTube uploads are private by default; TikTok posts use self-only visibility. These defaults limit audience exposure but do not replace provider-side access controls.

## Deployment boundaries

The service role key can read and write the configured storage bucket, and provider tokens can act on connected user accounts. Limit dashboard access, use least-privilege provider scopes where available, keep logs free of secrets, and restrict access to backups. The app's in-process worker and scheduler are designed for a single web process; they do not provide distributed locking or durable queue guarantees.
