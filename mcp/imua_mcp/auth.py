"""Token file loader — mode-600 enforced, rotation-aware, never-leak discipline.

Security properties (per ~/.hermes/skills/devops/imua-token-handling Rule 8
and docs/imua_mcp_server_specification_v1.md §2.3):

- Token source: a path to a mode-600 (or 400) file, passed as --token-file.
- Token value never appears in:
    - command-line arguments (path only, not content)
    - environment variables
    - log lines, error messages, __repr__, __str__
- Token is re-read from disk on each call (mtime check, throttled to
  once per _MIN_MTIME_REFRESH_MS) so scripts/join.py --rotate takes effect
  on the next MCP call without restarting Hermes.
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path


class TokenFileError(Exception):
    """Raised when the token file is missing, has wrong permissions, or unreadable.

    Messages are operator-facing diagnostics only — they MUST NOT contain any
    portion of the token value. Safe to log to stderr.
    """


class TokenFile:
    """Reads a bearer token from a mode-600 file. Supports rotation via mtime.

    Usage:
        tf = TokenFile('~/.hermes/SLK.token')
        token = tf.read()  # returns current token; refreshes if file changed

    Errors raised at construction time fail loud and early (server exits 1
    before binding stdio). Subsequent read() failures raise TokenFileError
    with a path-only message.
    """

    # Token shape: 64 lowercase hex chars (matches Imua's secrets.token_hex(32))
    _EXPECTED_TOKEN_LEN = 64

    # Throttle mtime checks to avoid syscall spam on every tool call
    _MIN_MTIME_REFRESH_MS = 100

    _ACCEPTED_MODES = (0o600, 0o400)

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(os.path.expanduser(str(path))).resolve()
        self._cached_token: str | None = None
        self._cached_mtime_ns: int | None = None
        self._last_check_ms: float = 0.0
        # Fail loud at construction; do not start the server with a bad file
        self._validate_file()

    def _validate_file(self) -> None:
        """Check the file exists, is a regular file, and has an accepted mode.

        Raises TokenFileError with a path-only message on any failure.
        """
        if not self._path.exists():
            raise TokenFileError(f"token file not found: {self._path}")
        if not self._path.is_file():
            raise TokenFileError(f"token path is not a regular file: {self._path}")
        if os.name == "nt":
            # Windows has no POSIX permission bits — os.chmod can't produce
            # a real 0600, so os.stat always reports back something outside
            # _ACCEPTED_MODES regardless of intent. Enforcing this check
            # there would make the server permanently unstartable rather
            # than more secure; rely on NTFS ACLs / the user's own account
            # isolation instead.
            return
        try:
            mode = stat.S_IMODE(self._path.stat().st_mode)
        except OSError as e:
            raise TokenFileError(f"cannot stat token file: {self._path}") from e
        if mode not in self._ACCEPTED_MODES:
            expected = "/".join(oct(m) for m in self._ACCEPTED_MODES)
            raise TokenFileError(
                f"token file mode {oct(mode)} is not in {expected}; "
                f"run: chmod 600 {self._path}"
            )

    def read(self) -> str:
        """Return the current token value, refreshing from disk if file changed.

        Throttles mtime checks to once per _MIN_MTIME_REFRESH_MS.
        """
        now_ms = time.monotonic() * 1000.0
        cache_stale = (
            self._cached_token is None
            or self._cached_mtime_ns is None
            or (now_ms - self._last_check_ms) >= self._MIN_MTIME_REFRESH_MS
        )
        if cache_stale:
            self._refresh()
            self._last_check_ms = now_ms
        assert self._cached_token is not None
        return self._cached_token

    def _refresh(self) -> None:
        """Re-read token from disk and validate format.

        Token format: 64 lowercase hex chars. We never log the content.
        """
        if not self._path.exists():
            # File may have been rotated away — clear cache and fail loud
            self._cached_token = None
            self._cached_mtime_ns = None
            raise TokenFileError(f"token file disappeared: {self._path}")
        try:
            content = self._path.read_text().strip()
        except OSError as e:
            raise TokenFileError(f"cannot read token file: {self._path}") from e
        if not content:
            raise TokenFileError(f"token file is empty: {self._path}")
        if len(content) != self._EXPECTED_TOKEN_LEN:
            raise TokenFileError(
                f"token file content has unexpected length "
                f"(expected {self._EXPECTED_TOKEN_LEN})"
            )
        # Hex check — case-insensitive (Imua stores lowercase, but accept upper)
        if not all(c in "0123456789abcdefABCDEF" for c in content):
            raise TokenFileError(
                "token file content is not a hex string"
            )
        self._cached_token = content
        self._cached_mtime_ns = self._path.stat().st_mtime_ns

    def write(self, token: str) -> None:
        """Replace the token on disk atomically (used by rotate_token, task 6.11d).

        Writes a temp file in the same directory with mode 600, then os.replace()s
        it over the old one, so a crash mid-write never leaves a half-written or
        empty token file. Raises TokenFileError (path-only message) on failure.
        """
        if len(token) != self._EXPECTED_TOKEN_LEN or not all(c in "0123456789abcdefABCDEF" for c in token):
            raise TokenFileError("refusing to write a token with an unexpected format")
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(token)
            os.replace(tmp, self._path)
        except OSError as e:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise TokenFileError(f"cannot write token file: {self._path}") from e
        self._cached_token = token
        self._cached_mtime_ns = self._path.stat().st_mtime_ns

    def __repr__(self) -> str:
        return f"TokenFile(path={self._path})"

    def __str__(self) -> str:
        return self.__repr__()
