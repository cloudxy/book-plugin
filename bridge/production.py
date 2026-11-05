"""Resumable source-to-Skill DAG. Native hosts claim/collect; command workers run it.

No model is bundled or trained. Hashes bind inputs, never prove comprehension.
State and source copies are private workspace data. L3 stays on the legacy route.
Cache keys bind task inputs and the pinned stage module, not scheduler source code.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time
import uuid

from book_skill_common import ContractError, digest, load_source, read_json, slug, text
from production_common import (VERSION, WorkerTimeout, atomic_json, classify_error, decode_result, error_line, file_hash,
                               locked, run_worker, strings)
from distill_skill import KINDS, build, verify
import production_stages as stages

SCHEMA = "book-production/1"
PROMPTS = stages.LEGACY_PROMPTS  # frozen 0.5.0 instructions, kept for runs pinned to them
MODULES = stages.MODULES
TIERS = ("L1", "L2")
# Person material keeps its provenance apart: own account, own work, others' account, later interpretation.
PERSON_ROLES = ("self-account", "work", "others-account", "later-interpretation")
DEFAULT_POLICY = {"chunk_chars": 6000, "merge_fanout": 6, "max_attempts": 2, "max_calls": 100,
                  "max_input_chars": 250000, "part_input_chars": 200000, "max_total_input_chars": 1500000,
                  "timeout_seconds": 600, "lease_seconds": 660, "max_seconds": 7200, "parallel": 2,
                  "max_repair_rounds": 2, "max_transient_retries": 6, "backoff_seconds": 30, "backoff_max_seconds": 900}
STAGE_TIMEOUTS = {"read": 600, "merge": 1200, "audit-part": 1200, "synthesize": 1800, "review-part": 1500, "review": 1800}
# Hashes of the 0.5.0 scheduler/builder sources that used to be part of every cache key.
LEGACY_CODE = {"code": "f31e790eebc277317e4857cbd38c03d424cafc7f7f6e6e0fb5d859ecb7bee4fd",
               "builder": "9b7685933644023a399a4ddb946c39a39d65b314c5b280a11e542974cacead85"}
INTERVENTIONS = {"policy", "retry", "unblock", "accept-gaps", "held-out-feedback"}


def pv(policy, key):
    return policy.get(key, DEFAULT_POLICY.get(key))


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


def check_policy(policy):
    for key, value in policy.items():
        if key == "stage_timeout_seconds":
            if not isinstance(value, dict) or any(k not in STAGE_TIMEOUTS or type(v) is not int or v <= 0 for k, v in value.items()):
                raise ContractError("stage_timeout_seconds: known stages with positive integer seconds")
        elif type(value) is not int or value <= 0:
            raise ContractError("policy values must be positive integers")
    if policy["chunk_chars"] < 200 or policy["merge_fanout"] < 2 or policy["lease_seconds"] <= policy["timeout_seconds"]:
        raise ContractError("chunk >=200, fanout >=2, lease must exceed worker timeout")


def stage_timeout(policy, kind):
    explicit = policy.get("stage_timeout_seconds", {}).get(kind)
    return explicit or max(policy["timeout_seconds"], STAGE_TIMEOUTS.get(kind, policy["timeout_seconds"]))


def init(root, sources, product, policy=None, prompts=None, target_tier="L2", host="unspecified"):
    root = Path(root).resolve()
    if (root / "state.json").exists():
        raise ContractError("production already exists; use sync/resume")
    slug(product.get("id"))
    for key in ("title", "period", "purpose"):
        text(product.get(key), key)
    for key in ("edition", "translator"):
        if key in product:
            text(product[key], key)
    if product.get("object") not in {"book", "person"}:
        raise ContractError("object must be book/person")
    if not set(strings(product.get("profiles"), "profiles")) <= set(KINDS):
        raise ContractError("unknown content profile")
    if not set(product.get("genres", [])) <= set(stages.GENRES):
        raise ContractError("unknown genre template")
    if target_tier == "L3":
        raise ContractError("L3 formal acceptance stays on the legacy author/whole-book route")
    if target_tier not in TIERS:
        raise ContractError("target tier must be L1 or L2")
    defaults = dict(DEFAULT_POLICY)
    defaults.update(policy or {})
    check_policy(defaults)
    if not sources:
        raise ContractError("actual sources required; research/download first")
    state = {"schema_version": SCHEMA, "workflow_version": VERSION, "fingerprint_scheme": 2, "intake": 2,
             "target_tier": target_tier, "host": host, "product": product,
             "prompts": str(Path(prompts or MODULES).resolve()),
             "policy": defaults, "sources": [], "units": {}, "tasks": {}, "created_at": time.time(),
             "usage": {"calls": 0, "input_chars": 0, "elapsed_seconds": 0}, "events": []}
    for i, source in enumerate(sources, 1):
        path = Path(source["path"]).resolve()
        for field in ("role", "period"):
            text(source.get(field), f"source.{field}")
        if product["object"] == "person" and source["role"] not in PERSON_ROLES:
            raise ContractError(f"person sources need a role in {PERSON_ROLES}")
        for field in ("url", "access", "retrieved_at"):
            if field in source:
                text(source[field], f"source.{field}")
        if not set(source.get("genres", [])) <= set(stages.GENRES):
            raise ContractError("unknown source genre template")
        strings(source.get("declared_issues", []), "declared_issues", allow_empty=True)
        state["sources"].append({**source, "id": f"s{i:03}", "path": str(path)})
    with locked(root):
        _plan(root, state)
        state["events"].append({"type": "command", "name": "init", "time": time.time()})
        save(root, state)
    return state


def _plan(root, state):
    old = state["tasks"]
    tasks, units = {}, {}
    intake = state.get("intake") == 2
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
        start, end = stages.body_range(body, source.get("body"))
        if intake:
            source["excluded"] = ([[0, start, "declared outside body"]] if start else []) + ([[end, len(body), "declared outside body"]] if end < len(body) else [])
            source["issues"] = source.get("declared_issues", []) + stages.source_issues(body[start:end])
        index = stages.position_index(body)
        for i, (a, b, value) in enumerate(chunks(body[start:end], state["policy"]["chunk_chars"]), 1):
            uid = f"{source['id']}-u{i:04}"
            units[uid] = {"source": source["id"], "start": start + a, "end": start + b, "sha256": digest(value.encode()),
                          "locator": stages.locate(body, index, start + a, start + b)}
            tasks[uid] = task("read", unit=uid)
    reads = list(tasks)
    level = list(reads)
    depth = 0
    while len(level) > state["policy"]["merge_fanout"]:
        next_level = []
        for i in range(0, len(level), state["policy"]["merge_fanout"]):
            mid = f"merge-{depth}-{i}"
            tasks[mid] = task("merge", level[i:i + state["policy"]["merge_fanout"]])
            next_level.append(mid)
        level = next_level
        depth += 1
    feature = stages.features(state)
    gate = list(level)
    if feature.get("audit"):
        tasks["audit"] = task("audit", reads, mode="python")
        gate.append("audit")
    if feature.get("ledger"):
        tasks["ledger"] = task("ledger", gate, mode="python")
    if state.get("target_tier", "L2") == "L2":
        tasks["synthesize"] = task("synthesize", gate)
        tasks["review"] = task("review", ["synthesize"])
        tasks["build"] = task("build", ["synthesize", "review"], mode="python")
    reused = 0
    for tid, current in tasks.items():
        previous = old.get(tid)
        if previous and previous["deps"] == current["deps"]:
            tasks[tid] = previous
            reused += previous["status"] == "done"
    # Budget layout parts survive a re-plan while their inputs exist; refresh re-derives them as needed.
    tasks.update({tid: prev for tid, prev in old.items() if "-part-" in tid and set(prev["deps"]) <= set(tasks)})
    for name in ("review", "audit"):
        prev = old.get(name)
        if name in tasks and prev and prev.get("mode") == "python" and set(prev["deps"]) <= set(tasks):
            tasks[name] = prev
    state["units"], state["tasks"] = units, tasks
    state["source_snapshot_hash"] = digest(state["sources"])
    refresh(root, state)
    return reused


def legacy_fingerprint(root, state, tid):
    """The 0.5.0 cache key, used only to verify old done work before re-keying it."""
    t = state["tasks"][tid]
    prompts = stages.load(state.get("prompts", PROMPTS))
    inputs = {"kind": t["kind"], "product": state["product"], "deps": {d: state["tasks"][d].get("output_hash") for d in t["deps"]},
              "prompt": prompts.get(t["kind"]), "feedback": t.get("feedback"), "workflow": "0.5.0", **LEGACY_CODE}
    if t["kind"] == "read":
        unit = state["units"][tid]
        source = next(s for s in state["sources"] if s["id"] == unit["source"])
        inputs["unit"] = {k: unit[k] for k in ("source", "start", "end", "sha256")}
        inputs["source"] = {k: source[k] for k in ("id", "role", "period")}
    else:
        inputs["source_snapshot_hash"] = state["source_snapshot_hash"]
    return digest(inputs)


def migrate(root, state):
    if state.get("fingerprint_scheme") == 2:
        return state
    kept = dropped = 0
    for tid in stages_order(state["tasks"]):
        t = state["tasks"][tid]
        if not t.get("input_hash"):
            continue
        try:
            verified = t["input_hash"] == legacy_fingerprint(root, state, tid)
        except (ContractError, OSError, KeyError):
            verified = False
        if verified:
            t["input_hash"] = fingerprint(root, state, tid)
            kept += 1
        else:
            dropped += 1
    state["fingerprint_scheme"] = 2
    state.setdefault("target_tier", "L2")
    state.setdefault("events", []).append({"type": "migration", "from": "0.5.0 cache keys", "verified": kept,
                                           "unverified": dropped, "time": time.time()})
    return state


def stages_order(tasks):
    return dependency_order(tasks)


def read_state(root):
    state = read_json(Path(root) / "state.json")
    if state.get("schema_version") != SCHEMA:
        raise ContractError("unsupported production schema")
    return migrate(root, state)


def save(root, state):
    state["updated_at"] = time.time()
    atomic_json(Path(root) / "state.json", state)
    states = {key: sum(t["status"] == key for t in state["tasks"].values()) for key in ("queued", "running", "done", "failed", "stale", "blocked")}
    # The projection lives inside pipeline; never overwrite legacy PIPELINE_STATE.md.
    body = f"# Production state\n\n{state['product']['title']} — 目标档 {state.get('target_tier', 'L2')} — {states}\n\n"
    body += "已构建不等于已实测或已交付。实际状态见 state.json；原正式任务状态保持独立。\n"
    (Path(root) / "STATUS.md").write_text(body, encoding="utf-8")


def source_text(root, state, uid):
    return stages.source_text(root, state, uid)


def fingerprint(root, state, tid):
    t = state["tasks"][tid]
    module = stages.stage_module(state, t["kind"])
    inputs = {"scheme": 2, "kind": t["kind"], "product": state["product"], "target_tier": state.get("target_tier", "L2"),
              "deps": {d: state["tasks"][d].get("output_hash") for d in t["deps"]},
              "module": digest(module), "feedback": t.get("feedback")}
    for key in ("items", "assigned", "mode", "accepted_gaps"):
        if t.get(key) is not None:
            inputs[key] = t[key]
    source = None
    if t["kind"] == "read":
        unit = state["units"][tid]
        source = next(s for s in state["sources"] if s["id"] == unit["source"])
        inputs["unit"] = {k: unit[k] for k in ("source", "start", "end", "sha256")}
        inputs["source"] = {k: source[k] for k in ("id", "role", "period", "genres") if k in source}
    else:
        inputs["source_snapshot_hash"] = state["source_snapshot_hash"]
    if "legacy_instruction" not in module and module.get("instruction"):
        inputs["templates"] = digest(stages.templates(state, source))
    if t["kind"] == "audit-part":
        inputs["sample_seed"] = state["source_snapshot_hash"]
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


def refresh(root, state, keep=None):
    before = {k: v.get("key") for k, v in state.get("layout", {}).items()}
    try:
        stages.layout(root, state)
    except (ContractError, OSError, KeyError) as exc:
        state["layout_error"] = str(exc)
    else:
        state.pop("layout_error", None)
    for name, record in state.get("layout", {}).items():
        if record.get("key") != before.get(name):
            state["events"].append({"type": "layout", "stage": name, "mode": record.get("mode", "parts"),
                                    "parts": len(record.get("parts", [])), "time": time.time()})
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
            if t["status"] in {"done", "running"}:
                t["cause"] = "input-changed"
            t["status"] = "stale"
            for key in ("output_hash", "lease", "input_hash", "blocked", "not_before", "transient"):
                t.pop(key, None)
            t["attempts"] = 0  # new input version gets a new bounded attempt budget
        if t["status"] == "running" and t["lease"]["until"] < time.time() and t["lease"]["token"] != keep:
            t["status"] = "failed"
            t["error"] = "lease expired; attempt retained"
            t["error_class"] = "transient"
            t["transient"] = t.get("transient", 0) + 1
            t["cause"] = "retry-after-transient"
            t.pop("lease", None)


def check_sources(state):
    if any(file_hash(s["path"]) != s["raw_sha256"] for s in state["sources"]):
        raise ContractError("source changed; run sync to invalidate affected work")


def packet(root, state, tid):
    return stages.packet(root, state, tid)


def eligible(state, t, now):
    policy = state["policy"]
    if t["status"] not in {"queued", "stale", "failed"} or t.get("blocked"):
        return False
    if t.get("not_before", 0) > now:
        return False
    if t["attempts"] - t.get("transient", 0) >= policy["max_attempts"] or t.get("transient", 0) >= pv(policy, "max_transient_retries"):
        return False
    return all(state["tasks"][d]["status"] == "done" for d in t["deps"])


def python_task(t):
    return t["kind"] in {"build", "audit", "ledger"} or t.get("mode") == "python"


def _lease(state, t, owner, kind):
    now = time.time()
    timeout = stage_timeout(state["policy"], kind)
    return {"owner": owner, "token": uuid.uuid4().hex, "until": now + max(state["policy"]["lease_seconds"], timeout + 300),
            "started_at": now}


def _run_python(root, state, tid, owner):
    t = state["tasks"][tid]
    t["lease"] = _lease(state, t, owner, t["kind"])
    token = t["lease"]["token"]
    t.update(status="running", input_hash=fingerprint(root, state, tid))
    t["attempts"] += 1
    rel = f"attempts/{tid}/{token}/request.json"
    atomic_json(root / rel, {"task_id": tid, "stage": t["kind"], "deps": t["deps"], "input_hash": t["input_hash"], "executor": "python"})
    t["request"] = rel
    result, error = {}, None
    try:
        if t["kind"] == "build":
            result = build(root, state)
        elif t["kind"] == "audit":
            result = stages.aggregate_audit(root, state)
        elif t["kind"] == "ledger":
            result = stages.write_ledger(root, state)
        else:
            result = stages.aggregate_review(root, state)
    except (ContractError, OSError, KeyError) as exc:
        error = str(exc)
    return _complete(root, state, tid, token, result, {"session_id": f"python-{token}", "host": "python", "model": "none"}, error)


def run_python_tasks(root, state, owner):
    progressed = True
    while progressed:
        progressed = False
        now = time.time()
        for tid in dependency_order(state["tasks"]):
            t = state["tasks"][tid]
            if python_task(t) and eligible(state, t, now):
                _run_python(root, state, tid, owner)
                refresh(root, state)
                progressed = True
                break


def claim(root, owner, wanted=None):
    root = Path(root).resolve()
    with locked(root):
        state = read_state(root)
        check_sources(state)
        refresh(root, state)
        run_python_tasks(root, state, owner)
        policy, usage = state["policy"], state["usage"]
        if sum(t["status"] == "running" for t in state["tasks"].values()) >= policy["parallel"]:
            save(root, state)
            return None
        now = time.time()
        for tid, t in state["tasks"].items():
            if wanted and wanted != tid:
                continue
            if python_task(t) or not eligible(state, t, now):
                continue
            p = packet(root, state, tid)
            size = len(json.dumps(p, ensure_ascii=False))
            ceiling = min(policy["max_input_chars"], state.get("host_limits", {}).get("max_input_chars") or policy.get("host_max_input_chars") or policy["max_input_chars"])
            if size > ceiling:
                t["blocked"] = {"class": "structural", "reason": f"packet {size} chars exceeds input ceiling {ceiling}; "
                                "reduce chunk_chars/merge_fanout or raise max_input_chars explicitly", "size": size}
                t["status"] = "blocked"
                state["events"].append({"type": "blocked", "task_id": tid, **t["blocked"], "time": now})
                continue
            if usage["calls"] >= policy["max_calls"] or usage["input_chars"] + size > policy["max_total_input_chars"] or usage["elapsed_seconds"] >= policy["max_seconds"]:
                state["stop_reason"] = "budget/context limit reached; checkpoint preserved"
                save(root, state)
                return None
            t["lease"] = _lease(state, t, owner, t["kind"])
            token = t["lease"]["token"]
            t.update(status="running", input_hash=fingerprint(root, state, tid), packet_chars=size)
            t["attempts"] += 1
            p.update(claim_token=token, input_hash=t["input_hash"], attempt=t["attempts"])
            rel = f"attempts/{tid}/{token}/request.json"
            atomic_json(root / rel, p)
            t["request"] = rel
            usage["calls"] += 1
            usage["input_chars"] += size
            state.pop("stop_reason", None)
            save(root, state)
            return p
        save(root, state)
        return None


def validate_result(state, tid, result, executor, root):
    stages.validate_result(root, state, tid, result, executor)


def _backoff(state, t, now):
    policy = state["policy"]
    t["not_before"] = now + min(pv(policy, "backoff_max_seconds"), pv(policy, "backoff_seconds") * 2 ** max(0, t.get("transient", 1) - 1))


def _complete(root, state, tid, token, result, executor, error=None, usage=None, detail=""):
    t = state["tasks"][tid]
    now = time.time()
    if not error and t["kind"] not in {"build", "audit", "ledger"} and t.get("mode") != "python":
        try:
            validate_result(state, tid, result, executor, root)
        except (ContractError, TypeError, KeyError, AttributeError) as exc:
            error = str(exc)
            detail = "contract"
    elapsed = now - t["lease"]["started_at"]
    rel = str(Path(t["request"]).with_name("result.json"))
    envelope = {"task_id": tid, "input_hash": t["input_hash"], "executor": executor, "result": result,
                "error": error, "elapsed_seconds": elapsed, "usage": usage or {"tokens": None, "cost": None}}
    atomic_json(root / rel, envelope)
    semantic_fail = t["kind"] in {"review", "audit"} and not error and result.get("verdict") == "fail"
    t.update(status="failed" if error or semantic_fail else "done", output=rel, output_hash=file_hash(root / rel))
    t.pop("lease")
    failure = None
    if error:
        failure = ("contract" if detail == "contract" or python_task(t) else "timeout" if detail == "timeout"
                   else classify_error(error, detail))
        t["error"], t["error_class"] = error, failure
        t["cause"] = f"retry-after-{failure}"
        if failure == "transient":
            t["transient"] = t.get("transient", 0) + 1
            _backoff(state, t, now)
        elif failure == "structural":
            _structural(state, tid, t, now)
    else:
        for key in ("error", "error_class"):
            t.pop(key, None)
    if t["kind"] not in {"build", "audit", "ledger"} and t.get("mode") != "python":
        state["usage"]["elapsed_seconds"] += elapsed
    state["events"].append({"type": "attempt", "task_id": tid, "kind": t["kind"], "status": t["status"], "class": failure or ("semantic" if semantic_fail else None),
                            "cause": t.get("cause", "initial"), "attempt": t["attempts"], "elapsed_seconds": round(elapsed, 3),
                            "host": executor.get("host"), "input_hash": t["input_hash"], "output": rel, "time": now})
    if semantic_fail:
        _semantic_failure(state, tid, t, result, now)
    return envelope


def _structural(state, tid, t, now):
    """Host rejected the input as too large: lower the learned ceiling so budget layout reshards."""
    if t["kind"] in {"review", "review-part", "audit-part"} and t.get("packet_chars"):
        limits = state.setdefault("host_limits", {})
        limits["max_input_chars"] = min(limits.get("max_input_chars") or t["packet_chars"], t["packet_chars"] - 1)
        t["transient"] = t.get("transient", 0) + 1  # the unchanged input is not retried; layout replaces it
        state["events"].append({"type": "repair", "origin": "orchestration", "task_id": tid, "automatic": True,
                                "action": f"host input ceiling lowered to {limits['max_input_chars']}; review/audit work resharded",
                                "time": now})
    else:
        t["blocked"] = {"class": "structural", "reason": "host rejected input size; reduce chunk_chars or merge_fanout explicitly"}
        t["status"] = "blocked"
        state["events"].append({"type": "blocked", "task_id": tid, **t["blocked"], "time": now})


def _semantic_failure(state, tid, t, result, now):
    origin = "review" if t["kind"] == "review" else "audit"
    if stages.repair_rounds(state, origin) >= pv(state["policy"], "max_repair_rounds"):
        gaps = result.get("failed_units") or sorted(k for k, v in result.get("decisions", {}).items() if v.get("verdict") != "pass")
        t["blocked"] = {"class": "repair-budget", "reason": f"{origin} still failing after {stages.repair_rounds(state, origin)} repair rounds; "
                        "gaps isolated, not reported as complete", "gaps": gaps}
        t["status"] = "blocked"
        state["events"].append({"type": "blocked", "task_id": tid, **t["blocked"], "time": now})
        return
    routes = (stages.route_review_failure if origin == "review" else stages.route_audit_failure)(state, result, now)
    if origin == "review":
        state["tasks"]["synthesize"]["cause"] = "repair"
    for route in routes:
        for target in route.get("targets", []):
            if target in state["tasks"] and route["stage"] in {"read", "merge"}:
                state["tasks"][target]["cause"] = "repair"
    t["attempts"] = 0
    state["events"].append({"type": "repair", "origin": origin, "round": stages.repair_rounds(state, origin), "automatic": True,
                            "routes": routes, "time": now})


def collect(root, tid, token, result, executor, error=None, usage=None, detail=""):
    root = Path(root).resolve()
    with locked(root):
        state = read_state(root)
        check_sources(state)
        refresh(root, state, keep=token)
        t = state["tasks"].get(tid)
        if not t or t["status"] != "running" or t["lease"]["token"] != token:
            raise ContractError("stale/foreign lease; result cannot overwrite newer work")
        envelope = _complete(root, state, tid, token, result, executor, error, usage, detail)
        refresh(root, state)
        run_python_tasks(root, state, "collect")
        save(root, state)
        return envelope


def intervention(state, kind, reason, actor, **extra):
    state["events"].append({"type": "intervention", "kind": kind, "reason": text(reason, "reason"),
                            "actor": actor or "operator", **extra, "time": time.time()})


def blocked(state):
    return [{"task_id": tid, **t["blocked"]} for tid, t in state["tasks"].items() if t.get("blocked")]


def lifecycle(root, state):
    tasks = state["tasks"]
    tier = state.get("target_tier", "L2")
    done = lambda tid: tid in tasks and tasks[tid]["status"] == "done"
    stage = "queued"
    if any(t["kind"] == "read" and t["status"] in {"done", "running"} for t in tasks.values()):
        stage = "reading"
    if tier == "L1":
        if done("ledger"):
            stage = "material-ready"
    elif done("build"):
        bid = read_json(Path(root) / tasks["build"]["output"])["result"]["build_id"]
        evals = [e for e in state.get("evaluations", []) if e["build_id"] == bid]
        stage = ("delivered" if any(d["build_id"] == bid for d in state.get("deliveries", []))
                 else "tested" if any(e["status"] == "passed" for e in evals)
                 else "test-failed" if evals and evals[-1]["status"] == "failed" else "built")
    elif done("review"):
        stage = "reviewed"
    elif done("synthesize"):
        stage = "reconstructed"
    policy = state["policy"]
    exhausted = [tid for tid, t in tasks.items() if t["status"] == "failed" and not t.get("blocked") and
                 (t["attempts"] - t.get("transient", 0) >= policy["max_attempts"] or t.get("transient", 0) >= pv(policy, "max_transient_retries"))]
    return {"stage": stage, "target_tier": tier, "blocked": blocked(state), "failed": exhausted,
            "stale": [tid for tid, t in tasks.items() if t["status"] == "stale"],
            "note": "built 不等于 tested；L1 材料不等于 Skill delivered"}


def forecast(root, state):
    policy, usage, tasks = state["policy"], state["usage"], state["tasks"]
    remaining = [tid for tid, t in tasks.items() if t["status"] != "done" and not python_task(t)]
    reads = sum(state["units"][tid]["end"] - state["units"][tid]["start"] + 3000 for tid in remaining if tasks[tid]["kind"] == "read")
    done_sizes = {}
    for t in tasks.values():
        if t.get("packet_chars"):
            done_sizes.setdefault(t["kind"], []).append(t["packet_chars"])
    others = sum(sum(done_sizes[tasks[tid]["kind"]]) / len(done_sizes[tasks[tid]["kind"]])
                 for tid in remaining if tasks[tid]["kind"] != "read" and done_sizes.get(tasks[tid]["kind"]))
    unknown = [tid for tid in remaining if tasks[tid]["kind"] != "read" and not done_sizes.get(tasks[tid]["kind"])]
    shortfall = []
    if len(remaining) > policy["max_calls"] - usage["calls"]:
        shortfall.append(f"max_calls: at least {len(remaining)} semantic calls remain, {policy['max_calls'] - usage['calls']} left")
    if reads + others > policy["max_total_input_chars"] - usage["input_chars"]:
        shortfall.append(f"max_total_input_chars: estimate {int(reads + others)} remaining, {policy['max_total_input_chars'] - usage['input_chars']} left")
    return {"remaining_semantic_tasks": len(remaining), "estimated_input_chars": int(reads + others),
            "unestimated_tasks": unknown[:10], "shortfall": shortfall,
            "note": "字符估计不是 token/费用；重试、返修与分批复核另增调用"}


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
        now = time.time()
        ready = [tid for tid, t in state["tasks"].items() if not python_task(t) and eligible(state, t, now)]
        waiting = sorted((t["not_before"], tid) for tid, t in state["tasks"].items() if t.get("not_before", 0) > now)
        life = lifecycle(root, state)
        label = {"built": "built-pending-runtime", "test-failed": "built-pending-runtime", "tested": "tested-trial",
                 "delivered": "delivered", "material-ready": "material-ready"}.get(life["stage"], "pending")
        if label == "pending" and life["blocked"] and not ready and not waiting:
            label = "blocked"
        result = {"status": label, "lifecycle": life, "product": state["product"], "ready": ready,
                  "backoff": [{"task_id": tid, "not_before": at} for at, tid in waiting], "usage": state["usage"],
                  "stop_reason": state.get("stop_reason"), "forecast": forecast(root, state),
                  "layout": {k: {x: v[x] for x in ("mode", "parts", "part_limit", "packet_chars") if x in v} for k, v in state.get("layout", {}).items()},
                  "tasks": {tid: {k: t[k] for k in ("kind", "status", "attempts")} for tid, t in state["tasks"].items()}}
        if "build" in state["tasks"] and state["tasks"]["build"]["status"] == "done":
            result.update(read_json(root / state["tasks"]["build"]["output"])["result"])
        if state.get("layout_error"):
            result["layout_error"] = state["layout_error"]
        return result


def sync(root):
    with locked(root):
        state = read_state(root)
        before = sum(t["status"] == "done" for t in state["tasks"].values())
        reused = _plan(Path(root), state)
        after = sum(t["status"] == "done" for t in state["tasks"].values())
        state["events"].append({"type": "cache", "trigger": "sync", "reused": after, "invalidated": max(0, before - after),
                                "kept_at_plan": reused, "time": time.time()})
        save(root, state)
    return status(root)


def retry(root, tid, feedback, actor=None):
    with locked(root):
        state = read_state(root)
        if tid not in state["tasks"]:
            raise ContractError("unknown task")
        t = state["tasks"][tid]
        if t["status"] == "running":
            raise ContractError("task still leased; wait for expiry or worker completion")
        attempts = t["attempts"]
        if attempts - t.get("transient", 0) >= state["policy"]["max_attempts"]:
            raise ContractError("attempt budget exhausted; revise policy explicitly before more work")
        t["feedback"] = text(feedback, "feedback")
        t["status"] = "stale"
        t["cause"] = "manual-retry"
        for key in ("output_hash", "blocked", "not_before"):
            t.pop(key, None)
        refresh(root, state)
        t["attempts"] = attempts
        intervention(state, "retry", feedback, actor, task_id=tid)
        save(root, state)


def policy_set(root, changes, reason, actor=None):
    """Explicit, recorded policy change; consumed budget is never reset."""
    with locked(root):
        state = read_state(root)
        policy = dict(state["policy"])
        diff = {}
        for key, value in changes.items():
            if key not in DEFAULT_POLICY and key not in {"stage_timeout_seconds", "host_max_input_chars"}:
                raise ContractError(f"unknown policy field: {key}")
            if key in {"chunk_chars", "merge_fanout"}:
                raise ContractError("chunking changes the reading plan; start a new production root")
            diff[key] = [policy.get(key), value]
            policy[key] = value
        check_policy({**DEFAULT_POLICY, **policy})
        state["policy"] = policy
        for t in state["tasks"].values():
            if t.get("blocked", {}).get("class") in {"structural", "repair-budget"}:
                t.pop("blocked")
                t["status"] = "failed" if t.get("output") else "queued"
        if "max_repair_rounds" in changes:
            for t in state["tasks"].values():
                if t["kind"] in {"review", "audit"} and t["status"] == "failed" and t.get("output"):
                    result = read_json(Path(root) / t["output"])["result"]
                    if result.get("verdict") == "fail":
                        _semantic_failure(state, t["kind"], t, result, time.time())
        state.pop("stop_reason", None)
        intervention(state, "policy", reason, actor, changes=diff)
        save(root, state)
    return status(root)


def unblock(root, tid, reason, actor=None, accept_gaps=False):
    with locked(root):
        state = read_state(root)
        t = state["tasks"].get(tid)
        if not t or not t.get("blocked"):
            raise ContractError("task is not blocked")
        if accept_gaps:
            if t["kind"] != "audit":
                raise ContractError("only sampled-audit gaps can be accepted; they become declared limits")
            t["accepted_gaps"] = sorted(set(t.get("accepted_gaps", [])) | set(t["blocked"].get("gaps", [])))
        t.pop("blocked")
        t["status"] = "stale"
        t["attempts"] = 0
        t.pop("input_hash", None)
        intervention(state, "accept-gaps" if accept_gaps else "unblock", reason, actor, task_id=tid)
        refresh(root, state)
        save(root, state)
    return status(root)


def execute_one(root, command, owner):
    p = claim(root, owner)
    if not p:
        return False
    state = read_state(root)
    kind = p["stage"]
    executor = {"session_id": p["claim_token"], "host": "command", "model": "not-reported"}
    result, error, usage, detail = {}, None, None, ""
    log = Path(root) / state["tasks"][p["task_id"]]["request"]
    try:
        code, out, err, _ = run_worker(command, json.dumps(p, ensure_ascii=False), stage_timeout(state["policy"], kind), root)
        log.with_name("stdout.txt").write_text(out, encoding="utf-8")
        log.with_name("stderr.txt").write_text(err, encoding="utf-8")
        if code:
            detail = err
            raise ContractError(f"worker exited {code}: {error_line(err)}")
        response = decode_result(out)
        result, executor, usage = response["result"], response["executor"], response.get("usage")
    except WorkerTimeout as exc:
        error, detail = str(exc), "timeout"
    except (OSError, ContractError, KeyError) as exc:
        error = str(exc)
    try:
        collect(root, p["task_id"], p["claim_token"], result, executor, error, usage, detail)
    except ContractError as exc:
        # A newer claim owns the task (e.g. after sleep); keep the late result privately, continue the run.
        log.with_name("late-result.json").write_text(json.dumps({"error": str(exc), "result": result}, ensure_ascii=False), encoding="utf-8")
    return True


def next_wakeup(roots):
    times = []
    for root in roots:
        state = read_state(root)
        for t in state["tasks"].values():
            if t.get("not_before", 0) > time.time() and t["status"] == "failed" and not t.get("blocked"):
                times.append(t["not_before"])
    return min(times) if times else None


def run(roots, command, parallel=2, wait=True):
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
            if any(progressed):
                continue
            wake = next_wakeup(roots) if wait else None
            if wake is None or wake - time.time() > DEFAULT_POLICY["backoff_max_seconds"] * 2:
                break
            time.sleep(max(1, wake - time.time()))
    wall = time.time() - started
    for root in roots:
        with locked(root):
            state = read_state(root)
            state["events"].append({"type": "run", "owner": owner, "wall_seconds": round(wall, 3), "parallel": parallel,
                                    "roots": len(roots), "started": started, "time": time.time()})
            save(root, state)
    return {"wall_seconds": wall, "runs": [status(root) for root in roots]}


def parse_setting(item):
    key, sep, raw = item.partition("=")
    if not sep:
        raise ContractError("--set requires key=value")
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    return key, value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    subs = ap.add_subparsers(dest="command", required=True)
    p = subs.add_parser("init")
    p.add_argument("--root", type=Path, required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", action="append", type=Path)
    group.add_argument("--sources", type=Path, help="JSON list of {path, role, period, url?, access?, retrieved_at?, genres?, body?}")
    for key in ("id", "title", "period", "purpose"):
        p.add_argument(f"--{key}", required=True)
    p.add_argument("--object", choices=("book", "person"), default="book")
    p.add_argument("--profile", action="append", choices=KINDS, required=True)
    p.add_argument("--genre", action="append", choices=stages.GENRES, help="content template(s); default follows purpose")
    p.add_argument("--source-role", default="primary-text")
    p.add_argument("--edition")
    p.add_argument("--translator")
    p.add_argument("--body-start", help="first text of the declared body; earlier text is recorded as excluded")
    p.add_argument("--body-end", help="first text after the declared body")
    p.add_argument("--issue", action="append", default=[], help="declared OCR/missing-page/appendix/translator-note issue")
    p.add_argument("--target-tier", choices=TIERS, default="L2")
    p.add_argument("--host", choices=("command", "assisted", "unspecified"), default="unspecified")
    p.add_argument("--policy", type=Path)
    p.add_argument("--prompts", type=Path, help="pinned stage module set (default production-modules.json)")
    for name in ("status", "sync", "claim", "collect", "retry", "policy", "unblock", "metrics", "failures"):
        p = subs.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        if name == "claim":
            p.add_argument("--owner", required=True)
            p.add_argument("--task")
        if name == "collect":
            p.add_argument("--response", type=Path, required=True)
        if name in {"retry", "policy", "unblock"}:
            p.add_argument("--actor", default="operator")
        if name == "retry":
            p.add_argument("--task", required=True)
            p.add_argument("--feedback", required=True)
        if name == "policy":
            p.add_argument("--set", action="append", required=True, metavar="KEY=JSON")
            p.add_argument("--reason", required=True)
        if name == "unblock":
            p.add_argument("--task", required=True)
            p.add_argument("--reason", required=True)
            p.add_argument("--accept-gaps", action="store_true")
    p = subs.add_parser("run")
    p.add_argument("--root", action="append", type=Path, required=True)
    p.add_argument("--worker", type=Path, required=True, help="JSON file containing argv list")
    p.add_argument("--parallel", type=int, default=2)
    p.add_argument("--no-wait", action="store_true", help="exit instead of waiting for transient backoff")
    for name in ("evaluate", "cycle"):
        p = subs.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        p.add_argument("--suite", type=Path, required=True)
        p.add_argument("--source-context", type=Path, required=True)
        p.add_argument("--worker", type=Path, required=name == "cycle")
        p.add_argument("--loading", choices=("inline", "host"), default="inline")
        if name == "cycle":
            p.add_argument("--max-rounds", type=int, default=2)
            p.add_argument("--parallel", type=int, default=2)
    p = subs.add_parser("attach")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--evaluation", type=Path, required=True)
    p = subs.add_parser("repair")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--evaluation", type=Path, required=True)
    p.add_argument("--use-held-out", action="store_true", help="feed held-out failures back; those cases stop counting as held-out")
    p = subs.add_parser("deliver")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--ws", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--replace", action="store_true")
    p = subs.add_parser("record")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--regression", type=Path, help="captured make e2e output")
    p.add_argument("--portfolio", type=Path, help="exported portfolio directory")
    p.add_argument("--baseline", type=Path, help="serial/baseline production root with the same scope")
    args = ap.parse_args()
    try:
        if args.command == "init":
            product = {key: getattr(args, key) for key in ("id", "title", "object", "period", "purpose")}
            product["profiles"] = args.profile
            for key in ("edition", "translator"):
                if getattr(args, key):
                    product[key] = getattr(args, key)
            if args.genre:
                product["genres"] = args.genre
            body = {k: v for k, v in (("start_marker", args.body_start), ("end_marker", args.body_end)) if v}
            if args.sources:
                sources = read_json(args.sources)
                if not isinstance(sources, list) or not sources:
                    raise ContractError("--sources must be a nonempty JSON list")
                base = args.sources.parent
                sources = [{**s, "path": str((base / s["path"]).resolve())} for s in sources]
            else:
                sources = [{"path": str(p), "role": args.source_role, "period": args.period, "declared_issues": args.issue,
                            **({"body": body} if body else {})} for p in args.source]
            init(args.root, sources, product, read_json(args.policy) if args.policy else None, args.prompts, args.target_tier, args.host)
            result = status(args.root)
        elif args.command == "status":
            result = status(args.root)
        elif args.command == "sync":
            result = sync(args.root)
        elif args.command == "claim":
            result = claim(args.root, args.owner, args.task)
        elif args.command == "collect":
            response = read_json(args.response)
            result = collect(args.root, response["task_id"], response["claim_token"], response["result"], response["executor"],
                             response.get("error"), usage=response.get("usage"))
        elif args.command == "retry":
            retry(args.root, args.task, args.feedback, args.actor)
            result = status(args.root)
        elif args.command == "policy":
            result = policy_set(args.root, dict(parse_setting(x) for x in args.set), args.reason, args.actor)
        elif args.command == "unblock":
            result = unblock(args.root, args.task, args.reason, args.actor, args.accept_gaps)
        elif args.command in {"metrics", "failures"}:
            import production_metrics as metrics
            result = metrics.metrics(args.root) if args.command == "metrics" else metrics.failures(args.root)
        elif args.command == "run":
            if args.parallel < 1:
                raise ContractError("parallel must be positive")
            result = run(args.root, read_json(args.worker), args.parallel, not args.no_wait)
        else:
            import production_loop as loop
            if args.command == "evaluate":
                result = loop.evaluate(args.root, args.suite, read_json(args.source_context),
                                       read_json(args.worker) if args.worker else None, args.loading)
            elif args.command == "cycle":
                result = loop.cycle(args.root, args.suite, read_json(args.source_context), read_json(args.worker),
                                    args.max_rounds, args.parallel, args.loading)
            elif args.command == "attach":
                result = loop.attach(args.root, args.evaluation)
            elif args.command == "repair":
                result = loop.repair_from_evaluation(args.root, args.evaluation, args.use_held_out)
            elif args.command == "deliver":
                result = loop.deliver(args.root, args.ws, args.out, args.replace)
            else:
                result = loop.record(args.root, args.regression, args.portfolio, args.baseline)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, KeyError, TypeError) as exc:
        ap.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
