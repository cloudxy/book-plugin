"""Persistence shared by the 0.5 production line; legacy contracts stay separate."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from book_skill_common import ContractError, digest, json_bytes

VERSION = "0.5.2"


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


STRUCTURAL = re.compile(r"input_too_large|context[_ ]length|maximum context|too many (?:input )?tokens|request too large|exceeds? (?:the )?(?:maximum|input|context)", re.I)
TRANSIENT = re.compile(r"at capacity|rate.?limit|\b429\b|\b50[0234]\b|overloaded|temporar|timed out|timeout|connection|network|ECONNRESET|reset by peer|unavailable|lease expired", re.I)


def classify_error(message, detail=""):
    """Infrastructure failures are retried with backoff; structural ones are not retried unchanged."""
    observed = f"{message}\n{detail}"
    if STRUCTURAL.search(observed):
        return "structural"
    if TRANSIENT.search(observed):
        return "transient"
    return "worker"


class WorkerTimeout(Exception):
    pass


def run_worker(command, payload, timeout, cwd, poll=15):
    """Wall-clock deadline: a call stalled across machine sleep is stopped promptly after wake."""
    started = time.time()
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, cwd=cwd)
    while True:
        try:
            out, err = process.communicate(payload, timeout=max(1, min(poll, started + timeout - time.time())))
            return process.returncode, out, err, time.time() - started
        except subprocess.TimeoutExpired:
            # 第一次 communicate 已写入并关闭 stdin；重试轮询不得再次发送输入。
            payload = None
            if time.time() >= started + timeout:
                process.kill()
                out, err = process.communicate()
                raise WorkerTimeout(f"worker timed out after {timeout} seconds (wall clock)") from None


def error_line(stderr, limit=300):
    """Short classified excerpt for state; full stderr stays in the private attempt log."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    hit = next((line for line in reversed(lines) if STRUCTURAL.search(line) or TRANSIENT.search(line)), lines[-1] if lines else "")
    return hit[:limit]
