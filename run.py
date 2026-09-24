import os

from app import create_app
from flask_migrate import upgrade

app = create_app()

if __name__ == "__main__":
    # `python run.py` is the local startup path. Bring the configured database
    # up to the current Alembic revision before the first request can start the
    # scheduler, which queries the schedules table.
    with app.app_context():
        upgrade()

    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
    )
