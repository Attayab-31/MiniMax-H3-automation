import atexit
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

load_dotenv()


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
csrf = CSRFProtect()


def create_app() -> Flask:
    app = Flask(__name__)
    secret_key = os.getenv("FLASK_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("FLASK_SECRET_KEY must be configured before starting the application.")
    app.config["SECRET_KEY"] = secret_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    database_url = os.getenv("DATABASE_URL", "sqlite:///h3_automation.db").strip()
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://") and "sslmode=" not in database_url:
        database_url += "&sslmode=require" if "?" in database_url else "?sslmode=require"
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    # Each Kaggle account has an independent kernel; same-account jobs are serialized.
    max_workers = max(1, min(32, int(os.getenv("KAGGLE_MAX_CONCURRENT_ACCOUNTS", "8"))))
    app.config["EXECUTOR"] = ThreadPoolExecutor(max_workers=max_workers)
    atexit.register(app.config["EXECUTOR"].shutdown, wait=False)
    app.config["FERNET_KEY"] = os.getenv("FERNET_KEY", "")
    app.config["KAGGLE_CALLBACK_URL"] = os.getenv("KAGGLE_CALLBACK_URL", "").strip()
    app.config["KAGGLE_CALLBACK_TOKEN"] = os.getenv("KAGGLE_CALLBACK_TOKEN", "").strip()
    app.config["SUPABASE_URL"] = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    app.config["SUPABASE_SERVICE_ROLE_KEY"] = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    app.config["SUPABASE_STORAGE_BUCKET"] = os.getenv("SUPABASE_STORAGE_BUCKET", "h3-videos").strip()

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)

    from app.models import GenerationJob, KaggleAccount, PlatformCredential, Schedule

    # Start the scheduler on the first web request, after deployment migrations
    # have run. It remains in-process and therefore needs one Gunicorn worker.
    scheduler_lock = threading.Lock()
    app.extensions["scheduler_lock"] = scheduler_lock

    @app.before_request
    def start_scheduler_once():
        if app.extensions.get("scheduler_started"):
            return
        with scheduler_lock:
            if not app.extensions.get("scheduler_started"):
                from app.scheduler import init_scheduler
                init_scheduler(app)
                app.extensions["scheduler_started"] = True

    from app.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.generate import generate_bp
    from app.routes.jobs import jobs_bp
    from app.routes.schedules import schedules_bp
    from app.routes.settings import settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(settings_bp)

    @app.route("/health")
    def health():
        db.session.execute(db.select(1))
        return {"status": "ok"}

    return app
