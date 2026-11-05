"""Single-book loop: evaluate the built package, trace failures to stages, repair, deliver, record.

Evaluation failures are routed by the independent reviewer's observable attribution:
missing source qualifiers -> read units of the affected capabilities; relation, voice,
trigger or example problems -> synthesis; entry/index/loading -> workflow issue (builder);
evaluator problems -> evaluator calibration. Unknown attribution escalates from synthesis
to reading on repeat. A later evaluation of the same case confirms or refutes it.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import time

from book_skill_common import ContractError, digest, read_json, tree_hashes
from production_common import VERSION, atomic_json, locked
import production as prod
import production_stages as stages
from production_eval import execute, prepare, report


def current_build(root, state):
    t = state["tasks"].get("build")
    if not t or t["status"] != "done":
        raise ContractError("no current build; run production until the package is built")
    built = read_json(Path(root) / t["output"])["result"]
    return built, Path(root) / built["package"]


def _bound(root, state, accepted):
    built, package = current_build(root, state)
    if (accepted["variant"] != "candidate" or accepted["build_id"] != built["build_id"]
            or accepted["package_sha256"] != digest(tree_hashes(package))):
        raise ContractError("evaluation does not bind the current production build")
    return built


def evaluate(root, suite, source_context, worker=None, loading="inline"):
    root = Path(root).resolve()
    prod.status(root)
    state = prod.read_state(root)
    built, package = current_build(root, state)
    n = len(state.get("evaluations", [])) + 1
    run = root / "evaluations" / f"{built['build_id'][:12]}-{n:02d}"
    while run.exists():
        n += 1
        run = root / "evaluations" / f"{built['build_id'][:12]}-{n:02d}"
    prepare(package, suite, run, source_context, "candidate", loading, production=root, consumed=state.get("consumed_held_out"))
    if not worker:
        return {"status": "prepared", "run": str(run), "next": "answer and review with production_eval.py packets, then production.py attach"}
    execute(run, worker)
    return attach(root, run)


def attach(root, run):
    root, run = Path(root).resolve(), Path(run).resolve()
    accepted = report(run)
    with locked(root):
        state = prod.read_state(root)
        built = _bound(root, state, accepted)
        rel = str(run.relative_to(root)) if run.is_relative_to(root) else str(run)
        failed = [c["id"] for c in accepted["cases"] if not c["passed"]]
        record = {"run": rel, "build_id": built["build_id"], "status": accepted["status"], "loading": accepted.get("loading", "inline-v1"),
                  "failed_cases": failed, "held_out_failed": accepted.get("held_out_failed", []),
                  "evidence_sha256": accepted["evidence_sha256"], "time": time.time()}
        evaluations = [e for e in state.get("evaluations", []) if e["run"] != rel]
        state["evaluations"] = evaluations + [record]
        results = {c["id"]: c["passed"] for c in accepted["cases"]}
        for item in state.get("attributions", []):
            if item["status"] == "pending-verification" and item["case"] in results and item["run"] != str(run):
                item["status"] = "confirmed-by-rerun" if results[item["case"]] else "not-confirmed"
                item["verified_by"] = rel
        state["events"].append({"type": "evaluation", "run": rel, "status": accepted["status"], "build_id": built["build_id"], "time": time.time()})
        prod.save(root, state)
    return {**record, "run_path": str(run), "attributions": accepted.get("attributions", {}), "coverage_complete": accepted["coverage_complete"]}


def _evidence_units(model, capabilities):
    caps = {c["id"]: c["evidence"] for c in model["capabilities"]}
    return sorted({u for c in capabilities for u in caps.get(c, [])})


def repair_from_evaluation(root, run, use_held_out=False, actor=None):
    root, run = Path(root).resolve(), Path(run).resolve()
    accepted = report(run)
    if accepted["status"] != "failed":
        return {"status": "nothing-to-repair", "evaluation": accepted["status"]}
    suite = {c["id"]: c for c in read_json(run / "suite.json")["cases"]}
    with locked(root):
        state = prod.read_state(root)
        prod.check_sources(state)
        prod.refresh(root, state)
        built = _bound(root, state, accepted)
        rounds = stages.repair_rounds(state, "evaluation")
        if rounds >= prod.pv(state["policy"], "max_repair_rounds"):
            raise ContractError(f"evaluation repair budget exhausted after {rounds} rounds; failures stay listed, not reported as passed")
        model = read_json(run / "relocated/skill/references/capabilities.json")["model"]
        failed = [c for c in accepted["cases"] if not c["passed"]]
        used = [c for c in failed if not suite[c["id"]]["held_out"] or use_held_out]
        if not used:
            return {"status": "held-out-only-failures", "held_out_failed": [c["id"] for c in failed],
                    "next": "the package fails held-out cases; replace them with new held-out cases after any repair, or revise scope"}
        history = state.setdefault("attributions", [])
        reads, synth, records = {}, [], []
        for case in used:
            cid = case["id"]
            for item in accepted["attributions"].get(cid, []) or [{"stage": "unknown", "capabilities": [], "problem": "unattributed failure", "evidence": "-"}]:
                caps = item["capabilities"] or suite[cid]["targets"]
                stage = item["stage"]
                if stage == "unknown":
                    tried = [h for h in history if h["case"] == cid and h["routed_to"] == "synthesize" and h["status"] == "not-confirmed"]
                    stage = "read" if tried else "synthesize"
                route = {"read": "read", "synthesize": "synthesize", "examples": "synthesize",
                         "build": "workflow:build", "evaluation": "workflow:evaluator"}[stage]
                problem = {"case": cid, "stage": item["stage"], "capabilities": caps, "problem": item["problem"], "evidence": item["evidence"]}
                if route == "read":
                    for uid in _evidence_units(model, caps):
                        reads.setdefault(uid, []).append(problem)
                    synth.append(problem)
                elif route == "synthesize":
                    synth.append(problem)
                records.append({"case": cid, "stage": item["stage"], "routed_to": route, "capabilities": caps,
                                "problem": item["problem"], "evidence": item["evidence"], "run": str(run), "build_id": built["build_id"],
                                "round": rounds + 1, "status": "pending-verification" if route in {"read", "synthesize"}
                                else "workflow-issue" if route == "workflow:build" else "evaluator-issue"})
        tasks = state["tasks"]
        for uid, problems in reads.items():
            tasks[uid]["feedback"] = {"origin": "evaluation", "problems": problems}
            stages.reset(tasks[uid])
            tasks[uid]["cause"] = "repair"
        if synth:
            tasks["synthesize"]["feedback"] = {"origin": "evaluation", "problems": synth}
            stages.reset(tasks["synthesize"])
            tasks["synthesize"]["cause"] = "repair"
        history.extend(records)
        if use_held_out:
            consumed = state.setdefault("consumed_held_out", {})
            for case in used:
                if suite[case["id"]]["held_out"]:
                    consumed[case["id"]] = digest(suite[case["id"]]["turns"])
            prod.intervention(state, "held-out-feedback", "held-out failures fed back; those cases no longer count as held-out", actor,
                              cases=[c["id"] for c in used if suite[c["id"]]["held_out"]])
        if reads or synth:
            state.setdefault("repairs", {})["evaluation"] = rounds + 1
        state["events"].append({"type": "repair", "origin": "evaluation", "round": rounds + 1, "automatic": True,
                                "routes": [{"stage": "read", "targets": sorted(reads)}] * bool(reads)
                                          + [{"stage": "synthesize", "targets": sorted({c for p in synth for c in p["capabilities"]})}] * bool(synth),
                                "workflow_issues": [r for r in records if r["routed_to"].startswith("workflow")], "time": time.time()})
        prod.refresh(root, state)
        prod.save(root, state)
    return {"status": "repair-scheduled" if reads or synth else "no-product-route", "read_units": sorted(reads),
            "synthesize": bool(synth), "workflow_issues": [r for r in records if r["routed_to"].startswith("workflow")],
            "held_out_not_used": [c["id"] for c in failed if suite[c["id"]]["held_out"] and not use_held_out]}


def cycle(root, suite, source_context, worker, max_rounds=2, parallel=2, loading="inline"):
    """Run -> evaluate -> attribute -> repair, bounded; never declares a pass the evaluation did not give."""
    root = Path(root).resolve()
    history = []
    for round_no in range(max_rounds + 1):
        prod.run([root], worker, parallel)
        current = prod.status(root)
        stage = current["lifecycle"]["stage"]
        if stage == "tested":
            return {"status": "passed", "rounds": history, "build_id": current.get("build_id")}
        if stage not in {"built", "test-failed"}:
            return {"status": "stopped-before-test", "stage": stage, "blocked": current["lifecycle"]["blocked"],
                    "stop_reason": current.get("stop_reason"), "rounds": history}
        evaluated = evaluate(root, suite, source_context, worker, loading)
        history.append({"round": round_no, "build_id": evaluated["build_id"], "evaluation": evaluated["status"],
                        "failed_cases": evaluated["failed_cases"]})
        if evaluated["status"] == "passed":
            return {"status": "passed", "rounds": history, "build_id": evaluated["build_id"]}
        if evaluated["status"] != "failed" or round_no == max_rounds:
            break
        repaired = repair_from_evaluation(root, root / evaluated["run"])
        history[-1]["repair"] = repaired["status"]
        if repaired["status"] != "repair-scheduled":
            break
    return {"status": "not-passed", "rounds": history}


def deliver(root, ws, out, replace=False):
    import skill_portfolio
    root = Path(root).resolve()
    prod.status(root)
    state = prod.read_state(root)
    built, package = current_build(root, state)
    passed = [e for e in state.get("evaluations", []) if e["build_id"] == built["build_id"] and e["status"] == "passed"]
    if not passed:
        raise ContractError("delivery requires a passed evaluation bound to the current build")
    run = Path(passed[-1]["run"])
    run = run if run.is_absolute() else root / run
    skill_portfolio.register(ws, package, run)
    manifest = skill_portfolio.export(ws, out, None, replace)
    with locked(root):
        state = prod.read_state(root)
        state.setdefault("deliveries", []).append({"build_id": built["build_id"], "out": str(Path(out).resolve()),
                                                   "portfolio_sha256": digest(manifest), "time": time.time()})
        state["events"].append({"type": "delivery", "build_id": built["build_id"], "time": time.time()})
        prod.save(root, state)
    return {"status": "delivered", "build_id": built["build_id"], "portfolio": str(out), "entries": len(manifest["entries"])}


def _git():
    plugin = Path(__file__).resolve().parents[1]
    try:
        head = subprocess.run(["git", "-C", str(plugin), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(plugin), "status", "--porcelain", "--", "bridge", "skills"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return {"commit": head or None, "uncommitted_changes": bool(dirty)}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "uncommitted_changes": None}


def record(root, regression=None, portfolio=None, baseline=None):
    """Seven separately evidenced items; none is inferred from another."""
    import production_metrics as metrics
    root = Path(root).resolve()
    status = prod.status(root)
    state = prod.read_state(root)
    modules = stages.module_data(state)
    items = {"code_implemented": {"status": "recorded", "evidence": {"workflow_version": VERSION, "modules_version": modules.get("version", "0.5.0-flat"),
                                                                     "modules_sha256": digest(modules), **_git()}}}
    if regression:
        body = Path(regression).read_text(encoding="utf-8")
        ok = "\nOK" in body or body.startswith("OK")
        ran = next((line for line in body.splitlines() if line.startswith("Ran ")), None)
        items["contract_regression"] = {"status": "passed" if ok and ran else "failed", "evidence": {"log_sha256": digest(body.encode()), "summary": ran}}
    else:
        items["contract_regression"] = {"status": "not-recorded", "evidence": None}
    evals = state.get("evaluations", [])
    build = status.get("build_id")
    current = [e for e in evals if e["build_id"] == build]
    if state.get("target_tier") == "L1":
        items["skill_usable_in_scope"] = {"status": "not-applicable", "evidence": "L1 material is not a Skill"}
    elif current:
        latest = current[-1]
        items["skill_usable_in_scope"] = {"status": latest["status"], "evidence": {k: latest[k] for k in ("run", "evidence_sha256", "loading", "failed_cases")}}
    else:
        items["skill_usable_in_scope"] = {"status": "not-tested", "evidence": None}
    if portfolio:
        import skill_portfolio
        try:
            manifest = skill_portfolio.verify_portfolio(portfolio)
            hit = [e for e in manifest["entries"] if (e.get("package", {}).get("build_id") or e.get("build_id")) == build]
            items["portfolio_usable"] = {"status": "passed" if hit else "missing-current-build", "evidence": {"portfolio_sha256": digest(manifest)}}
        except (ContractError, OSError) as exc:
            items["portfolio_usable"] = {"status": "failed", "evidence": str(exc)}
    else:
        items["portfolio_usable"] = {"status": "not-checked", "evidence": None}
    passed = [e for e in current if e["status"] == "passed"]
    items["relocated_run_passed"] = {"status": "passed" if passed else "not-observed",
                                     "evidence": {"inline_relocated": any(e["loading"] in {"inline", "inline-v1"} for e in passed),
                                                  "host_discovered": any(e["loading"] == "host" for e in passed)}}
    if baseline:
        try:
            items["productivity_observed"] = {"status": "observed", "evidence": metrics.compare(baseline, root)}
        except ContractError as exc:
            items["productivity_observed"] = {"status": "not-comparable", "evidence": str(exc)}
    else:
        items["productivity_observed"] = {"status": "not-observed", "evidence": "no same-scope baseline run supplied"}
    items["l3_accepted"] = {"status": "not-applicable", "evidence": "trial line never grants L3; formal acceptance stays on evaluate-and-publish"}
    result = {"schema_version": "delivery-record/1", "product": state["product"]["id"], "build_id": build,
              "lifecycle": status["lifecycle"]["stage"], "items": items, "time": time.time(),
              "rule": "各项分别取证；材料文件、导出统计或目标项目接口不能替代 Skill 的真实运行表现"}
    atomic_json(root / "delivery-record.json", result)
    return result
