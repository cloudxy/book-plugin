"""Resumable source-to-Skill DAG. Native hosts claim/collect; command workers run it.

No model is bundled or trained. Hashes bind inputs, never prove comprehension.
State and source copies are private workspace data. L3 stays on the legacy route.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from book_skill_common import ContractError, digest, load_source, read_json, slug, text
from production_common import VERSION, atomic_json, decode_result, file_hash, locked, strings
from distill_skill import MODEL_SCHEMA, KINDS, build, validate_model, verify

SCHEMA = "book-production/1"
PROMPTS = Path(__file__).resolve().parents[1] / "skills/book-workflow/references/production-prompts.json"


def chunks(body, limit):
    """Complete, contiguous Unicode ranges; prefer paragraph boundaries."""
    start = 0
    while start < len(body):
        end = min(start + limit, len(body))
        if end < len(body):
            boundary = body.rfind("\n", start + limit // 2, end)
            if boundary >= 0:
                end = boundary + 1
        yield start, end, body[start:end]
        start = end


def task(kind, deps=(), **extra):
    return {"kind": kind, "deps": list(deps), "status": "queued", "attempts": 0, **extra}


def init(root, sources, product, policy=None, prompts=None):
    root = Path(root).resolve()
    if (root / "state.json").exists():
        raise ContractError("production already exists; use sync/resume")
    slug(product.get("id"))
    for key in ("title", "period", "purpose"):
        text(product.get(key), key)
    if product.get("object") not in {"book", "person"}:
        raise ContractError("object must be book/person")
    if not set(strings(product.get("profiles"), "profiles")) <= set(KINDS):
        raise ContractError("unknown content profile")
    defaults = {"chunk_chars": 6000, "merge_fanout": 6, "max_attempts": 2, "max_calls": 100,
                "max_input_chars": 80000, "max_total_input_chars": 1500000,
                "timeout_seconds": 600, "lease_seconds": 660, "max_seconds": 7200, "parallel": 2}
    defaults.update(policy or {})
    if any(type(v) is not int or v <= 0 for v in defaults.values()):
        raise ContractError("policy values must be positive integers")
    if defaults["chunk_chars"] < 200 or defaults["merge_fanout"] < 2 or defaults["lease_seconds"] <= defaults["timeout_seconds"]:
        raise ContractError("chunk >=200, fanout >=2, lease must exceed worker timeout")
    if not sources:
        raise ContractError("actual sources required; research/download first")
    state = {"schema_version": SCHEMA, "workflow_version": VERSION, "product": product,
             "prompts": str(Path(prompts or PROMPTS).resolve()),
             "policy": defaults, "sources": [], "units": {}, "tasks": {}, "created_at": time.time(),
             "usage": {"calls": 0, "input_chars": 0, "elapsed_seconds": 0}, "events": []}
    for i, source in enumerate(sources, 1):
        path = Path(source["path"]).resolve()
        for field in ("role", "period"):
            text(source.get(field), f"source.{field}")
        state["sources"].append({**source, "id": f"s{i:03}", "path": str(path)})
    with locked(root):
        _plan(root, state)
        save(root, state)
    return state


def _plan(root, state):
    old = state["tasks"]
    tasks, units = {}, {}
    for source in state["sources"]:
        path = Path(source["path"])
        body = load_source(path)
        if not body.strip():
            raise ContractError("empty source")
        source["raw_sha256"] = file_hash(path)
        source["text_sha256"] = digest(body.encode())
        source["snapshot"] = f"sources/{source['id']}-{source['text_sha256']}.txt"
        snap = root / source["snapshot"]
        snap.parent.mkdir(parents=True, exist_ok=True)
        if not snap.exists():
            snap.write_text(body, encoding="utf-8")
        for i, (start, end, value) in enumerate(chunks(body, state["policy"]["chunk_chars"]), 1):
            uid = f"{source['id']}-u{i:04}"
            units[uid] = {"source": source["id"], "start": start, "end": end, "sha256": digest(value.encode())}
            tasks[uid] = task("read", unit=uid)
    level = list(tasks)
    depth = 0
    while len(level) > state["policy"]["merge_fanout"]:
        next_level = []
        for i in range(0, len(level), state["policy"]["merge_fanout"]):
            mid = f"merge-{depth}-{i}"
            tasks[mid] = task("merge", level[i:i + state["policy"]["merge_fanout"]])
            next_level.append(mid)
        level = next_level
        depth += 1
    tasks["synthesize"] = task("synthesize", level)
    tasks["review"] = task("review", ["synthesize"])
    tasks["build"] = task("build", ["synthesize", "review"])
    for tid, current in tasks.items():
        previous = old.get(tid)
        if previous and previous["deps"] == current["deps"]:
            tasks[tid] = previous
    state["units"], state["tasks"] = units, tasks
    state["source_snapshot_hash"] = digest(state["sources"])
    refresh(root, state)


def read_state(root):
    state = read_json(Path(root) / "state.json")
    if state.get("schema_version") != SCHEMA:
        raise ContractError("unsupported production schema")
    return state


def save(root, state):
    state["updated_at"] = time.time()
    atomic_json(Path(root) / "state.json", state)
    states = {key: sum(t["status"] == key for t in state["tasks"].values()) for key in ("queued", "running", "done", "failed", "stale")}
    # The projection lives inside pipeline; never overwrite legacy PIPELINE_STATE.md.
    body = f"# Production state\n\n{state['product']['title']} — {states}\n\n"
    body += "已构建不等于已实测或已交付。实际状态见 state.json；原正式任务状态保持独立。\n"
    (Path(root) / "STATUS.md").write_text(body, encoding="utf-8")


def source_text(root, state, uid):
    unit = state["units"][uid]
    source = next(s for s in state["sources"] if s["id"] == unit["source"])
    body = (Path(root) / source["snapshot"]).read_text(encoding="utf-8")
    value = body[unit["start"]:unit["end"]]
    if digest(value.encode()) != unit["sha256"]:
        raise ContractError("source snapshot changed")
    return value


def fingerprint(root, state, tid):
    t = state["tasks"][tid]
    prompts = read_json(state.get("prompts", PROMPTS))
    inputs = {"kind": t["kind"], "product": state["product"], "deps": {d: state["tasks"][d].get("output_hash") for d in t["deps"]},
              "prompt": prompts.get(t["kind"]), "feedback": t.get("feedback"), "workflow": VERSION,
              "code": file_hash(Path(__file__)), "builder": file_hash(Path(__file__).with_name("distill_skill.py"))}
    if t["kind"] == "read":
        unit = state["units"][tid]
        source = next(s for s in state["sources"] if s["id"] == unit["source"])
        inputs["unit"] = unit
        inputs["source"] = {k: source[k] for k in ("id", "role", "period")}
    else:
        inputs["source_snapshot_hash"] = state["source_snapshot_hash"]
    return digest(inputs)


def dependency_order(tasks):
    visited, active, result = set(), set(), []
    def visit(tid):
        if tid in active or tid not in tasks:
            raise ContractError("cyclic or missing task dependency")
        if tid in visited:
            return
        active.add(tid)
        for dep in tasks[tid]["deps"]:
            visit(dep)
        active.remove(tid)
        visited.add(tid)
        result.append(tid)
    for tid in tasks:
        visit(tid)
    return result


def refresh(root, state):
    for tid in dependency_order(state["tasks"]):
        t = state["tasks"][tid]
        stale = t.get("input_hash") and t["input_hash"] != fingerprint(root, state, tid)
        if t["status"] == "done":
            path = Path(root) / t["output"]
            stale = stale or not path.exists() or file_hash(path) != t.get("output_hash")
            if t["kind"] == "build" and not stale:
                try:
                    verify(Path(root) / read_json(path)["result"]["package"])
                except (ContractError, OSError):
                    stale = True
        if any(state["tasks"][d]["status"] != "done" for d in t["deps"]):
            stale = stale or t["status"] in {"done", "running"}
        if stale:
            t["status"] = "stale"
            t.pop("output_hash", None)
            t.pop("lease", None)
            t["attempts"] = 0  # new input version gets a new bounded attempt budget
            t.pop("input_hash", None)
        if t["status"] == "running" and t["lease"]["until"] < time.time():
            t["status"] = "failed"
            t["error"] = "lease expired; attempt retained"
            t.pop("lease", None)


def check_sources(state):
    if any(file_hash(s["path"]) != s["raw_sha256"] for s in state["sources"]):
        raise ContractError("source changed; run sync to invalidate affected work")


def packet(root, state, tid):
    t = state["tasks"][tid]
    prompt = read_json(state.get("prompts", PROMPTS)).get(t["kind"], "")
    data = {"schema_version": SCHEMA, "task_id": tid, "stage": t["kind"], "instruction": prompt,
            "product": state["product"], "feedback": t.get("feedback"), "inputs": {}}
    for dep in t["deps"]:
        data["inputs"][dep] = read_json(Path(root) / state["tasks"][dep]["output"])["result"]
    if t["kind"] == "read":
        unit = state["units"][tid]
        data["source_unit"] = {"id": tid, **unit, "text": source_text(root, state, tid)}
        data["source_metadata"] = next({k: v for k, v in s.items() if k not in {"path", "snapshot"}} for s in state["sources"] if s["id"] == unit["source"])
    elif t["kind"] == "review":
        model = data["inputs"]["synthesize"]
        uids = sorted({u for c in model["capabilities"] for u in c["evidence"]})
        data["source_units"] = {uid: source_text(root, state, uid) for uid in uids}
        data["sources"] = [{k: v for k, v in s.items() if k not in {"path", "snapshot"}} for s in state["sources"]]
        data["reading_findings"] = {uid: read_json(Path(root) / state["tasks"][uid]["output"])["result"] for uid in state["units"]}
    elif t["kind"] == "synthesize":
        data["source_units"] = list(state["units"])
        data["output_schema"] = MODEL_SCHEMA
    return data


def claim(root, owner, wanted=None):
    root = Path(root).resolve()
    with locked(root):
        state = read_state(root)
        check_sources(state)
        refresh(root, state)
        policy, usage = state["policy"], state["usage"]
        if sum(t["status"] == "running" for t in state["tasks"].values()) >= policy["parallel"]:
            save(root, state)
            return None
        for tid, t in state["tasks"].items():
            if wanted and wanted != tid:
                continue
            if t["status"] not in {"queued", "stale", "failed"} or t["attempts"] >= policy["max_attempts"]:
                continue
            if any(state["tasks"][d]["status"] != "done" for d in t["deps"]):
                continue
            p = packet(root, state, tid)
            size = len(json.dumps(p, ensure_ascii=False))
            if t["kind"] != "build" and (usage["calls"] >= policy["max_calls"] or size > policy["max_input_chars"] or usage["input_chars"] + size > policy["max_total_input_chars"] or usage["elapsed_seconds"] >= policy["max_seconds"]):
                state["stop_reason"] = "budget/context limit reached; checkpoint preserved"
                save(root, state)
                return None
            token = uuid.uuid4().hex
            t.update(status="running", input_hash=fingerprint(root, state, tid))
            t["attempts"] += 1
            t["lease"] = {"owner": owner, "token": token, "until": time.time() + policy["lease_seconds"], "started_at": time.time()}
            p.update(claim_token=token, input_hash=t["input_hash"], attempt=t["attempts"])
            rel = f"attempts/{tid}/{token}/request.json"
            atomic_json(root / rel, p)
            t["request"] = rel
            if t["kind"] != "build":
                usage["calls"] += 1
                usage["input_chars"] += size
            state.pop("stop_reason", None)
            save(root, state)
            return p
        save(root, state)
        return None


def validate_result(state, tid, result, executor, root):
    kind = state["tasks"][tid]["kind"]
    for field in ("session_id", "host", "model"):
        text(executor.get(field), f"executor.{field}")
    if kind in {"read", "merge"}:
        strings(result.get("covered_units"), "covered_units")
        expected = {tid} if kind == "read" else set()
        if kind == "merge":
            for dep in state["tasks"][tid]["deps"]:
                expected.update(read_json(Path(root) / state["tasks"][dep]["output"])["result"]["covered_units"])
        if set(result["covered_units"]) != expected:
            raise ContractError("reading/merge must account for every assigned unit")
        text(result.get("findings"), "findings")
        strings(result.get("limitations"), "limitations", allow_empty=True)
        strings(result.get("open_connections"), "open_connections", allow_empty=True)
    elif kind == "synthesize":
        validate_model(result, state["units"])
    elif kind == "review":
        synth = read_json(Path(root) / state["tasks"]["synthesize"]["output"])
        authors = {read_json(Path(root) / t["output"])["executor"]["session_id"] for t in state["tasks"].values() if t["status"] == "done" and t["kind"] in {"read", "merge", "synthesize"}}
        if executor["session_id"] in authors:
            raise ContractError("review session must be independent of all generators")
        model = synth["result"]
        expected = {x["id"] for x in model["capabilities"] + model["examples"]}
        decisions = result.get("decisions", {})
        if set(decisions) != expected:
            raise ContractError("review must cover each capability and example")
        for key, value in decisions.items():
            if value.get("verdict") not in {"pass", "fail"}:
                raise ContractError(f"invalid review verdict: {key}")
            text(value.get("reason"), f"{key}.reason")
        strings(result.get("issues"), "issues", allow_empty=True)
        text(result.get("coverage_assessment"), "coverage_assessment")
        if result.get("verdict") not in {"pass", "fail"} or (result["verdict"] == "pass" and (result["issues"] or any(v["verdict"] != "pass" for v in decisions.values()))):
            raise ContractError("review aggregate conflicts with decisions")


def collect(root, tid, token, result, executor, error=None, usage=None):
    root = Path(root).resolve()
    with locked(root):
        state = read_state(root)
        check_sources(state)
        refresh(root, state)
        t = state["tasks"].get(tid)
        if not t or t["status"] != "running" or t["lease"]["token"] != token:
            raise ContractError("stale/foreign lease; result cannot overwrite newer work")
        if not error:
            try:
                validate_result(state, tid, result, executor, root)
            except (ContractError, TypeError, KeyError, AttributeError) as exc:
                error = str(exc)
        elapsed = time.time() - t["lease"]["started_at"]
        rel = str(Path(t["request"]).with_name("result.json"))
        envelope = {"task_id": tid, "input_hash": t["input_hash"], "executor": executor, "result": result,
                    "error": error, "elapsed_seconds": elapsed, "usage": usage or {"tokens": None, "cost": None}}
        atomic_json(root / rel, envelope)
        failed_review = t["kind"] == "review" and not error and result.get("verdict") == "fail"
        t.update(status="failed" if error or failed_review else "done", output=rel, output_hash=file_hash(root / rel))
        t.pop("lease")
        if error:
            t["error"] = error
        else:
            t.pop("error", None)
        state["usage"]["elapsed_seconds"] += elapsed
        state["events"].append({"task_id": tid, "status": t["status"], "input_hash": t["input_hash"], "output": rel, "time": time.time()})
        if failed_review:
            # Bounded repair at synthesis; read-specific failures can be retried explicitly.
            target = state["tasks"]["synthesize"]
            if target["attempts"] < state["policy"]["max_attempts"]:
                attempts = target["attempts"]
                target["feedback"] = result
                refresh(root, state)
                target["attempts"] = attempts
                t["attempts"] = 0
        save(root, state)
        return envelope


def status(root):
    root = Path(root).resolve()
    with locked(root):
        state = read_state(root)
        try:
            check_sources(state)
        except (ContractError, OSError):
            return {"status": "stale-source", "next": "sync", "product": state["product"]}
        refresh(root, state)
        save(root, state)
        ready = [tid for tid, t in state["tasks"].items() if t["status"] in {"queued", "stale", "failed"} and t["attempts"] < state["policy"]["max_attempts"] and all(state["tasks"][d]["status"] == "done" for d in t["deps"])]
        result = {"status": "built-pending-runtime" if state["tasks"]["build"]["status"] == "done" else "pending",
                  "product": state["product"], "ready": ready, "usage": state["usage"], "stop_reason": state.get("stop_reason"),
                  "tasks": {tid: {k: t[k] for k in ("kind", "status", "attempts")} for tid, t in state["tasks"].items()}}
        if result["status"] == "built-pending-runtime":
            result.update(read_json(root / state["tasks"]["build"]["output"])["result"])
        return result


def sync(root):
    with locked(root):
        state = read_state(root)
        _plan(Path(root), state)
        save(root, state)
    return status(root)


def retry(root, tid, feedback):
    with locked(root):
        state = read_state(root)
        if tid not in state["tasks"]:
            raise ContractError("unknown task")
        t = state["tasks"][tid]
        if t["status"] == "running":
            raise ContractError("task still leased; wait for expiry or worker completion")
        attempts = t["attempts"]
        if attempts >= state["policy"]["max_attempts"]:
            raise ContractError("attempt budget exhausted; revise policy explicitly before more work")
        t["feedback"] = text(feedback, "feedback")
        t["status"] = "stale"
        t.pop("output_hash", None)
        refresh(root, state)
        t["attempts"] = attempts
        save(root, state)


def execute_one(root, command, owner):
    p = claim(root, owner)
    if not p:
        return False
    state = read_state(root)
    executor = {"session_id": p["claim_token"], "host": "command", "model": "not-reported"}
    result, error, usage = {}, None, None
    try:
        if p["stage"] == "build":
            result = build(root, state)
            executor["host"], executor["model"] = "python", "none"
        else:
            completed = subprocess.run(command, input=json.dumps(p, ensure_ascii=False), text=True,
                                       capture_output=True, timeout=state["policy"]["timeout_seconds"], cwd=root)
            log = Path(root) / state["tasks"][p["task_id"]]["request"]
            log.with_name("stdout.txt").write_text(completed.stdout, encoding="utf-8")
            log.with_name("stderr.txt").write_text(completed.stderr, encoding="utf-8")
            if completed.returncode:
                raise ContractError(f"worker exited {completed.returncode}; see private attempt log")
            response = decode_result(completed.stdout)
            result, executor, usage = response["result"], response["executor"], response.get("usage")
    except (OSError, subprocess.TimeoutExpired, ContractError, KeyError) as exc:
        error = str(exc)
    collect(root, p["task_id"], p["claim_token"], result, executor, error, usage)
    return True


def run(roots, command, parallel=2):
    if not isinstance(command, list) or not command or any(not isinstance(s, str) for s in command):
        raise ContractError("worker command must be a JSON argv list; shell strings are not supported")
    started = time.time()
    roots = [Path(root).resolve() for root in roots]
    owner = f"runner-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    # Per-root policy limits concurrent work; file leases also protect other runners.
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        while True:
            jobs = []
            for root in roots:
                s = read_state(root)
                slots = min(parallel, s["policy"]["parallel"])
                jobs.extend(pool.submit(execute_one, root, command, owner) for _ in range(slots))
            progressed = [job.result() for job in jobs]
            if not any(progressed):
                break
    return {"wall_seconds": time.time() - started, "runs": [status(root) for root in roots]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    subs = ap.add_subparsers(dest="command", required=True)
    p = subs.add_parser("init")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--source", action="append", type=Path, required=True)
    for key in ("id", "title", "period", "purpose"):
        p.add_argument(f"--{key}", required=True)
    p.add_argument("--object", choices=("book", "person"), default="book")
    p.add_argument("--profile", action="append", choices=KINDS, required=True)
    p.add_argument("--source-role", default="primary-text")
    p.add_argument("--policy", type=Path)
    p.add_argument("--prompts", type=Path, help="optional versioned stage instruction candidate")
    for name in ("status", "sync", "claim", "collect", "retry"):
        p = subs.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        if name == "claim":
            p.add_argument("--owner", required=True)
            p.add_argument("--task")
        if name == "collect":
            p.add_argument("--response", type=Path, required=True)
        if name == "retry":
            p.add_argument("--task", required=True)
            p.add_argument("--feedback", required=True)
    p = subs.add_parser("run")
    p.add_argument("--root", action="append", type=Path, required=True)
    p.add_argument("--worker", type=Path, required=True, help="JSON file containing argv list")
    p.add_argument("--parallel", type=int, default=2)
    args = ap.parse_args()
    try:
        if args.command == "init":
            product = {key: getattr(args, key) for key in ("id", "title", "object", "period", "purpose")}
            product["profiles"] = args.profile
            init(args.root, [{"path": str(p), "role": args.source_role, "period": args.period} for p in args.source], product, read_json(args.policy) if args.policy else None, args.prompts)
            result = status(args.root)
        elif args.command == "status":
            result = status(args.root)
        elif args.command == "sync":
            result = sync(args.root)
        elif args.command == "claim":
            result = claim(args.root, args.owner, args.task)
        elif args.command == "collect":
            response = read_json(args.response)
            result = collect(args.root, response["task_id"], response["claim_token"], response["result"], response["executor"], usage=response.get("usage"))
        elif args.command == "retry":
            retry(args.root, args.task, args.feedback)
            result = status(args.root)
        else:
            if args.parallel < 1:
                raise ContractError("parallel must be positive")
            result = run(args.root, read_json(args.worker), args.parallel)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, KeyError, TypeError) as exc:
        ap.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
