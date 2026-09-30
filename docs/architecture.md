# Architecture

## System overview

The web application stores workspace data and coordinates generation. Kaggle runs the GPU workload in an isolated notebook. The service retrieves the notebook output, stores the video, and optionally publishes it through the user's connected platform accounts.

```mermaid
flowchart LR
    Browser[User browser]
    Flask[Flask web app]
    DB[(PostgreSQL or local SQLite)]
    Pool[In-process executor]
    Scheduler[APScheduler]
    Kaggle[Kaggle API and GPU notebook]
    Gemini[Gemini API]
    Storage[(Private Supabase Storage)]
    YouTube[YouTube Data API]
    TikTok[TikTok Content Posting API]

    Browser -->|HTTP and session cookie| Flask
    Flask <--> DB
    Flask --> Pool
    Scheduler --> DB
    Scheduler --> Pool
    Pool --> Kaggle
    Pool --> Gemini
    Kaggle -->|manifest, video, logs| Pool
    Pool --> Storage
    Pool --> YouTube
    Pool --> TikTok
    Flask -->|signed video URL| Browser
```

The app does not proxy all video bytes through Flask when Supabase is configured. It checks ownership, creates a short-lived signed URL, and redirects the browser to private storage.

## Generation lifecycle

```mermaid
sequenceDiagram
    actor User
    participant Web as Flask route
    participant DB as Database
    participant Worker as ThreadPoolExecutor
    participant Kaggle
    participant Storage as Supabase Storage
    participant Platform as User's YouTube/TikTok account

    User->>Web: Submit prompt, GPU account, options
    Web->>DB: Save owner-scoped job
    Web->>Worker: Queue job ID
    Worker->>DB: Load job and owner credentials
    Worker->>Kaggle: Push clean notebook with job parameters
    loop Until Kaggle completes or fails
        Worker->>Kaggle: Poll kernel status
        Kaggle-->>Web: Optional signed progress callback
    end
    Worker->>Kaggle: Download manifest and final video
    Worker->>Storage: Upload video to jobs/{job UUID}/...
    opt User selected connected platform(s)
        Worker->>Platform: Publish using owner-scoped token
    end
    Worker->>DB: Save final status and metadata
    User->>Web: Open job or video library
    Web->>DB: Query only current user's rows
    Web-->>User: Details and short-lived video URL
```

Job statuses are `queued`, `pushing`, `running`, `downloading`, `posting`, `completed`, and `failed`. A failed publish can leave a generated video attached to a failed job; retry posting uses that video without rerunning H3. A completed Kaggle run can also retry only its output download.

## Workspace data model

```mermaid
erDiagram
    USER ||--o{ KAGGLE_ACCOUNT : owns
    USER ||--o{ SCHEDULE : owns
    USER ||--o{ GENERATION_JOB : owns
    USER ||--o{ PLATFORM_CREDENTIAL : owns
    SCHEDULE o|--o{ GENERATION_JOB : creates
    KAGGLE_ACCOUNT o|--o{ SCHEDULE : selected_by
    KAGGLE_ACCOUNT o|--o{ GENERATION_JOB : runs

    USER {
        int id PK
        string username UK
        string password_hash
    }
    KAGGLE_ACCOUNT {
        int id PK
        int user_id FK
        string label
        string username
        string api_key_encrypted
        string kernel_id
    }
    SCHEDULE {
        int id PK
        int user_id FK
        string name
        string niche
        text style_notes
        json creative_brief
        json target_platforms
    }
    GENERATION_JOB {
        int id PK
        int user_id FK
        string job_id UK
        text prompt_text
        json generation_params
        string status
        string video_storage_path
    }
    PLATFORM_CREDENTIAL {
        int id PK
        int user_id FK
        string platform
        string account_label
        text encrypted_tokens
    }
```

Every browser-facing query for jobs, schedules, Kaggle accounts, and provider credentials filters by `current_user.id`. A job stores both its owner and its selected Kaggle account. Provider clients receive the job owner ID and use it to select Gemini, YouTube, or TikTok credentials. Foreign keys and per-workspace uniqueness constraints back up those checks.

The prompt is stored with its generation job. A schedule stores the reusable niche, style notes, creative brief, timing, and video settings from which it creates future jobs. There is no separate prompt-template library.

## Component responsibilities

| Component | Responsibility |
| --- | --- |
| `app/__init__.py` | Flask application factory, extensions, database configuration, and blueprint registration |
| `app/auth.py` | Signup, login, logout, and Flask-Login user loading |
| `app/routes/` | Authenticated UI and user-scoped data operations |
| `app/models.py` | Database schema and relationships |
| `app/pipeline.py` | Generation, resume, output download, retries, and publishing |
| `app/kaggle_client.py` | Kaggle client setup, parameter file, notebook copy, push, poll, and artifact download |
| `app/scheduler.py` | In-process schedule registration and scheduled job creation |
| `app/storage.py` | Supabase Storage REST operations and signed URLs |
| `app/llm_client.py` | User-keyed Gemini prompting and deterministic fallbacks |
| `app/youtube_client.py`, `app/tiktok_client.py` | User-keyed publishing and token refresh |
| `notebook/*.ipynb` | Kaggle GPU workload source; exactly one `.ipynb` is expected |

## HTTP surface

| Route | Purpose |
| --- | --- |
| `GET/POST /signup`, `GET/POST /login`, `POST /logout` | User authentication |
| `GET /`, `GET/POST /generate` | Owner dashboard and manual job creation |
| `GET /jobs/<id>`, `/api/jobs/<id>` | Job detail and polling API |
| `GET /jobs/<id>/video`, `/download` | Owner-checked video access |
| `GET /videos` | Owner-scoped video library |
| `POST /jobs/<id>/delete-*`, `/retry-*` | Owner-checked job actions |
| `GET/POST /schedules`, `/schedules/<id>` | Owner-scoped recurring schedules |
| `GET/POST /settings` and credential actions | User's Kaggle and provider setup |
| `POST /api/kaggle/progress/<job UUID>` | Notebook callback authenticated by shared callback token |
| `GET /health` | Database connectivity probe |

## Storage and local runtime

The database is the source of truth for owners, prompts, statuses, and manifests. The private Supabase bucket stores durable videos when configured. Temporary notebook copies, parameter JSON, and downloaded outputs are under ignored `runtime/` directories. On ephemeral hosts, those local files disappear on restarts; the database and Supabase bucket persist independently.
