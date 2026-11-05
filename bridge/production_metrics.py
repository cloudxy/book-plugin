"""Productivity and failure records of one production run; cross-run comparison.

Quality and cost are reported separately: wall time, summed task time, tokens,
calls, interventions, automatic repairs, first-pass rates, repeats and reuse.
Unknown values stay unknown; earlier 0.5.0 runs only expose what they recorded.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path

from book_skill_common import ContractError, digest, read_json
from production import INTERVENTIONS, read_state


def _numbers(target, usage):
    for key, value in (usage or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            target[key] += value


def _attempt_events(state):
    out = []
    for e in state["events"]:
        if e.get("type") == "attempt":
            out.append(e)
        elif "type" not in e and "task_id" in e and "status" in e:  # 0.5.0 status event
            out.append({**e, "kind": state["tasks"].get(e["task_id"], {}).get("kind"), "legacy": True})
    return out


def _interventions(state):
    items = [e for e in state["events"] if e.get("type") == "intervention" and e.get("kind") in INTERVENTIONS]
    items += [{"kind": "policy", "legacy": True, "reason": e.get("note"), "time": e.get("ts")} for e in state["events"]
              if "type" not in e and e.get("kind") == "policy_adjust"]
    return items


def tokens(root, state):
    """Every recorded attempt counts, including failures, retries and reviews."""
    total, missing = Counter(), 0
    for path in Path(root).glob("attempts/*/*/result.json"):
        usage = read_json(path).get("usage") or {}
        numeric = {k: v for k, v in usage.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if numeric:
            _numbers(total, numeric)
        elif read_json(path).get("executor", {}).get("host") != "python":
            missing += 1
    return dict(total), missing


def evaluation_cost(root, state):
    total, calls, seconds = Counter(), 0, 0.0
    for item in state.get("evaluations", []):
        run = Path(item["run"]) if Path(item["run"]).is_absolute() else Path(root) / item["run"]
        for log in run.glob("logs/*.json"):
            record = read_json(log)
            calls += 1
            seconds += record.get("elapsed_seconds") or 0
            try:
                _numbers(total, json.loads(record.get("stdout") or "{}").get("usage"))
            except ValueError:
                pass
    return {"calls": calls, "seconds": round(seconds, 1), "tokens": dict(total)}


def metrics(root):
    root = Path(root).resolve()
    state = read_state(root)
    attempts = _attempt_events(state)
    by_task = defaultdict(list)
    for e in attempts:
        by_task[e["task_id"]].append(e)
    first_pass = defaultdict(lambda: {"tasks": 0, "first_pass": 0})
    repeats = Counter()
    for tid, items in by_task.items():
        kind = items[0].get("kind") or "removed"
        if kind in {"build", "audit", "ledger"} or items[0].get("host") == "python":
            continue
        first_pass[kind]["tasks"] += 1
        first_pass[kind]["first_pass"] += items[0]["status"] == "done"
        for previous, current in zip(items, items[1:]):
            cause = current.get("cause") or ("retry-after-failure" if previous["status"] != "done" else "rerun-after-change")
            repeats[cause] += 1
    for value in first_pass.values():
        value["rate"] = round(value["first_pass"] / value["tasks"], 3) if value["tasks"] else None
    interventions = _interventions(state)
    repairs = [e for e in state["events"] if e.get("type") == "repair"]
    runs = [e for e in state["events"] if e.get("type") == "run"]
    cache = [e for e in state["events"] if e.get("type") == "cache"]
    token_total, missing = tokens(root, state)
    evaluations = state.get("evaluations", [])
    passed = [e for e in evaluations if e["status"] == "passed"]
    classes = Counter(e.get("class") for e in attempts if e.get("class"))
    return {"product": state["product"]["id"], "target_tier": state.get("target_tier", "L2"),
            "workflow_version": state.get("workflow_version"),
            "first_usable_skill_seconds": round(passed[0]["time"] - state["created_at"], 1) if passed else None,
            "wall_seconds_recorded": round(sum(e["wall_seconds"] for e in runs), 1) if runs else None,
            "task_seconds": round(state["usage"]["elapsed_seconds"], 1), "calls": state["usage"]["calls"],
            "input_chars": state["usage"]["input_chars"],
            "tokens": token_total, "attempts_without_token_report": missing, "cost": None,
            "evaluation": evaluation_cost(root, state),
            "interventions": {"count": len(interventions), "by_kind": dict(Counter(e["kind"] for e in interventions))},
            "automatic_repairs": {"count": sum(bool(e.get("automatic")) for e in repairs),
                                  "by_origin": dict(Counter(e.get("origin") for e in repairs if e.get("automatic")))},
            "stage_first_pass": dict(first_pass), "repeated_calls": dict(repeats), "failure_classes": dict(classes),
            "assisted_attempts": sum(1 for e in attempts if e.get("host") not in {None, "command", "python", "codex-cli"}),
            "cache": {"sync_reused": sum(e.get("reused", 0) for e in cache), "sync_invalidated": sum(e.get("invalidated", 0) for e in cache)},
            "parallel_settings": sorted({e["parallel"] for e in runs}),
            "quality": {"evaluations": len(evaluations), "latest": evaluations[-1] if evaluations else None},
            "limits": ["wall time is recorded only for runs started with 0.5.2 or later",
                       "cost stays unknown unless the host reports it; token fields are what the host emitted",
                       "0.5.0 events carry no cause/class; their repeats are inferred from order",
                       "parallel wall time and summed task time are different quantities"]}


def failures(root):
    """Observable failures traced to stages; input for the cross-book workflow loop."""
    root = Path(root).resolve()
    state = read_state(root)
    items = []
    for e in _attempt_events(state):
        if e["status"] in {"failed", "blocked"}:
            klass = e.get("class")
            if not klass and e.get("output"):
                try:
                    envelope = read_json(root / e["output"])
                    klass = "semantic" if not envelope.get("error") else "legacy-error"
                except ContractError:
                    klass = "unknown"
            items.append({"stage": e.get("kind"), "class": klass, "task_id": e["task_id"], "source": "attempt"})
    for e in state["events"]:
        if e.get("type") == "repair":
            for route in e.get("routes", []) or [{"stage": "orchestration", "targets": []}]:
                items.append({"stage": route.get("stage", "orchestration"), "class": f"repair:{e.get('origin')}", "source": "repair",
                              "targets": route.get("targets", [])[:20]})
        if e.get("type") == "blocked":
            items.append({"stage": e.get("task_id"), "class": f"blocked:{e.get('class')}", "source": "blocked"})
    for a in state.get("attributions", []):
        items.append({"stage": a["stage"], "class": f"evaluation:{a['status']}", "source": "evaluation", "case": a["case"]})
    for e in _interventions(state):
        items.append({"stage": "orchestration", "class": f"intervention:{e['kind']}", "source": "intervention"})
    summary = Counter((i["stage"], i["class"]) for i in items)
    return {"product": state["product"]["id"], "profiles": state["product"]["profiles"],
            "genres": state["product"].get("genres"), "items": items,
            "by_stage": [{"stage": s, "class": c, "count": n} for (s, c), n in sorted(summary.items(), key=lambda x: -x[1])]}


def comparable(a, b):
    sources = lambda s: [{k: x[k] for k in ("raw_sha256", "role", "period")} for x in s["sources"]]
    scope = lambda s: {k: s["product"].get(k) for k in ("object", "profiles", "period", "purpose")}
    if sources(a) != sources(b) or scope(a) != scope(b) or a.get("target_tier", "L2") != b.get("target_tier", "L2"):
        raise ContractError("productivity comparison requires the same sources, scope and target tier")


def compare(baseline, candidate):
    a, b = read_state(baseline), read_state(candidate)
    comparable(a, b)
    ma, mb = metrics(baseline), metrics(candidate)
    keys = ("wall_seconds_recorded", "task_seconds", "calls", "input_chars", "tokens", "interventions", "automatic_repairs",
            "stage_first_pass", "repeated_calls", "first_usable_skill_seconds", "evaluation", "parallel_settings")
    latest = lambda m: (m["quality"]["latest"] or {}).get("status")
    return {"status": "observation-only", "baseline": {k: ma[k] for k in keys}, "candidate": {k: mb[k] for k in keys},
            "baseline_serial": ma["parallel_settings"] == [1], "quality": {"baseline": latest(ma), "candidate": latest(mb)},
            "source_sha256": digest([s["raw_sha256"] for s in a["sources"]]),
            "limits": ["equal quality must be shown by evaluations bound to each build before cost differences mean anything",
                       "one book cannot establish a general speed-up; report observations, not percentages"]}
