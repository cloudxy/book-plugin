"""Actual, isolated trial-Skill use, independent review, and bound acceptance.

The evaluation suite stays outside the runtime package. Command workers receive
one turn at a time; all model answers/reviews and failures remain in private runs.
Packet version 1 runs keep their original packets so recorded bindings stay valid.
Version 2 adds purpose dimensions, failure attribution and host-discovered loading.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

from book_skill_common import ContractError, digest, read_json, slug, text, tree_hashes
from production_common import (WorkerTimeout, atomic_json, classify_error, decode_result, error_line, file_hash, locked,
                               run_worker, strings)
from distill_skill import verify

GROUPS = {"direct", "combine", "changed", "correction", "deliver", "boundary"}
DIMENSIONS = {"fidelity", "application", "utility"}
PURPOSE_DIMENSIONS = {"thought": "cognition", "expression": "expression"}
NOT_APPLICABLE = {"cognition": "用途不含思想/作者认知：按方案不测作者认知，知识包不强制作者画像",
                  "expression": "用途不含表达：不测作者表达或口吻"}
DELIVERABLES = {"explanation", "calculation", "plan", "judgment", "narrative", "expression"}
ATTRIBUTION = {"read", "synthesize", "examples", "build", "evaluation", "unknown"}
RETRY = {"max_attempts": 4, "backoff_seconds": 30, "backoff_max_seconds": 600}


def clean_sources(value):
    if not isinstance(value, dict):
        raise ContractError("source context object required")
    docs = value.get("documents")
    if docs is None and isinstance(value.get("text"), str):
        docs = [value]
    if not isinstance(docs, list) or not docs:
        raise ContractError("actual source documents required for fidelity review")
    cleaned = []
    for doc in docs:
        text(doc.get("text"), "source document text")
        cleaned.append({k: v for k, v in doc.items() if k in {"id", "text", "title", "role", "period", "url", "scope", "author"}})
    return {"documents": cleaned}


def dimensions(config):
    return config.get("dimensions") or sorted(DIMENSIONS)


def failing(config, result):
    dims = result["dimensions"]
    return bool(result["hard_failures"]) or any(dims[d]["score"] < 2 for d in dimensions(config))


def validate_review_response(run, response, packet):
    config = read_json(Path(run) / "config.json")
    for field in ("session_id", "host", "model"):
        text(response.get("executor", {}).get(field), f"reviewer.{field}")
    sessions = {read_json(p)["executor"]["session_id"] for p in (Path(run) / "answers").glob("*/*.json")}
    sessions.update(config.get("generation_sessions", []))
    if response["executor"]["session_id"] in sessions:
        raise ContractError("review session participated in generation or answering")
    result = response.get("result", {})
    if set(result.get("dimensions", {})) != set(dimensions(config)):
        raise ContractError("review dimensions required")
    for dim, value in result["dimensions"].items():
        if type(value.get("score")) is not int or not 0 <= value["score"] <= 3:
            raise ContractError("invalid score")
        text(value.get("reason"), f"{dim}.reason")
        excerpt = text(value.get("excerpt"), f"{dim}.excerpt")
        if not any(excerpt in a for a in packet["answers"]):
            raise ContractError("review excerpt not present in actual answers")
    strings(result.get("hard_failures"), "hard_failures", allow_empty=True)
    if config.get("packet_version", 1) >= 2:
        items = result.get("attribution")
        if not isinstance(items, list):
            raise ContractError("attribution list required (empty when the case passes)")
        for item in items:
            if item.get("stage") not in ATTRIBUTION:
                raise ContractError("attribution stage must be read/synthesize/examples/build/evaluation/unknown")
            if not set(strings(item.get("capabilities"), "attribution.capabilities", allow_empty=True)) <= set(config["targets"]):
                raise ContractError("attribution names unknown capabilities")
            text(item.get("problem"), "attribution.problem")
            text(item.get("evidence"), "attribution.evidence")
        if failing(config, result) and not items:
            raise ContractError("failed case requires attribution to a production stage")


def cases(suite, manifest):
    items = suite.get("cases")
    if suite.get("schema_version") != "production-eval/1" or not isinstance(items, list) or not items:
        raise ContractError("production-eval/1 cases required")
    profiles = manifest.get("product", {}).get("profiles", [])
    known = set()
    for case in items:
        cid = slug(case.get("id"))
        if cid in known:
            raise ContractError("duplicate case")
        known.add(cid)
        if case.get("group") not in GROUPS:
            raise ContractError("unknown case group")
        strings(case.get("turns"), "case.turns")
        text(case.get("rubric"), "case.rubric")
        strings(case.get("targets"), "case.targets")
        if case.get("condition") not in {"normal", "changed"}:
            raise ContractError("case.condition required")
        if case["group"] == "changed" and case["condition"] != "changed":
            raise ContractError("changed group must test changed conditions")
        if case["group"] == "correction" and len(case["turns"]) < 2:
            raise ContractError("correction requires sequential multiple turns")
        if type(case.get("held_out")) is not bool:
            raise ContractError("held_out flag required")
        if "deliverable" in case:
            if case["deliverable"] not in DELIVERABLES:
                raise ContractError("deliverable must be explanation/calculation/plan/judgment/narrative/expression")
            if case["deliverable"] == "expression" and "expression" not in profiles:
                raise ContractError("expression deliverables only test packages with an expression purpose")
    return items


def production_sessions(production):
    """Every session that produced or reviewed the package is excluded from answer review."""
    sessions = set()
    for result in Path(production).glob("attempts/*/*/result.json"):
        executor = read_json(result).get("executor", {})
        if executor.get("session_id") and executor.get("host") != "python":
            sessions.add(executor["session_id"])
    return sorted(sessions)


def prepare(candidate, suite_path, run, source_context, variant="candidate", loading="inline", production=None, consumed=None):
    candidate, run = Path(candidate).resolve(), Path(run).resolve()
    manifest = verify(candidate)
    suite = read_json(suite_path)
    items = cases(suite, manifest)
    model = read_json(candidate / "references/capabilities.json")["model"]
    ids = {c["id"] for c in model["capabilities"]}
    if any(not set(c["targets"]) <= ids for c in items):
        raise ContractError("unknown capability in case targets")
    reused = [c["id"] for c in items if c["held_out"] and digest(c["turns"]) in set((consumed or {}).values())]
    if reused:
        raise ContractError(f"held-out cases already fed back into production; replace them: {reused}")
    if run.exists():
        raise ContractError("use a new evaluation directory; do not overwrite history")
    if run.is_relative_to(candidate):
        raise ContractError("evaluation must be outside runtime package")
    if variant not in {"candidate", "none"}:
        raise ContractError("variant must be candidate/none")
    if loading not in {"inline", "host"}:
        raise ContractError("loading must be inline/host")
    generation_sessions = source_context.get("generation_sessions", [])
    strings(generation_sessions, "generation_sessions", allow_empty=True)
    if production:
        generation_sessions = sorted(set(generation_sessions) | set(production_sessions(production)))
    if not generation_sessions:
        raise ContractError("generation sessions required to prove reviewer independence (pass the production root)")
    source_context = clean_sources(source_context)
    run.mkdir(parents=True)
    shutil.copytree(candidate, run / "relocated/skill")
    verify(run / "relocated/skill")
    atomic_json(run / "suite.json", suite)
    atomic_json(run / "source-context.json", source_context)
    profiles = manifest["product"].get("profiles", [])
    dims = sorted(DIMENSIONS | {PURPOSE_DIMENSIONS[p] for p in profiles if p in PURPOSE_DIMENSIONS})
    config = {"schema_version": "production-eval/1", "packet_version": 2, "build_id": manifest["build_id"], "variant": variant,
              "loading": loading if variant == "candidate" else "none", "profiles": profiles, "dimensions": dims,
              "not_applicable": {d: NOT_APPLICABLE[d] for d in PURPOSE_DIMENSIONS.values() if d not in dims},
              "suite_sha256": digest(suite), "source_sha256": digest(source_context), "targets": sorted(ids),
              "package_sha256": digest(tree_hashes(candidate)), "created_at": time.time(), "timeout_seconds": 900,
              "retry": RETRY, "generation_sessions": generation_sessions}
    atomic_json(run / "config.json", config)
    return config


def check_inputs(run):
    run = Path(run)
    config = read_json(run / "config.json")
    manifest = verify(run / "relocated/skill")
    actual_targets = sorted(c["id"] for c in read_json(run / "relocated/skill/references/capabilities.json")["model"]["capabilities"])
    if config.get("targets") != actual_targets:
        raise ContractError("evaluation target inventory differs from package")
    if config["build_id"] != manifest["build_id"] or config["package_sha256"] != digest(tree_hashes(run / "relocated/skill")):
        raise ContractError("evaluation package changed")
    if digest(read_json(run / "suite.json")) != config["suite_sha256"] or digest(read_json(run / "source-context.json")) != config["source_sha256"]:
        raise ContractError("suite/source context changed after prepare")
    if config.get("packet_version", 1) >= 2:
        profiles = manifest["product"].get("profiles", [])
        expected = sorted(DIMENSIONS | {PURPOSE_DIMENSIONS[p] for p in profiles if p in PURPOSE_DIMENSIONS})
        if config.get("dimensions") != expected or config.get("profiles") != profiles:
            raise ContractError("evaluation dimensions differ from package purposes")
    clean_sources(read_json(run / "source-context.json"))
    return config


def answer_packet(run, cid, turn):
    run = Path(run)
    config = check_inputs(run)
    case = next(c for c in read_json(run / "suite.json")["cases"] if c["id"] == cid)
    if not 0 <= turn < len(case["turns"]):
        raise ContractError("invalid turn")
    history = []
    for i in range(turn):
        result = read_json(run / "answers" / cid / f"{i}.json")
        history.extend([{"role": "user", "content": case["turns"][i]}, {"role": "assistant", "content": result["result"]["answer"]}])
    history.append({"role": "user", "content": case["turns"][turn]})
    package = run / "relocated/skill"
    if config.get("loading") == "host":
        name = read_json(package / "book-workflow-manifest.json")["product"]["id"]
        return {"instruction": "按当前对话完成用户任务；工作区中可用的 Skill 由宿主自行发现与加载。直接答题，不评价自己。返回JSON {answer:完整回答}。",
                "conversation": history, "loading": "host", "skill_dir": "relocated/skill", "skill_name": name}
    resources = {p.relative_to(package).as_posix(): p.read_text(encoding="utf-8") for p in sorted(package.rglob("*.md"))} if config["variant"] == "candidate" else {}
    return {"instruction": "使用所给Skill及当前对话完成用户任务。直接答题，不评价自己，不读取外部材料。返回JSON {answer:完整回答}。若无Skill则正常回答。", "conversation": history, "skill": resources}


def collect_answer(run, cid, turn, response):
    run = Path(run)
    with locked(run):
        packet = answer_packet(run, cid, turn)
        config = read_json(run / "config.json")
        path = run / "answers" / cid / f"{turn}.json"
        if path.exists():
            raise ContractError("answer exists; retries require new evaluation run")
        text(response.get("result", {}).get("answer"), "actual answer")
        for key in ("session_id", "host", "model"):
            text(response.get("executor", {}).get(key), f"executor.{key}")
        if config.get("loading") == "host":
            reads = strings(response["executor"].get("observed_reads", []), "observed_reads", allow_empty=True)
            loading = {"loaded_files": reads, "loading_mode": "host-discovered; reads observed from host tool events",
                       "entry_loaded": "SKILL.md" in reads}
        elif config.get("packet_version", 1) >= 2:
            loading = {"loaded_files": list(packet["skill"]), "loading_mode": "inlined-by-harness; not evidence of host discovery"}
        else:
            loading = {"loaded_files": list(packet["skill"]), "loading_mode": "harness read relocated package and supplied content"}
        response = {**response, "packet_sha256": digest(packet), "turn_delivery": "sequential", **loading}
        atomic_json(path, response)
        ledger_path = run / "recorded.json"
        ledger = read_json(ledger_path) if ledger_path.exists() else {}
        ledger[path.relative_to(run).as_posix()] = file_hash(path)
        atomic_json(ledger_path, ledger)
    return response


def review_packet(run, cid):
    run = Path(run)
    config = check_inputs(run)
    case = next(c for c in read_json(run / "suite.json")["cases"] if c["id"] == cid)
    answers = [read_json(run / "answers" / cid / f"{i}.json")["result"]["answer"] for i in range(len(case["turns"]))]
    if config.get("packet_version", 1) < 2:
        return {"instruction": "独立评审实际答文，逐项结合来源、题内事实及rubric判断。返回JSON dimensions:{fidelity:{score:0到3,reason,excerpt:答文原句},application:{score,reason,excerpt},utility:{score,reason,excerpt}}, hard_failures:[严重失败，无则空]。2代表完成，3代表有额外辨别；无依据事实、拼原句不解题或条件改变不更新须指出。不要根据包名、作者身份或回答长度给分。",
                "turns": case["turns"], "answers": answers, "rubric": case["rubric"],
                "source_context": read_json(run / "source-context.json")}
    model = read_json(run / "relocated/skill/references/capabilities.json")["model"]
    packet = {"instruction": ("独立评审实际答文，逐项结合来源、题内事实及rubric判断，只依据给出的材料。dimensions 只评 dimensions 列出的维度，每项"
                              "{score:0到3, reason, excerpt:答文原句}：fidelity=来源忠实与材料边界（书内主张不得当作已核现实，人物/被引不等于作者）；"
                              "application=把蒸馏机制运用到新问题、随条件变化调整；utility=对用户任务的实际效用；cognition=是否按被测 Skill 的判断路径与习惯处理新问题，而非复述或套话；"
                              "expression=是否按其表达 PROFILE 组织成文且不冒称原话。2代表完成，3代表有额外辨别；无依据事实、拼原句不解题或条件改变不更新须指出。"
                              "hard_failures 列严重失败，无则空。凡有维度低于2或有严重失败，attribution 至少一项：stage 取 read（原文限定、反例或后果缺失）、"
                              "synthesize（关系方向、声音或条件错误）、examples（能力在包内但不会选择或组合，触发与范例不足）、build（入口、索引或资源未被加载使用）、"
                              "evaluation（题目或评分依据本身有问题）、unknown（证据不足以定位）；capabilities 写涉及的能力ID，evidence 写答文或来源中的可查证据。"
                              "不要根据包名、作者身份或回答长度给分。"),
              "turns": case["turns"], "answers": answers, "rubric": case["rubric"], "dimensions": dimensions(config),
              "not_applicable": config.get("not_applicable", {}), "attribution_required": True,
              "package_capabilities": [{"id": c["id"], "name": c["name"], "trigger": c["trigger"]} for c in model["capabilities"]],
              "targets": case["targets"], "source_context": read_json(run / "source-context.json")}
    if config.get("loading") == "host":
        packet["loading_observed"] = [read_json(run / "answers" / cid / f"{i}.json").get("loaded_files", []) for i in range(len(case["turns"]))]
    return packet


def collect_review(run, cid, response):
    run = Path(run)
    with locked(run):
        p = review_packet(run, cid)
        target = run / "reviews" / f"{cid}.json"
        if target.exists():
            raise ContractError("review exists; preserve original evaluation")
        answers = [read_json(path) for path in sorted((run / "answers" / cid).glob("*.json"))]
        validate_review_response(run, response, p)
        atomic_json(target, {**response, "packet_sha256": digest(p), "answers_sha256": digest(answers)})
        ledger_path = run / "recorded.json"
        ledger = read_json(ledger_path) if ledger_path.exists() else {}
        ledger[target.relative_to(run).as_posix()] = file_hash(target)
        atomic_json(ledger_path, ledger)
    return response


def report(run):
    run = Path(run)
    config = check_inputs(run)
    suite = read_json(run / "suite.json")
    manifest = verify(run / "relocated/skill")
    version = config.get("packet_version", 1)
    expected_answers = {f"{c['id']}/{i}.json" for c in cases(suite, manifest) for i in range(len(c["turns"]))}
    actual_answers = {p.relative_to(run / "answers").as_posix() for p in (run / "answers").glob("*/*.json")}
    if not actual_answers <= expected_answers:
        raise ContractError("unlisted answer artifacts")
    expected_reviews = {c["id"] + ".json" for c in suite["cases"]}
    if not {p.name for p in (run / "reviews").glob("*.json")} <= expected_reviews:
        raise ContractError("unlisted review artifacts")
    ledger = read_json(run / "recorded.json") if (run / "recorded.json").exists() else {}
    for path in list((run / "answers").glob("*/*.json")) + list((run / "reviews").glob("*.json")):
        if ledger.get(path.relative_to(run).as_posix()) != file_hash(path):
            raise ContractError("collected answer/review changed; new evaluation required")
    results, pending, attributions = [], [], {}
    covered = {"normal": set(), "changed": set()}
    host_load = {"answers": 0, "entry_loaded": 0, "files": set()}
    for case in cases(suite, manifest):
        cid = case["id"]
        try:
            answers = [read_json(run / "answers" / cid / f"{i}.json") for i in range(len(case["turns"]))]
            review = read_json(run / "reviews" / f"{cid}.json")
        except ContractError:
            pending.append(cid)
            continue
        for i, answer in enumerate(answers):
            text(answer.get("result", {}).get("answer"), "actual answer")
            for field in ("session_id", "host", "model"):
                text(answer.get("executor", {}).get(field), f"executor.{field}")
            if answer["packet_sha256"] != digest(answer_packet(run, cid, i)):
                raise ContractError("answer no longer binds turn input")
        if review["packet_sha256"] != digest(review_packet(run, cid)) or review["answers_sha256"] != digest(answers):
            raise ContractError("review/answers are stale")
        validate_review_response(run, review, review_packet(run, cid))
        dims = review["result"]["dimensions"]
        passed = not failing(config, review["result"])
        entry = {"id": cid, "passed": passed, "scores": {d: dims[d]["score"] for d in dimensions(config)}}
        if config.get("loading") == "host":
            loaded = all(a.get("entry_loaded") for a in answers)
            host_load["answers"] += len(answers)
            host_load["entry_loaded"] += sum(bool(a.get("entry_loaded")) for a in answers)
            host_load["files"].update(f for a in answers for f in a.get("loaded_files", []))
            if not loaded:
                passed = entry["passed"] = False
                entry["host_loaded"] = False
                attributions.setdefault(cid, []).append({"stage": "build", "capabilities": [], "problem": "host did not discover/load SKILL.md",
                                                         "evidence": "observed host tool events"})
        if not passed and version >= 2:
            attributions.setdefault(cid, []).extend(review["result"].get("attribution", []))
        if version >= 2:
            entry.update(group=case["group"], held_out=case["held_out"], targets=case["targets"])
        results.append(entry)
        if passed:
            covered[case["condition"]].update(case["targets"])
    complete = (set(c["group"] for c in suite["cases"]) == GROUPS and all(set(config["targets"]) <= covered[k] for k in covered)
                and any(c["held_out"] and c["group"] == "changed" and c["condition"] == "changed" for c in suite["cases"]))
    state = "failed" if any(not r["passed"] for r in results) else "pending" if pending or not complete else "passed"
    evidence = tree_hashes(run / "answers") if (run / "answers").exists() else {}
    evidence.update({"reviews/" + k: v for k, v in tree_hashes(run / "reviews").items()} if (run / "reviews").exists() else {})
    result = {**config, "status": state, "cases": results, "pending": pending, "coverage_complete": complete,
              "evidence_sha256": digest(evidence), "relocated": True,
              "isolation_limit": "fresh executor sessions receive relocated package content only; filesystem denial of original workspace is not attested",
              "hosts": sorted({read_json(p)["executor"]["host"] for p in (run / "answers").glob("*/*.json")})}
    if version >= 2:
        result["attributions"] = attributions
        result["held_out_failed"] = [r["id"] for r in results if r["held_out"] and not r["passed"]]
        if config.get("loading") == "host":
            result["host_load"] = {**host_load, "files": sorted(host_load["files"])}
            result["isolation_limit"] = "host session ran in a fresh project holding only the relocated Skill; reads are taken from host tool events"
    atomic_json(run / "acceptance.json", result)
    return result


def invoke(command, packet, run, name, timeout=600, retry=None):
    """Bounded retries with backoff for transient host failures; every attempt is logged and costed."""
    retry = {**RETRY, **(retry or {"max_attempts": 1})}
    log = Path(run) / "logs" / name
    log.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retry["max_attempts"] + 1):
        try:
            code, out, err, elapsed = run_worker(command, json.dumps(packet, ensure_ascii=False), timeout, run)
        except WorkerTimeout as exc:
            code, out, err, elapsed = -1, "", str(exc), timeout
        record = {"returncode": code, "stdout": out, "stderr": err, "elapsed_seconds": elapsed, "attempt": attempt}
        atomic_json(log if attempt == 1 else log.with_name(f"{log.stem}.attempt{attempt}{log.suffix}"), record)
        if not code:
            return decode_result(out)
        kind = "timeout" if code == -1 else classify_error(f"exit {code}", err)
        if kind == "structural" or attempt == retry["max_attempts"] or kind not in {"transient", "timeout"}:
            raise ContractError(f"evaluation worker failed ({kind}: {error_line(err)}); see {log}")
        time.sleep(min(retry["backoff_max_seconds"], retry["backoff_seconds"] * 2 ** (attempt - 1)))
    raise ContractError("unreachable")


def execute(run, command):
    run = Path(run).resolve()
    config = check_inputs(run)
    timeout, retry = config.get("timeout_seconds", 600), config.get("retry")
    for case in read_json(run / "suite.json")["cases"]:
        cid = case["id"]
        for i in range(len(case["turns"])):
            if not (run / "answers" / cid / f"{i}.json").exists():
                collect_answer(run, cid, i, invoke(command, answer_packet(run, cid, i), run, f"{cid}-answer-{i}.json", timeout, retry))
        if not (run / "reviews" / f"{cid}.json").exists():
            collect_review(run, cid, invoke(command, review_packet(run, cid), run, f"{cid}-review.json", timeout, retry))
    return report(run)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    for flag in ("candidate", "suite", "run", "source-context"):
        p.add_argument("--" + flag, type=Path, required=True)
    p.add_argument("--variant", choices=("candidate", "none"), default="candidate")
    p.add_argument("--loading", choices=("inline", "host"), default="inline",
                   help="host: the worker's host must discover and load the relocated Skill itself")
    p.add_argument("--production", type=Path, help="production root whose sessions are excluded from review")
    p = sub.add_parser("run")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--worker", type=Path, required=True)
    p = sub.add_parser("report")
    p.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.cmd == "prepare":
            result = prepare(args.candidate, args.suite, args.run, read_json(args.source_context), args.variant, args.loading, args.production)
        elif args.cmd == "run":
            result = execute(args.run, read_json(args.worker))
        else:
            result = report(args.run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
