"""Actual, isolated trial-Skill use, independent review, and bound acceptance.

The evaluation suite stays outside the runtime package. Command workers receive
one turn at a time; all model answers/reviews and failures remain in private runs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

from book_skill_common import ContractError, digest, read_json, slug, text, tree_hashes
from production_common import atomic_json, decode_result, file_hash, locked, strings
from distill_skill import verify

GROUPS = {"direct", "combine", "changed", "correction", "deliver", "boundary"}
DIMENSIONS = {"fidelity", "application", "utility"}


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


def validate_review_response(run, response, packet):
    config = read_json(Path(run) / "config.json")
    for field in ("session_id", "host", "model"):
        text(response.get("executor", {}).get(field), f"reviewer.{field}")
    sessions = {read_json(p)["executor"]["session_id"] for p in (Path(run) / "answers").glob("*/*.json")}
    sessions.update(config.get("generation_sessions", []))
    if response["executor"]["session_id"] in sessions:
        raise ContractError("review session participated in generation or answering")
    result = response.get("result", {})
    if set(result.get("dimensions", {})) != DIMENSIONS:
        raise ContractError("review dimensions required")
    for dim, value in result["dimensions"].items():
        if type(value.get("score")) is not int or not 0 <= value["score"] <= 3:
            raise ContractError("invalid score")
        text(value.get("reason"), f"{dim}.reason")
        excerpt = text(value.get("excerpt"), f"{dim}.excerpt")
        if not any(excerpt in a for a in packet["answers"]):
            raise ContractError("review excerpt not present in actual answers")
    strings(result.get("hard_failures"), "hard_failures", allow_empty=True)


def cases(suite, manifest):
    items = suite.get("cases")
    if suite.get("schema_version") != "production-eval/1" or not isinstance(items, list) or not items:
        raise ContractError("production-eval/1 cases required")
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
    return items


def prepare(candidate, suite_path, run, source_context, variant="candidate"):
    candidate, run = Path(candidate).resolve(), Path(run).resolve()
    manifest = verify(candidate)
    suite = read_json(suite_path)
    items = cases(suite, manifest)
    model = read_json(candidate / "references/capabilities.json")["model"]
    ids = {c["id"] for c in model["capabilities"]}
    if any(not set(c["targets"]) <= ids for c in items):
        raise ContractError("unknown capability in case targets")
    if run.exists():
        raise ContractError("use a new evaluation directory; do not overwrite history")
    if run.is_relative_to(candidate):
        raise ContractError("evaluation must be outside runtime package")
    if variant not in {"candidate", "none"}:
        raise ContractError("variant must be candidate/none")
    run.mkdir(parents=True)
    shutil.copytree(candidate, run / "relocated/skill")
    verify(run / "relocated/skill")
    atomic_json(run / "suite.json", suite)
    generation_sessions = source_context.get("generation_sessions", [])
    strings(generation_sessions, "generation_sessions", allow_empty=True)
    source_context = clean_sources(source_context)
    atomic_json(run / "source-context.json", source_context)
    config = {"schema_version": "production-eval/1", "build_id": manifest["build_id"], "variant": variant,
              "suite_sha256": digest(suite), "source_sha256": digest(source_context), "targets": sorted(ids),
              "package_sha256": digest(tree_hashes(candidate)), "created_at": time.time()}
    config["generation_sessions"] = generation_sessions
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
    resources = {p.relative_to(package).as_posix(): p.read_text(encoding="utf-8") for p in sorted(package.rglob("*.md"))} if config["variant"] == "candidate" else {}
    return {"instruction": "使用所给Skill及当前对话完成用户任务。直接答题，不评价自己，不读取外部材料。返回JSON {answer:完整回答}。若无Skill则正常回答。", "conversation": history, "skill": resources}


def collect_answer(run, cid, turn, response):
    run = Path(run)
    with locked(run):
        packet = answer_packet(run, cid, turn)
        path = run / "answers" / cid / f"{turn}.json"
        if path.exists():
            raise ContractError("answer exists; retries require new evaluation run")
        text(response.get("result", {}).get("answer"), "actual answer")
        for key in ("session_id", "host", "model"):
            text(response.get("executor", {}).get(key), f"executor.{key}")
        response = {**response, "packet_sha256": digest(packet), "turn_delivery": "sequential",
                    "loaded_files": list(packet["skill"]), "loading_mode": "harness read relocated package and supplied content"}
        atomic_json(path, response)
        ledger_path = run / "recorded.json"
        ledger = read_json(ledger_path) if ledger_path.exists() else {}
        ledger[path.relative_to(run).as_posix()] = file_hash(path)
        atomic_json(ledger_path, ledger)
    return response


def review_packet(run, cid):
    run = Path(run)
    check_inputs(run)
    case = next(c for c in read_json(run / "suite.json")["cases"] if c["id"] == cid)
    answers = [read_json(run / "answers" / cid / f"{i}.json")["result"]["answer"] for i in range(len(case["turns"]))]
    return {"instruction": "独立评审实际答文，逐项结合来源、题内事实及rubric判断。返回JSON dimensions:{fidelity:{score:0到3,reason,excerpt:答文原句},application:{score,reason,excerpt},utility:{score,reason,excerpt}}, hard_failures:[严重失败，无则空]。2代表完成，3代表有额外辨别；无依据事实、拼原句不解题或条件改变不更新须指出。不要根据包名、作者身份或回答长度给分。",
            "turns": case["turns"], "answers": answers, "rubric": case["rubric"],
            "source_context": read_json(run / "source-context.json")}


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
    results, pending = [], []
    covered = {"normal": set(), "changed": set()}
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
        passed = not review["result"]["hard_failures"] and all(dims[d]["score"] >= 2 for d in DIMENSIONS)
        results.append({"id": cid, "passed": passed, "scores": {d: dims[d]["score"] for d in DIMENSIONS}})
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
    atomic_json(run / "acceptance.json", result)
    return result


def invoke(command, packet, run, name, timeout=600):
    started = time.time()
    proc = subprocess.run(command, input=json.dumps(packet, ensure_ascii=False), text=True, capture_output=True, timeout=timeout, cwd=run)
    log = Path(run) / "logs" / name
    log.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(log, {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "elapsed_seconds": time.time()-started})
    if proc.returncode:
        raise ContractError(f"evaluation worker failed; see {log}")
    return decode_result(proc.stdout)


def execute(run, command):
    run = Path(run).resolve()
    check_inputs(run)
    for case in read_json(run / "suite.json")["cases"]:
        cid = case["id"]
        for i in range(len(case["turns"])):
            if not (run / "answers" / cid / f"{i}.json").exists():
                collect_answer(run, cid, i, invoke(command, answer_packet(run, cid, i), run, f"{cid}-answer-{i}.json"))
        if not (run / "reviews" / f"{cid}.json").exists():
            collect_review(run, cid, invoke(command, review_packet(run, cid), run, f"{cid}-review.json"))
    return report(run)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    for flag in ("candidate", "suite", "run", "source-context"):
        p.add_argument("--" + flag, type=Path, required=True)
    p.add_argument("--variant", choices=("candidate", "none"), default="candidate")
    p = sub.add_parser("run")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--worker", type=Path, required=True)
    p = sub.add_parser("report")
    p.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.cmd == "prepare":
            result = prepare(args.candidate, args.suite, args.run, read_json(args.source_context), args.variant)
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
