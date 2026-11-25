"""
Imua — Flask application entry point.

Creates the Flask app, loads config, registers blueprints,
and initializes the database.
"""

import os
import shutil
import socket
import secrets
import sys
import yaml
from flask import Flask, request, current_app
from flask_socketio import SocketIO, join_room

# Ensure the repo root is on sys.path so `python app/server.py` works
# the same way `flask run` does. Without this, running the script
# directly makes sys.path[0] == <repo>/app/ and imports of `app.*`
# from inside server.py itself fail with ModuleNotFoundError.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

socketio = SocketIO()


def _install_post_receive_hook(bare_repo_path) -> None:
    """Copy scripts/post-receive into the bare repo's hooks/ dir.

    Idempotent. Runs on every app startup. We re-copy on each boot
    so a developer editing the script in the repo gets the new hook
    on restart without a manual copy step.
    """
    bare_repo = bare_repo_path if isinstance(bare_repo_path, str) else str(bare_repo_path)
    source = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "post-receive",
    )
    dest = os.path.join(bare_repo, "hooks", "post-receive")
    if not os.path.exists(source):
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(source, dest)
    os.chmod(dest, 0o755)


def _detect_lan_ip() -> str:
    """Best-effort detection of this machine's LAN-facing IP.

    Browsers report location.hostname as whatever the operator typed
    (often "localhost"), which other machines on the LAN can't use to
    reach the hub. Opening a UDP socket to a public address (no packets
    actually sent — UDP connect() just picks the outbound interface)
    and reading the socket's own bound address gets the real LAN IP.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _key_path(app: Flask, filename: str) -> str:
    """Key files live next to the SQLite database, so they persist wherever the
    data does (on HUB-1: the bind-mounted data/ folder, which survives rebuilds)."""
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    db_path = uri[len("sqlite:///"):] if uri.startswith("sqlite:///") else ""
    if not db_path or db_path == ":memory:":
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "data", "database", "imua.db")
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), filename)


def _vault_key_path(app: Flask) -> str:
    return _key_path(app, "vault.key")


def _load_or_create_key(path: str, generate, label: str) -> str:
    """Return the key persisted at `path`, generating it (mode 600) on first run.

    Refuses to start on an empty key file: silently replacing a lost/truncated key
    would orphan whatever it protects, so that must be a deliberate decision."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path) as f:
            key = f.read().strip()
        if not key:
            raise RuntimeError(
                f"Imua {label} file {path} is empty. Restore it from backup, or delete it "
                "to generate a new one.")
        return key
    key = generate()
    with os.fdopen(fd, "w") as f:
        f.write(key)
    print(f"Imua: generated new {label} at {path} — back it up with the database.",
          file=sys.stderr, flush=True)
    return key


def _load_or_create_vault_key(path: str) -> str:
    """Vault master key. Losing it makes every stored secret unreadable."""
    from cryptography.fernet import Fernet
    return _load_or_create_key(path, lambda: Fernet.generate_key().decode(), "vault key")


