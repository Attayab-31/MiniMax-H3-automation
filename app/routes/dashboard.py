from flask import Blueprint, render_template
from flask_login import login_required

from app.models import GenerationJob, Schedule


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    jobs = GenerationJob.query.order_by(
        GenerationJob.created_at.desc()).limit(10).all()
    upcoming_schedules = (
        Schedule.query.filter_by(enabled=True)
        .order_by(Schedule.time_of_day.asc())
        .limit(10)
        .all()
    )
    return render_template("dashboard.html", jobs=jobs, upcoming_schedules=upcoming_schedules)
