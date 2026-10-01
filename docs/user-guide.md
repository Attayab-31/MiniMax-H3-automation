# User guide

## Accounts and workspace isolation

Choose **Create an account** to register a regular workspace user, then sign in. The first workspace migration also creates the initial workspace user from the configured `ADMIN_USERNAME` and `ADMIN_PASSWORD`. Separately, the operator creates the admin-panel account once at `/admin/signup` using `ADMIN_CODE`; that account can manage users from the admin panel.

Your jobs, schedules, Kaggle accounts, and platform credentials belong to your user record. The dashboard, job detail pages, video library, and settings only show the signed-in user's records. Use **Settings** to add or remove credentials. A Kaggle account includes a display label, Kaggle username, API key, and notebook kernel ID. Add multiple Kaggle accounts to distribute separate jobs across their kernels. A given account's kernel work is serialized.

Gemini is optional. Add a Gemini API key in settings for AI-generated prompts and publishing metadata. If no key is configured, the app uses its deterministic prompt/metadata fallback. Platform developer credentials are configured by the operator; users add their own platform tokens in settings.

## Create a video

Open **Generate** and provide a niche, style notes, and creative brief. Select an enabled Kaggle account, video dimensions/preset, duration, clip length, generation options, and any connected publishing platforms. The job captures its prompt, generation parameters, selected platforms, and owner when submitted. You can follow its state on the job page and see logs and output metadata there.

If an operation fails, inspect the error on the job page. A completed Kaggle run can retry output download, and a job with a generated video can retry publishing without regenerating the video. Deleting a job or video is a destructive workspace action; it removes the selected record and its stored artifact where supported.

## Schedules

Create a schedule with a name, niche, style notes, creative brief, Kaggle account, local time, IANA timezone (for example `America/Los_Angeles`), video settings, and optional platforms. Enabled schedules create a job daily at the chosen time. Update or disable schedules from the schedules page. Scheduled jobs retain the same owner and use the settings captured when the job is created.

The scheduler runs inside the web process. It needs the process to stay awake and running; a free or sleeping web service is not a dependable unattended scheduler. See [Operations](operations.md).

## Videos and publishing

Use **Videos** to browse your completed artifacts. With Supabase Storage configured, video files are held in a private bucket and accessed through short-lived signed URLs. Without it, the app may use local runtime storage, which is not durable on ephemeral hosting. YouTube uploads are private by default. TikTok publishing uses self-only visibility in this implementation. Confirm platform permissions, account access, and content before enabling publishing.

## Account access

Sign out on shared devices. Passwords are hashed before storage, and credential values are encrypted using the configured Fernet key. If that key is lost, stored encrypted credentials cannot be decrypted; preserve it securely and include it in your secret backup process.
