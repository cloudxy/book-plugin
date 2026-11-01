"""Persistence shared by the 0.5 production line; legacy contracts stay separate."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile

from book_skill_common import ContractError, digest, json_bytes

VERSION = "0.5.0"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def strings(value, label, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ContractError(f"{label}: list required")
    if any(not isinstance(v, str) or not v.strip() for v in value):
        raise ContractError(f"{label}: nonempty strings required")
    return value


def decode_result(raw):
    """Accept one JSON response, optionally fenced; never extract arbitrary substrings."""
    raw = raw.strip()
    if raw.startswith("```json\n") and raw.endswith("```"):
        raw = raw[8:-3].strip()
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ContractError(f"executor did not return JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("executor result must be an object")
    return value


def file_hash(path):
    return digest(Path(path).read_bytes())
