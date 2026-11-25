"""
app/routes/project.py

HTTP endpoints for Imua's project repo (git integration & auto-deploy).

Endpoints (per spec §3.8, §4.1):
    GET  /api/project/status   — branch, last commit, build status
    POST /api/project/deploy   — manual deploy trigger
    GET  /project/             — static serving of the deployed worktree
    GET  /project/<path>       — files inside the worktree
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, send_from_directory, abort

from app.services import git_repo

log = logging.getLogger(__name__)

project_bp = Blueprint(
    "project", __name__,
)


def _data_dir() -> Path:
    """Return the runtime data dir (parent of the SQLite DB)."""
    db_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///") and not db_uri.startswith("sqlite:///:memory:"):
        db_path = Path(db_uri.replace("sqlite:///", "", 1)).resolve()
        return db_path.parent.parent
    # Fallback: relative to app root
    return Path(current_app.root_path).parent / "data"


@project_bp.get("/api/project/status")
def project_status() -> Any:
    """Return current branch + last commit info for the deployed project."""
    bare, worktree = git_repo.repo_paths(_data_dir())

    if not bare.exists():
        return jsonify({
            "status": "not_initialized",
            "message": "Project repo has not been initialized yet.",
            "bare_path": str(bare),
            "worktree_path": str(worktree),
        }), 200

    try:
        s = git_repo.get_status(bare, worktree)
    except git_repo.GitRepoError as e:
        log.exception("project status failed")
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({
        "status": "ok",
        "branch": s.branch,
        "last_commit": s.last_commit,
        "last_commit_full": s.last_commit_full,
        "last_commit_message": s.last_commit_message,
        "last_commit_author": s.last_commit_author,
        "last_commit_time": s.last_commit_time,
        "worktree_path": s.worktree_path,
        "bare_path": s.bare_path,
    })


@project_bp.post("/api/project/deploy")
def project_deploy() -> Any:
    """Trigger a manual deploy — re-checks out HEAD into the worktree.

    Normally the post-receive hook does this automatically. This endpoint
    exists for operator use (e.g., re-deploy after manual repo repair).
    """
    bare, worktree = git_repo.repo_paths(_data_dir())

    if not bare.exists():
        return jsonify({
            "status": "not_initialized",
            "message": "Nothing to deploy — repo not initialized.",
        }), 404

    try:
        git_repo.deploy(bare, worktree)
        s = git_repo.get_status(bare, worktree)
    except git_repo.GitRepoError as e:
        log.exception("manual deploy failed")
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({
        "status": "deployed",
        "branch": s.branch,
        "last_commit": s.last_commit,
        "last_commit_message": s.last_commit_message,
    })


@project_bp.get("/project/")
@project_bp.get("/project/<path:filename>")
def project_static(filename: str = "index.html") -> Any:
    """Serve static files from the deployed worktree.

    Files outside the worktree (path traversal) are rejected.
    """
    _, worktree = git_repo.repo_paths(_data_dir())

    if not worktree.exists() or not (worktree / filename).is_file():
        abort(404)

    # Defense in depth: confirm resolved path stays inside worktree
    target = (worktree / filename).resolve()
    if not str(target).startswith(str(worktree.resolve())):
        abort(404)

    return send_from_directory(str(worktree), filename)