def create_app(config_path: str | None = None) -> Flask:
    """Application factory — creates and configures a Flask instance."""
    app = Flask(__name__)

    # --- Default config ---
    _root = os.path.dirname(os.path.abspath(__file__))
    _default_db = os.path.join(os.path.dirname(_root), "data", "database", "imua.db")
    app.config["SECRET_KEY"] = ""  # resolved after config/env overrides (see below)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{_default_db}"
    app.config["DOCS_STORAGE_DIR"] = os.path.join(os.path.dirname(_root), "data", "docs")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["DEBUG"] = True
    app.config["HOST"] = "0.0.0.0"
    app.config["PORT"] = 47280
    app.config["VERSION"] = "0.1.0"
    app.config["VAULT_KEY"] = ""  # resolved after config/env overrides (see below)
    app.config["OPERATOR_KEY"] = ""  # the operator's own vault-bypass credential; empty disables it
    app.config["OPERATOR_KEY_ENABLED"] = True  # auth.operator_key_enabled: false turns it off everywhere
    app.config["HEARTBEAT_TIMEOUT"] = 120  # seconds before an agent is reported offline
    app.config["ADVERTISE_HOST"] = _detect_lan_ip()  # IP other LAN machines should use

    # --- Load config file ---
    config_path = config_path or os.environ.get(
        "IMUA_CONFIG", "config/config.yaml"
    )
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        app_cfg = cfg.get("app", {})
        db_cfg = cfg.get("database", {})
        agents_cfg = cfg.get("agents", {})
        if "debug" in app_cfg:
            app.config["DEBUG"] = app_cfg["debug"]
        if "secret_key" in app_cfg and app_cfg["secret_key"] != "CHANGE_ME_TO_A_RANDOM_STRING":
            app.config["SECRET_KEY"] = app_cfg["secret_key"]
        if "port" in app_cfg:
            app.config["PORT"] = app_cfg["port"]
        if "version" in app_cfg:
            app.config["VERSION"] = app_cfg["version"]
        if "host" in app_cfg:
            app.config["HOST"] = app_cfg["host"]
        if app_cfg.get("vault_key"):
            app.config["VAULT_KEY"] = app_cfg["vault_key"]
        if app_cfg.get("operator_key"):
            app.config["OPERATOR_KEY"] = app_cfg["operator_key"]
        if "operator_key_enabled" in cfg.get("auth", {}):
            app.config["OPERATOR_KEY_ENABLED"] = bool(cfg["auth"]["operator_key_enabled"])
        if "path" in db_cfg:
            app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_cfg['path']}"
        if "heartbeat_timeout" in agents_cfg:
            app.config["HEARTBEAT_TIMEOUT"] = agents_cfg["heartbeat_timeout"]
        if app_cfg.get("advertise_host"):
            app.config["ADVERTISE_HOST"] = app_cfg["advertise_host"]

    # --- Env overrides ---
    if os.environ.get("IMUA_SECRET_KEY"):
        app.config["SECRET_KEY"] = os.environ["IMUA_SECRET_KEY"]
    if os.environ.get("IMUA_DEBUG"):
        app.config["DEBUG"] = os.environ["IMUA_DEBUG"].lower() == "true"
    if os.environ.get("IMUA_PORT"):
        app.config["PORT"] = int(os.environ["IMUA_PORT"])
    if os.environ.get("IMUA_VAULT_KEY"):
        app.config["VAULT_KEY"] = os.environ["IMUA_VAULT_KEY"]
    if os.environ.get("IMUA_OPERATOR_KEY"):
        app.config["OPERATOR_KEY"] = os.environ["IMUA_OPERATOR_KEY"]
    if os.environ.get("IMUA_OPERATOR_KEY_ENABLED"):
        app.config["OPERATOR_KEY_ENABLED"] = os.environ["IMUA_OPERATOR_KEY_ENABLED"].lower() == "true"

    # --- Vault master key: config/env win; otherwise persisted in data/ ---
    # (Was a fresh random key per start, which made every secret unreadable after a
    # restart.) Tests get an ephemeral key so they never write into data/.
    if not app.config["VAULT_KEY"]:
        if os.environ.get("IMUA_TESTING"):
            app.config["VAULT_KEY"] = os.urandom(32).hex()
        else:
            app.config["VAULT_KEY"] = _load_or_create_vault_key(_vault_key_path(app))

    # --- Session signing key: config/env win; otherwise persisted in data/ ---
    # A fresh random key per start would sign every admin out on each restart.
    if not app.config["SECRET_KEY"]:
        if os.environ.get("IMUA_TESTING"):
            app.config["SECRET_KEY"] = os.urandom(32).hex()
        else:
            app.config["SECRET_KEY"] = _load_or_create_key(
                _key_path(app, "session.key"), lambda: secrets.token_hex(32), "session key")

    # --- Initialize database ---
    from app.models import init_db
    init_db(app)

    # --- Admin sign-in sessions (cookie flags, timeouts) ---
    from app.services import admin_session
    admin_session.configure(app)
    from app.services import csrf
    csrf.init_app(app)
    from app.services import audit
    audit.init_app(app)  # records every admin write (task 5.6)

    # --- Register blueprints ---
    from app.routes.auth import auth_bp
    app.register_blueprint(auth_bp)
    from app.routes.audit import audit_bp
    app.register_blueprint(audit_bp)
    from app.routes.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)
    from app.routes.agents import agents_bp
    app.register_blueprint(agents_bp)
    from app.routes.messages import messages_bp
    app.register_blueprint(messages_bp)
    from app.routes.secrets import secrets_bp
    app.register_blueprint(secrets_bp)
    from app.routes.project import project_bp
    app.register_blueprint(project_bp)
    from app.routes.projects import projects_bp
    app.register_blueprint(projects_bp)
    from app.routes.tasks import tasks_bp
    app.register_blueprint(tasks_bp)
    from app.routes.cron import cron_bp
    app.register_blueprint(cron_bp)
    from app.routes.settings import settings_bp
    app.register_blueprint(settings_bp)
    from app.routes.documents import documents_bp
    app.register_blueprint(documents_bp)
    from app.routes.knowledge import knowledge_bp
    app.register_blueprint(knowledge_bp)
    from app.routes.issues import issues_bp
    app.register_blueprint(issues_bp)

    # --- Initialize ChromaDB-backed knowledge base (vector store) ---
    if not os.environ.get("IMUA_TESTING"):
        try:
            from app.services import knowledge_base as kb
            kb.init_knowledge_base(app)
        except Exception as exc:
            app.logger.warning("knowledge base init failed: %s", exc)

    # --- Initialize git project repo (bare + worktree + seed) ---
    # Idempotent; safe to run on every startup. If the bare repo is
    # already populated, this is a no-op.
    # Skip entirely in tests (set IMUA_TESTING=1) — tests will init
    # the repo into a tmp dir explicitly via git_repo.init_repo().
    from app.services import git_repo
    _data_dir = os.path.join(os.path.dirname(_root), "data")
    if not os.environ.get("IMUA_TESTING"):
        try:
            bare, worktree = git_repo.init_repo(_data_dir)
            # Ensure the deployed worktree matches HEAD on first startup
            # (no-op if the hook or a prior deploy already did it)
            git_repo.deploy(bare, worktree)
            app.config["PROJECT_BARE_PATH"] = str(bare)
            app.config["PROJECT_WORKTREE_PATH"] = str(worktree)
        except git_repo.GitRepoError as exc:
            # Don't kill the app if git isn't available yet — log and let
            # the operator fix it. Status endpoint will report the error.
            app.logger.warning("project repo init failed: %s", exc)

    # --- Install post-receive hook into the bare repo ---
    # The hook lives at scripts/post-receive in the repo. We copy it
    # into the bare repo's hooks/ directory on startup so a fresh
    # clone (or a wiped data/ dir) gets the hook for free.
    if not os.environ.get("IMUA_TESTING") and "bare" in dir():
        _install_post_receive_hook(bare)

    # --- Health endpoint ---
    @app.route("/api/health")
    def health():
        hub_url = f"http://{app.config['ADVERTISE_HOST']}:{app.config['PORT']}"
        return {"status": "ok", "version": app.config.get("VERSION", "0.1.0"), "hub_url": hub_url}

    # --- Template context: version shown in the sidebar (base.html) ---
    @app.context_processor
    def inject_version():
        return {"version": app.config.get("VERSION", "0.1.0"),
                "current_admin": admin_session.current_admin()}

    # --- Init SocketIO ---
    socketio.init_app(app, cors_allowed_origins="*")

    # --- WebSocket events ---
    @socketio.on("connect")
    def on_ws_connect(auth):
        agent_name = request.args.get("agent_name")
        if agent_name:
            join_room(f"agent_{agent_name}")
            current_app.logger.info("WS connected: %s", agent_name)

    @socketio.on("disconnect")
    def on_ws_disconnect():
        current_app.logger.info("WS disconnected")

    return app


def run_dev(app: Flask | None = None) -> None:
    """Run the dev server (for use with `python app/server.py`)."""
    app = app or create_app()
    socketio.run(
        app,
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config["DEBUG"],
        allow_unsafe_werkzeug=True,
    )


# Convenience reference for `gunicorn app.server:app`
app = create_app()

if __name__ == "__main__":
    run_dev()
