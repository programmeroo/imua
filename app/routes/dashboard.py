"""
Dashboard route — serves the main operator interface.
"""

from flask import Blueprint, render_template

dashboard_bp = Blueprint(
    "dashboard", __name__,
    template_folder="../templates",
    static_folder="../static",
    static_url_path="/static",
)


@dashboard_bp.route("/")
def index():
    """Render the main dashboard page."""
    return render_template("dashboard.html", title="Imua · Dashboard")


@dashboard_bp.route("/agents")
def agents_page():
    """Render the agents page — roster + invite-a-new-agent panel."""
    return render_template("agents.html", title="Imua · Agents")
