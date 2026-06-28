"""Fingerprint the skill's runtime source so a code update can be detected.

The long-lived daemon loads this package into memory once; when the skill is
updated on disk the running process keeps serving stale code. `code_version()`
turns the current source into a short, stable hash so the launcher can tell
whether a running daemon matches the code on disk.
"""
import hashlib
from pathlib import Path

# Files whose contents affect what the daemon serves. Tests and assets are
# deliberately excluded so editing a test never forces a daemon restart.
_SKILL_DIR = Path(__file__).resolve().parent.parent
_RUNTIME_GLOBS = ("serve.py", "docserver/*.py")


def _runtime_sources() -> dict:
    files = {}
    for glob in _RUNTIME_GLOBS:
        for p in _SKILL_DIR.glob(glob):
            if p.is_file():
                files[str(p.relative_to(_SKILL_DIR))] = p.read_bytes()
    return files


def fingerprint(files: dict) -> str:
    """Order-independent short hash of a {relpath: bytes} mapping."""
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(files[rel])
        h.update(b"\0")
    return h.hexdigest()[:12]


def code_version() -> str:
    return fingerprint(_runtime_sources())
