"""Tests for imua_mcp.auth.TokenFile.

Per spec §8.1, must cover:
- Mode 600/400 required (server exits 1 otherwise)
- Missing file: clean error, no path content in message
- Token re-read on file change (mtime check)
- Token never in argv or error message
- Token never in __repr__ / __str__
"""

import os
import stat
import tempfile
import time
import unittest

from imua_mcp.auth import TokenFile, TokenFileError


# A valid Imua-shaped token: 64 hex chars
VALID_TOKEN = "a" * 32 + "b" * 32  # 64 chars, all hex


def _write_token_file(path: str, content: str = VALID_TOKEN, mode: int = 0o600) -> None:
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, mode)


class TokenFileModeEnforcement(unittest.TestCase):
    def test_mode_600_accepted(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write(VALID_TOKEN)
            path = f.name
        try:
            os.chmod(path, 0o600)
            tf = TokenFile(path)
            self.assertEqual(tf.read(), VALID_TOKEN)
        finally:
            os.unlink(path)

    def test_mode_400_accepted(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write(VALID_TOKEN)
            path = f.name
        try:
            os.chmod(path, 0o400)
            tf = TokenFile(path)
            self.assertEqual(tf.read(), VALID_TOKEN)
        finally:
            # On Windows, chmod(0o400) sets the real read-only DOS attribute
            # (unlike 0o600/0o644, which are no-ops there) — restore write
            # access before unlinking or cleanup itself raises PermissionError.
            os.chmod(path, 0o600)
            os.unlink(path)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits aren't meaningful on Windows")
    def test_mode_644_rejected(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write(VALID_TOKEN)
            path = f.name
        try:
            os.chmod(path, 0o644)
            with self.assertRaises(TokenFileError) as ctx:
                TokenFile(path)
            # Error message must mention the mode, not the token
            self.assertIn("mode", str(ctx.exception).lower())
            self.assertNotIn(VALID_TOKEN, str(ctx.exception))
        finally:
            os.unlink(path)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits aren't meaningful on Windows")
    def test_mode_600_but_world_readable_rejected(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write(VALID_TOKEN)
            path = f.name
        try:
            # 0o604 = owner rw, group r, other r — wrong
            os.chmod(path, 0o604)
            with self.assertRaises(TokenFileError):
                TokenFile(path)
        finally:
            os.unlink(path)

    def test_windows_skips_mode_check_entirely(self):
        """On Windows, os.chmod can't produce a real 0600, so the check is a
        no-op there rather than a permanent, unfixable startup failure."""
        if os.name != "nt":
            self.skipTest("Windows-only behavior")
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write(VALID_TOKEN)
            path = f.name
        try:
            tf = TokenFile(path)
            self.assertEqual(tf.read(), VALID_TOKEN)
        finally:
            os.unlink(path)


class TokenFileMissingAndInvalid(unittest.TestCase):
    def test_missing_file_raises_with_path_only(self):
        # TokenFile resolves to an absolute Path internally, so a hardcoded
        # "/tmp/..." string would come back re-rooted under the current
        # drive on Windows (e.g. "C:\tmp\...") instead of appearing verbatim.
        bogus_path = os.path.join(tempfile.gettempdir(), "__nonexistent_imua_token_xyz__.token")
        if os.path.exists(bogus_path):
            os.unlink(bogus_path)
        with self.assertRaises(TokenFileError) as ctx:
            TokenFile(bogus_path)
        # The filename may appear in the error (operator diagnostic); token must not
        self.assertIn("__nonexistent_imua_token_xyz__.token", str(ctx.exception))
        self.assertNotIn(VALID_TOKEN, str(ctx.exception))

    def test_empty_file_rejected_on_read(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write("")
            path = f.name
        try:
            os.chmod(path, 0o600)
            tf = TokenFile(path)
            with self.assertRaises(TokenFileError) as ctx:
                tf.read()
            self.assertIn("empty", str(ctx.exception).lower())
        finally:
            os.unlink(path)

    def test_wrong_length_rejected(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write("abc123")  # way too short
            path = f.name
        try:
            os.chmod(path, 0o600)
            tf = TokenFile(path)
            with self.assertRaises(TokenFileError) as ctx:
                tf.read()
            self.assertIn("length", str(ctx.exception).lower())
        finally:
            os.unlink(path)

    def test_non_hex_content_rejected(self):
        bad = "z" * 64  # 64 chars but not hex
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write(bad)
            path = f.name
        try:
            os.chmod(path, 0o600)
            tf = TokenFile(path)
            with self.assertRaises(TokenFileError) as ctx:
                tf.read()
            self.assertIn("hex", str(ctx.exception).lower())
        finally:
            os.unlink(path)

    def test_directory_not_a_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(TokenFileError):
                TokenFile(tmpdir)


class TokenFileRotation(unittest.TestCase):
    def test_token_refreshes_when_file_changes(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write(VALID_TOKEN)
            path = f.name
        try:
            os.chmod(path, 0o600)
            tf = TokenFile(path)
            self.assertEqual(tf.read(), VALID_TOKEN)
            # Rotate: write a new token, bump mtime
            new_token = "c" * 64
            with open(path, "w") as f:
                f.write(new_token)
            os.chmod(path, 0o600)
            # Force a mtime change (some filesystems have second-resolution)
            new_mtime = time.time() + 1
            os.utime(path, (new_mtime, new_mtime))
            # Bypass the throttle so the next read() actually re-reads
            tf._last_check_ms = 0.0
            self.assertEqual(tf.read(), new_token)
        finally:
            os.unlink(path)


class TokenFileRepresentation(unittest.TestCase):
    def test_repr_does_not_leak_token(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".token") as f:
            f.write(VALID_TOKEN)
            path = f.name
        try:
            os.chmod(path, 0o600)
            tf = TokenFile(path)
            rep = repr(tf)
            self.assertIn(path, rep)
            self.assertNotIn(VALID_TOKEN, rep)
            self.assertNotIn(VALID_TOKEN, str(tf))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()


class TokenFileWrite(unittest.TestCase):
    """Task 6.11d: TokenFile.write replaces the token atomically and stays owner-only."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "AKM.token")
        with open(self.path, "w") as f:
            f.write("a" * 64)
        os.chmod(self.path, 0o600)

    def test_write_replaces_and_read_returns_new(self):
        from imua_mcp.auth import TokenFile
        tf = TokenFile(self.path)
        self.assertEqual(tf.read(), "a" * 64)
        tf.write("b" * 64)
        self.assertEqual(tf.read(), "b" * 64)
        with open(self.path) as f:
            self.assertEqual(f.read(), "b" * 64)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_written_file_is_owner_only(self):
        from imua_mcp.auth import TokenFile
        TokenFile(self.path).write("c" * 64)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_refuses_malformed_token(self):
        from imua_mcp.auth import TokenFile, TokenFileError
        tf = TokenFile(self.path)
        with self.assertRaises(TokenFileError):
            tf.write("not-a-token")
        with open(self.path) as f:
            self.assertEqual(f.read(), "a" * 64)  # old token untouched
