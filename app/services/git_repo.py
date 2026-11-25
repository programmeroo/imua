"""
app/services/git_repo.py

Bare git repo + worktree management for Imua's project hosting.

Layout on disk (relative to app root):
    data/repos/project.git/   — bare repo (agents push here)
    data/repos/project/       — non-bare worktree served at /project/

The bare repo is initialized idempotently on first startup. If empty,
a seed commit (index.html) is created so the deploy pipeline is
testable end-to-end on day one.

All subprocess calls use explicit absolute paths and a clean env
(we only need PATH, HOME, and a stable GIT_AUTHOR/COMMITTER for
the seed commit — no leakage of the Flask process env).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# --- Defaults (overridable per-app via app.config["GIT_REPO_DIR"]) ---

REPO_DIRNAME = "project"          # bare repo: data/repos/project.git
WORKTREE_DIRNAME = "project"      # checkout: data/repos/project/
SEED_AUTHOR_NAME = "Imua"
SEED_AUTHOR_EMAIL = "imua@localhost"
SEED_COMMIT_MESSAGE = "chore: seed initial Imua project site"
SEED_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Imua</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
    background: #f7f8fa;
    color: #0b0d11;
    line-height: 1.55;
  }
  main {
    max-width: 720px;
    margin: 0 auto;
    padding: 4rem 1.5rem;
  }
  h1 { font-size: 2.5rem; margin: 0 0 0.25rem; letter-spacing: -0.02em; }
  .tag { color: #5b6370; font-size: 1rem; margin: 0 0 2.5rem; }
  h2 { font-size: 1.1rem; margin: 2rem 0 0.5rem; }
  ul { padding-left: 1.25rem; }
  li { margin: 0.25rem 0; }
  footer {
    margin-top: 4rem;
    padding-top: 1.5rem;
    border-top: 1px solid #e5e7eb;
    color: #5b6370;
    font-size: 0.9rem;
  }
  code { background: #eef0f3; padding: 0.1rem 0.35rem; border-radius: 3px; }
  @media (prefers-color-scheme: dark) {
    body { background: #0b0d11; color: #f3f4f6; }
    code { background: #1f242c; }
    footer { border-top-color: #1f242c; }
  }
</style>
</head>
<body>
<main>
  <h1>Imua</h1>
  <p class="tag">LAN orchestration for AI agents.</p>

  <p>
    This site is served by the Imua hub. A bare git repo lives at
    <code>data/repos/project.git</code> &mdash; push to it and the
    new commit is auto-deployed to this URL.
  </p>

  <h2>What Imua does</h2>
  <ul>
    <li>Shared message bus between agents</li>
    <li>Encrypted secrets vault</li>
    <li>Knowledge base with semantic search</li>
    <li>Task queue and cron scheduler</li>
    <li>n8n workflow bridge</li>
    <li>Operator dashboard</li>
  </ul>

  <h2>How to deploy</h2>
  <p>
    Clone the bare repo, edit, commit, push. The post-receive hook
    checks out the new commit into the worktree &mdash; this page
    updates on the next refresh, no service restart needed.
  </p>

  <footer>
    Built on Imua. Replace this page with your own content via
    <code>git push</code>.
  </footer>
</main>
</body>
</html>
"""


class GitRepoError(RuntimeError):
    """Raised when a git operation fails."""


@dataclass
class ProjectStatus:
    """Snapshot of the deployed project's state."""

    branch: str
    last_commit: str          # short SHA
    last_commit_full: str     # full SHA
    last_commit_message: str
    last_commit_author: str
    last_commit_time: str     # ISO 8601
    worktree_path: str
    bare_path: str


# --- Internal helpers ------------------------------------------------------


def _clean_env() -> dict:
    """Return a minimal env for git subprocess calls.

    We strip most of the parent env so we don't leak Flask/SQLAlchemy
    vars into git, and we set a stable identity for the seed commit.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
        "GIT_AUTHOR_NAME": SEED_AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": SEED_AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": SEED_AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": SEED_AUTHOR_EMAIL,
        # Suppress interactive prompts in any environment that defines it
        "GIT_TERMINAL_PROMPT": "0",
    }
    # Pass through SYSTEMROOT on Windows for git-for-windows path resolution
    if os.name == "nt" and "SYSTEMROOT" in os.environ:
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


def _run(
    args: list[str],
    *,
    cwd: Optional[Path] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command and return CompletedProcess. Raise on failure."""
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=_clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise GitRepoError(
            f"git command failed: {' '.join(args)}\n"
            f"stdout: {proc.stdout.strip()}\n"
            f"stderr: {proc.stderr.strip()}"
        )
    return proc


def _git_version() -> tuple[int, ...]:
    """Return git version as a tuple like (2, 25, 1).

    Returns (0, 0, 0) if version parsing fails.
    """
    try:
        proc = subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True, check=True,
        )
        # stdout: "git version 2.25.1" or "git version 2.28.0.windows.1"
        parts = proc.stdout.strip().split()
        if len(parts) >= 3:
            raw = parts[2].split(".")[:3]
            return tuple(int(p) for p in raw)
    except Exception:
        pass
    return (0, 0, 0)


