"""Prepare blind packets, collect actual outputs, score structure, report acceptance.

No model calls or semantic scoring are fabricated by this CLI. A host agent uses
packets; independent reviewers score the resulting answers. Exit 3 means pending.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from book_skill_common import (AUTHOR_DIMENSIONS, CASE_GROUPS, DIMENSIONS, SCHEMA, LEGACY_SCHEMA, STYLE_DIMENSIONS,
    ContractError, digest, json_bytes, read_json, read_yaml, slug, text,
    verify_package, write_json)

RULES = "book-eval/2"
LEGACY_RULES = "book-eval/1"


def rules_for(schema):
    if schema == SCHEMA:
        return RULES
    if schema == LEGACY_SCHEMA:
        return LEGACY_RULES
    raise ContractError("unsupported evaluation schema")


def expected(case, rules):
    defaults = DIMENSIONS
    if rules == RULES:
        task_type = case.get("task_type", "open")
        if task_type == "lookup":
            defaults = ("fidelity", "utility")
        elif task_type == "procedure":
            defaults = ("fidelity", "modeling", "inference", "utility")
        else:
            defaults = tuple(d for d in DIMENSIONS if d != "updating") + AUTHOR_DIMENSIONS
        if len(turns(case)) > 1:
            defaults += ("updating",)
    return case.get("expected_dimensions", defaults)


def case_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ContractError(f"invalid case id: {value!r}")
    return value


def turns(case):
    values = case.get("turns", [case.get("prompt")])
    if not isinstance(values, list):
        raise ContractError("turns must be a list")
    result = []
    for value in values:
        if isinstance(value, dict):
            if value.get("role") != "user":
                raise ContractError("only user inputs belong in evaluation packets")
            value = value.get("content")
        result.append(text(value, "user turn"))
    if not result:
        raise ContractError("at least one user turn required")
    return result


def cases_from(suite, rules=None):
    rules = rules or suite.get("schema_version", LEGACY_RULES)
    if rules not in {RULES, LEGACY_RULES} or suite.get("schema_version", LEGACY_RULES) != rules:
        raise ContractError("suite version differs from package evaluation contract; migrate explicitly")
    cases, seen = suite.get("cases"), set()
    if not isinstance(cases, list) or not cases:
        raise ContractError("nonempty cases list required")
    for case in cases:
        cid = case_id(case.get("id"))
        if cid in seen or case.get("group") not in CASE_GROUPS:
            raise ContractError(f"duplicate case/unknown group: {cid}")
        seen.add(cid)
        turns(case)
        dimensions = expected(case, rules)
        allowed = DIMENSIONS + (AUTHOR_DIMENSIONS if rules == RULES else ())
        if not isinstance(dimensions, (list, tuple)) or not dimensions or any(x not in allowed for x in dimensions):
            raise ContractError(f"{cid}: invalid expected_dimensions")
        if rules == RULES:
            task_type = case.get("task_type", "open")
            if task_type in {"lookup", "procedure"}:
                if case["group"] != {"lookup": "C01", "procedure": "C12"}[task_type]:
                    raise ContractError(f"{cid}: author exception only for exact lookup/procedure groups")
                text(case.get("applicability_reason"), f"{cid}.applicability_reason")
            elif task_type not in {"open", "writing", "explanation", "dialogue"}:
                raise ContractError(f"{cid}: unknown task_type")
            elif not set(AUTHOR_DIMENSIONS).issubset(dimensions):
                raise ContractError(f"{cid}: open/writing tasks require both author dimensions")
            targets = case.get("author_targets", [])
            if not isinstance(targets, list) or any(not isinstance(x, str) for x in targets) or len(targets) != len(set(targets)):
                raise ContractError(f"{cid}: invalid author_targets")
            if task_type not in {"lookup", "procedure"} and not targets:
                raise ContractError(f"{cid}: author target coverage required")
            if targets and case.get("author_condition") not in {"normal", "changed"}:
                raise ContractError(f"{cid}: declare normal/changed author condition")
        rubric = case.get("rubric")
        if isinstance(rubric, list):
            if not rubric:
                raise ContractError(f"{cid}: empty rubric")
            for item in rubric:
                text(item, f"{cid}.rubric")
        else:
            text(rubric, f"{cid}.rubric")
        if type(case.get("required", True)) is not bool or type(case.get("held_out", False)) is not bool:
            raise ContractError(f"{cid}: required/held_out must be booleans")
    return cases


def prepare(candidate, suite_path, run, variant="candidate", baseline=None, source=None, mode="acceptance", control_kind=None):
    candidate, run = Path(candidate).resolve(), Path(run).resolve()
    manifest = verify_package(candidate)
    if mode not in {"acceptance", "diagnostic"} or variant not in {"candidate", "none", "legacy", "retrieval", "summary", "ablation"}:
        raise ContractError("unknown mode or material variant")
    suite = read_yaml(suite_path)
    rules = rules_for(manifest["schema_version"])
    cases = cases_from(suite, rules)
    inventory = manifest.get("author_targets", {})
    if rules == RULES:
        if not isinstance(inventory, dict) or not inventory:
            raise ContractError("author package target inventory missing")
        for case in cases:
            if set(case.get("author_targets", [])) - set(inventory):
                raise ContractError(f"{case['id']}: unknown author target")
    if variant in {"summary", "ablation"}:
        kinds = {"without_habits", "without_expression", "swapped_expression", "without_examples"}
        if (mode != "diagnostic" or (variant == "ablation" and control_kind not in kinds)
                or (variant == "summary" and control_kind is not None)):
            raise ContractError("explicit ablation kind and diagnostic mode required for controls")
    elif control_kind is not None:
        raise ContractError("control_kind only belongs to ablation materials")
    if run.exists():
        raise ContractError("run directory exists; preserve previous outputs")
    run.mkdir(parents=True)
    for name in ("packets", "outputs", "reviews"):
        (run / name).mkdir()
    write_json(run / "suite.json", suite)
    if variant == "candidate":
        shutil.copytree(candidate, run / "skill")
    elif variant in {"legacy", "summary", "ablation"}:
        if not baseline or not (Path(baseline) / "SKILL.md").is_file():
            raise ContractError("legacy baseline must be a real installed/generated Skill")
        shutil.copytree(baseline, run / "skill")
    elif variant == "retrieval":
        if not source:
            raise ContractError("retrieval baseline needs actual source")
        from book_skill_common import load_source
        (run / "source.txt").write_text(load_source(source))
    elif variant != "none":
        raise ContractError("unknown variant")
    for case in cases:
        packet = {"case_id": case["id"], "turns": turns(case), "book_scope": manifest["scope"],
                  "instruction": "依用户问题自然回答。各轮依次处理并保留本题对话；不要读取评分、其他题或其他变体。"}
        if variant in {"candidate", "legacy", "summary", "ablation"}:
            packet["skill"] = str(run / "skill/SKILL.md")
        elif variant == "retrieval":
            packet["source"] = str(run / "source.txt")
            packet["instruction"] += "可充分检索和分析给定原文，记录所读范围。"
        if len(packet["turns"]) > 1:
            all_turns = packet.pop("turns")
            packet["turn_count"] = len(all_turns)
            packet["first_turn_packet"] = str(run / "packets" / case["id"] / "turn-01.json")
            packet["instruction"] += "多轮题由主持人逐轮递交，答完本轮再提供下一轮；不得预读后续文件。"
            for i, prompt in enumerate(all_turns, 1):
                one_turn = {k: v for k, v in packet.items() if k not in {"first_turn_packet", "turn_count"}}
                one_turn.update(turn=i, turns=[prompt])
                write_json(run / "packets" / case["id"] / f"turn-{i:02}.json", one_turn)
        write_json(run / "packets" / f"{case['id']}.json", packet)
    from book_skill_common import tree_hashes
    material = tree_hashes(run / "skill") if (run / "skill").exists() else (
        {"source.txt": digest((run / "source.txt").read_bytes())} if variant == "retrieval" else {})
    config = {"schema_version": manifest["schema_version"], "rules_version": rules, "mode": mode,
              "variant": variant, "build_id": manifest["build_id"],
              "package_sha256": digest(tree_hashes(candidate)),
              "suite_sha256": digest(suite), "material": material,
              "packets": tree_hashes(run / "packets")}
    if rules == RULES:
        config["author_targets"] = inventory
        config["scope"] = manifest["scope"]
    if variant in {"summary", "ablation"}:
        config["control_kind"] = "summary" if variant == "summary" else control_kind
    write_json(run / "run.json", config)
    return run


def validate_output(output, case):
    if output.get("case_id") != case["id"]:
        raise ContractError("output case_id mismatch")
    answers = output.get("answers")
    count = len(turns(case))
    if not isinstance(answers, list) or len(answers) != count:
        raise ContractError("actual answer required for every user turn")
    for answer in answers:
        text(answer, "actual answer")
    for field in ("executor", "host", "model", "session_id"):
        text(output.get(field), f"output.{field}")
    if output.get("isolated") is not True:
        raise ContractError("isolated answer session required")
    evidence = output.get("loading_evidence")
    if not (isinstance(evidence, (dict, list)) and evidence):
        text(evidence, "loading_evidence or explicit observability limitation")


def collect(run, case_id, answer_file):
    run = Path(run)
    config = read_json(run / "run.json")
    case = next((c for c in cases_from(read_json(run / "suite.json"), config["rules_version"]) if c["id"] == case_id), None)
    if not case:
        raise ContractError("unknown case")
    output = read_json(answer_file)
    validate_output(output, case)
    target = run / "outputs" / f"{case['id']}.json"
    if target.exists():
        raise ContractError("answer already collected; use a new run for a retry")
    write_json(target, output)
    return target


def report_run(run, structural_only=False):
    run = Path(run)
    config, suite = read_json(run / "run.json"), read_json(run / "suite.json")
    rules = rules_for(config.get("schema_version"))
    if config.get("rules_version") != rules or digest(suite) != config.get("suite_sha256"):
        raise ContractError("suite/scoring contract changed; prepare a fresh run")
    from book_skill_common import tree_hashes
    if config.get("packets") is not None:
        if tree_hashes(run / "packets") != config["packets"]:
            raise ContractError("user input packets changed after prepare")
    elif config["mode"] == "acceptance":
        raise ContractError("packet hashes not recorded; prepare a fresh acceptance run")
    actual = tree_hashes(run / "skill") if (run / "skill").exists() else (
        {"source.txt": digest((run / "source.txt").read_bytes())} if config["variant"] == "retrieval" else {})
    if actual != config["material"]:
        raise ContractError("answering material changed after prepare")
    if config["variant"] == "candidate":
        manifest = verify_package(run / "skill")
        if manifest["build_id"] != config["build_id"] or manifest["schema_version"] != config["schema_version"]:
            raise ContractError("candidate build mismatch")
        if rules == RULES and manifest.get("author_targets") != config.get("author_targets"):
            raise ContractError("author target inventory changed")
    if config["variant"] in {"summary", "ablation"} and config["mode"] != "diagnostic":
        raise ContractError("controls cannot authorize release")
    cases = cases_from(suite, rules)
    inventory = config.get("author_targets", {})
    if rules == RULES and (not inventory or any(set(c.get("author_targets", [])) - set(inventory) for c in cases)):
        raise ContractError("missing/unknown author targets")
    rows, pending, failed, output_hashes, sessions = [], [], [], {}, {}
    environments = set()
    collected = 0
    for case in cases:
        cid = case["id"]
        output_path, review_path = run / "outputs" / f"{cid}.json", run / "reviews" / f"{cid}.json"
        row = {"case_id": cid, "group": case["group"], "required": case.get("required", True)}
        if not output_path.is_file():
            row["status"] = "pending_output"
            pending.append(cid)
        else:
            collected += 1
            try:
                output = read_json(output_path)
                validate_output(output, case)
                environments.add((output["host"], output["model"]))
                if config["mode"] == "acceptance" and len(turns(case)) > 1:
                    if output.get("turn_delivery") != "sequential":
                        raise ContractError("multi-turn acceptance requires sequential delivery; scripted replay is diagnostic only")
                # Independent tasks must not silently share answer history.
                sid = output["session_id"]
                if sid in sessions and sessions[sid] != cid:
                    raise ContractError("same session reused across cases")
                sessions[sid] = cid
                output_hashes[cid] = digest(output)
                row["status"] = "structural_passed"
                if not structural_only:
                    if not review_path.is_file():
                        row["status"] = "pending_review"
                        pending.append(cid)
                    else:
                        review = read_json(review_path)
                        if (review.get("answer_sha256") != digest(output)
                                or review.get("rubric_sha256") != digest(case)
                                or review.get("independent") is not True or review.get("blind") is not True
                                or text(review.get("reviewer"), "reviewer") == output["executor"]):
                            raise ContractError("review is stale or not independently blind")
                        for dimension in expected(case, rules):
                            score = review.get("dimensions", {}).get(dimension, {})
                            if type(score.get("score")) is not int or score["score"] not in range(4):
                                raise ContractError(f"missing dimension score: {dimension}")
                            text(score.get("rationale"), f"{dimension}.rationale")
                            if score["score"] < 2:
                                raise ContractError(f"dimension below completion: {dimension}")
                            if dimension in AUTHOR_DIMENSIONS:
                                excerpt = text(score.get("answer_excerpt"), f"{dimension}.answer_excerpt")
                                if not any(excerpt in answer for answer in output["answers"]):
                                    raise ContractError(f"{dimension}: evidence is not in actual answer")
                        if rules == RULES:
                            evidence = review.get("author_evidence", {})
                            if set(evidence) != set(case.get("author_targets", [])):
                                raise ContractError("review must address each declared author target")
                            for target, proof in evidence.items():
                                excerpt = text(proof.get("answer_excerpt"), f"{target}.answer_excerpt")
                                text(proof.get("rationale"), f"{target}.rationale")
                                if not any(excerpt in answer for answer in output["answers"]):
                                    raise ContractError(f"{target}: evidence is not in actual answer")
                        if "expression" in expected(case, rules):
                            for dimension in STYLE_DIMENSIONS:
                                score = review.get("expression", {}).get(dimension, {})
                                if score.get("status") == "not_applicable":
                                    if dimension in {"preservation", "naturalness"}:
                                        raise ContractError(f"{dimension} cannot be not_applicable")
                                    text(score.get("rationale"), f"{dimension}.not_applicable")
                                elif (type(score.get("score")) is not int or score["score"] < 2
                                      or score["score"] > 3 or not score.get("rationale")):
                                    raise ContractError(f"expression subdimension incomplete: {dimension}")
                                else:
                                    text(score.get("rationale"), f"{dimension}.rationale")
                        if review.get("hard_failures") != []:
                            raise ContractError("critical factual/semantic failure or hard_failures not reviewed")
                        row["status"] = "passed"
                        row["review_sha256"] = digest(review)
            except (ContractError, ValueError, TypeError, KeyError) as exc:
                row.update(status="failed", error=str(exc))
                if row["required"]:
                    failed.append(cid)
        rows.append(row)
    groups = {case["group"] for case in cases}
    if len(environments) > 1:
        failed.append("host_or_model_changed_within_run")
    held = {case["group"] for case in cases if case.get("held_out")}
    if config["mode"] == "acceptance":
        if set(CASE_GROUPS) - groups:
            pending.append("missing_task_groups:" + ",".join(sorted(set(CASE_GROUPS) - groups)))
        if {"C02", "C03", "C05", "C13", "C14"} - held:
            pending.append("held_out_coverage")
        if rules == RULES and not structural_only:
            coverage = {target: set() for target in inventory}
            for case, row in zip(cases, rows):
                if row["status"] != "passed":
                    continue
                for target in case.get("author_targets", []):
                    coverage[target].add(case["author_condition"])
            for target, conditions in coverage.items():
                if conditions != {"normal", "changed"}:
                    pending.append("author_target_coverage:" + target)
    elif not structural_only:
        pending.append("diagnostic_run_only")
    if not structural_only:
        user_path = run / "user-expression.json"
        if not user_path.is_file():
            pending.append("user_expression_review")
        else:
            user = read_json(user_path)
            if (user.get("build_id") != config["build_id"]
                    or user.get("suite_sha256") != config["suite_sha256"]
                    or user.get("output_sha256") != output_hashes
                    or user.get("reviewer_role") != "user" or user.get("approved") is not True
                    or not user.get("rationale")):
                failed.append("user_expression_review_rejected_or_stale")
    state = "failed" if failed else "pending" if pending else "passed"
    if structural_only:
        state = "structural_passed" if not pending and not failed else state
    result = {"schema_version": config["schema_version"], "rules_version": rules,
            "status": state, "build_id": config["build_id"], "variant": config["variant"],
            "package_sha256": config["package_sha256"],
            "suite_sha256": config["suite_sha256"], "mode": config["mode"],
            "planned": len(cases), "actual": len(output_hashes),
            "collected": collected, "missing_outputs": len(cases) - collected,
            "passed": sum(row["status"] == "passed" for row in rows),
            "pending": pending, "failed": failed, "cases": rows, "output_sha256": output_hashes}
    if rules == RULES:
        result["scope"] = config["scope"]
        result["author_targets"] = inventory
        result["author_certification"] = "failed" if state == "failed" else (
            "passed" if state == "passed" and config["variant"] == "candidate" else "pending")
    return result


def blind_packets(run, out):
    """Hide material/executor labels; preserve every character of actual answers."""
    run, out = Path(run), Path(out)
    config, suite = read_json(run / "run.json"), read_json(run / "suite.json")
    if digest(suite) != config["suite_sha256"]:
        raise ContractError("suite changed before anonymization")
    if out.exists():
        raise ContractError("blind packet directory exists; preserve the prior review batch")
    records, mapping = {}, {}
    for case in cases_from(suite, config["rules_version"]):
        path = run / "outputs" / f"{case['id']}.json"
        if not path.is_file():
            continue
        output = read_json(path)
        validate_output(output, case)
        oid = digest(output)
        anonymous_id = digest({"answer": oid, "case": digest(case)})[:20]
        records[anonymous_id] = {"case": case, "answers": output["answers"],
                                 "answer_sha256": oid, "answers_sha256": digest(output["answers"]),
                                 "rubric_sha256": digest(case)}
        mapping[anonymous_id] = {"case_id": case["id"], "output": str(path.resolve()), "answer_sha256": oid}
    if not records:
        raise ContractError("no actual outputs to anonymize")
    for aid, record in records.items():
        write_json(out / "packets" / f"{aid}.json", record)
    write_json(out / "host-map.json", mapping)
    return out / "packets"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    for name in ("candidate", "suite", "run-dir"):
        prep.add_argument(f"--{name}", required=True, type=Path)
    prep.add_argument("--variant", choices=("candidate", "none", "legacy", "retrieval", "summary", "ablation"), default="candidate")
    prep.add_argument("--control-kind", choices=("without_habits", "without_expression", "swapped_expression", "without_examples"))
    prep.add_argument("--baseline", type=Path)
    prep.add_argument("--source", type=Path)
    prep.add_argument("--mode", choices=("acceptance", "diagnostic"), default="acceptance")
    col = sub.add_parser("collect")
    col.add_argument("--run-dir", required=True, type=Path)
    col.add_argument("--case", required=True)
    col.add_argument("--answer", required=True, type=Path)
    blind = sub.add_parser("blind", help="bind full anonymous answers to actual collected output hashes")
    blind.add_argument("--run-dir", required=True, type=Path)
    blind.add_argument("--out-dir", required=True, type=Path)
    for cmd in ("score-structural", "report"):
        parser = sub.add_parser(cmd)
        parser.add_argument("--run-dir", required=True, type=Path)
    args = ap.parse_args()
    try:
        if args.command == "prepare":
            print(prepare(args.candidate, args.suite, args.run_dir, args.variant,
                          args.baseline, args.source, args.mode, args.control_kind))
            return 0
        if args.command == "collect":
            print(collect(args.run_dir, args.case, args.answer))
            return 0
        if args.command == "blind":
            print(blind_packets(args.run_dir, args.out_dir))
            return 0
        result = report_run(args.run_dir, args.command == "score-structural")
        filename = "structural.json" if args.command == "score-structural" else "acceptance.json"
        write_json(args.run_dir / filename, result)
        print(f"{result['status']}: actual={result['actual']}/{result['planned']}; "
              f"semantic_passed={result['passed']}; pending={result['pending']}; failed={result['failed']}")
        return 0 if result["status"] in {"passed", "structural_passed"} else 1 if result["status"] == "failed" else 3
    except (ContractError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"评测拒绝: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