def _git_init(
    path: str | Path,
    *,
    bare: bool = False,
    branch: str = "main",
) -> None:
    """Initialize a git repo, setting the default branch to *branch*.

    Uses ``--initial-branch`` flag on git >= 2.28.0. Falls back to
    ``git symbolic-ref HEAD`` for older git versions (e.g. WSL's
    Ubuntu repos which ship with 2.25.x).
    """
    args = ["git", "init"]
    is_bare = bare

    ver = _git_version()
    if ver >= (2, 28, 0):
        args.append(f"--initial-branch={branch}")
    else:
        # Initialise with the default branch name, then rename via symbolic-ref
        pass  # handled below

    if is_bare:
        args.append("--bare")

    args.append(str(path))

    _run(args)

    if ver < (2, 28, 0):
        # Old git: set HEAD to the desired branch via plumbing
        if is_bare:
            _run(["git", "--git-dir", str(path), "symbolic-ref", "HEAD", f"refs/heads/{branch}"])
        else:
            _run(["git", "-C", str(path), "symbolic-ref", "HEAD", f"refs/heads/{branch}"])


# --- Public API ------------------------------------------------------------


def repo_paths(data_dir: str | Path) -> tuple[Path, Path]:
    """Return (bare_path, worktree_path) for the project repo."""
    base = Path(data_dir) / "repos"
    return base / f"{REPO_DIRNAME}.git", base / WORKTREE_DIRNAME


def init_repo(data_dir: str | Path) -> tuple[Path, Path]:
    """Initialize bare repo + worktree if not already present.

    Idempotent: safe to call on every app startup. If the bare repo
    is freshly created (or empty), seed it with an initial commit so
    the deploy pipeline is testable immediately.

    Returns (bare_path, worktree_path) regardless of whether init
    actually happened.
    """
    bare, worktree = repo_paths(data_dir)
    bare.parent.mkdir(parents=True, exist_ok=True)

    if not bare.exists():
        _git_init(bare, bare=True, branch="main")

    is_empty = _run(
        ["git", "--git-dir", str(bare), "rev-parse", "--verify", "HEAD"],
        check=False,
    ).returncode != 0

    if is_empty:
        _seed_initial_commit(bare, worktree)

    # Ensure the worktree is in a deployable state on every init.
    # This is a no-op on a re-init where the worktree already exists.
    worktree.mkdir(parents=True, exist_ok=True)
    deploy(bare, worktree)

    return bare, worktree


def _seed_initial_commit(bare: Path, worktree: Path) -> None:
    """Create the initial commit in the bare repo with a seed index.html.

    Strategy: create a temp dir, init a regular repo, write index.html,
    commit, then push to the bare repo. Avoids wrestling with bare-repo
    worktrees or plumbing commands.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="imua-seed-") as tmp:
        tmp_path = Path(tmp)
        _git_init(tmp_path, bare=False, branch="main")
        # Set local identity (overrides env for this repo only)
        _run(["git", "-C", str(tmp_path), "config", "user.name", SEED_AUTHOR_NAME])
        _run(["git", "-C", str(tmp_path), "config", "user.email", SEED_AUTHOR_EMAIL])

        (tmp_path / "index.html").write_text(SEED_INDEX_HTML, encoding="utf-8")
        _run(["git", "-C", str(tmp_path), "add", "index.html"])
        _run(["git", "-C", str(tmp_path), "commit", "-m", SEED_COMMIT_MESSAGE])
        _run(["git", "-C", str(tmp_path), "push", str(bare), "main:main"])


def deploy(bare: Path, worktree: Path) -> None:
    """Checkout HEAD of bare repo into the worktree.

    This is what the post-receive hook calls. Idempotent: re-running
    it on the same commit is a no-op. Uses --force so a force-push
    is reflected in the deployed site.
    """
    worktree.parent.mkdir(parents=True, exist_ok=True)

    if not (worktree / ".git").exists():
        # First deploy: clone the bare repo into the worktree
        if worktree.exists() and any(worktree.iterdir()):
            # Defensive: worktree dir exists but is not a clone. Wipe it.
            shutil.rmtree(worktree)
        _run([
            "git", "clone", "--shared", "--branch", "main",
            str(bare), str(worktree),
        ])
    else:
        # Subsequent deploys: fetch + reset hard.
        # We use `fetch <bare> main` (not `main:main`) because you
        # cannot fetch into a branch that's currently checked out
        # in the worktree. FETCH_HEAD gives us the new tip.
        _run(["git", "-C", str(worktree), "fetch", str(bare), "main"])
        _run(["git", "-C", str(worktree), "reset", "--hard", "FETCH_HEAD"])


def get_status(bare: Path, worktree: Path) -> ProjectStatus:
    """Return a ProjectStatus snapshot of the current deployed state."""
    fmt = "%H%n%h%n%s%n%an <%ae>%n%aI"  # full, short, subject, author, iso
    proc = _run([
        "git", "--git-dir", str(bare), "log", "-1", f"--format={fmt}",
    ], check=False)

    if proc.returncode != 0 or not proc.stdout.strip():
        raise GitRepoError(f"cannot read HEAD of {bare}: {proc.stderr.strip()}")

    lines = proc.stdout.rstrip("\n").split("\n")
    full, short, subject, author, iso = lines[0], lines[1], lines[2], lines[3], lines[4]

    # Branch detection: HEAD of a freshly-cloned bare points to refs/heads/main
    branch_proc = _run([
        "git", "--git-dir", str(bare), "symbolic-ref", "--short", "HEAD",
    ], check=False)
    branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else "main"

    return ProjectStatus(
        branch=branch,
        last_commit=short,
        last_commit_full=full,
        last_commit_message=subject,
        last_commit_author=author,
        last_commit_time=iso,
        worktree_path=str(worktree),
        bare_path=str(bare),
    )
