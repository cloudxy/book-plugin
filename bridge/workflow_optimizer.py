"""Workflow loop: pooled stage failures, bounded module candidates, experience ledger, comparisons.

No training. A candidate changes one stage module (instruction, one example or one
failure-handling rule) and is never adopted automatically. It becomes a global rule
only after a same-condition comparison on a book that was not used for tuning;
otherwise it stays a book- or genre-level suggestion. Implements a small reflective
search plus an ACE-style ledger, not the full MIPRO/GEPA systems.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import copy
import json
from pathlib import Path
import time

from book_skill_common import ContractError, digest, read_json, slug, text, tree_hashes
from distill_skill import verify
from production import MODULES, read_state
from production_eval import invoke, report
from production_common import atomic_json, locked, strings

LEDGER = "workflow-experience/1"
SCOPES = ("book", "genre", "global")


def propose(base, feedback, command, out):
    out = Path(out).resolve()
    if out.exists():
        raise ContractError("experiment directory exists; preserve earlier evidence")
    out.mkdir(parents=True)
    prompts = read_json(base)
    evidence = read_json(feedback)
    if prompts.get("schema_version") == "stage-modules/1":
        return _propose_module(prompts, evidence, command, out, base)
    packet = {"instruction": "根据可观察失败，只提出一个阶段指令的最小修订。返回JSON stage:read|merge|synthesize|review,instruction:完整新指令,rationale:与具体失败对应的原因。保留阶段输出结构和来源/范围/独立性约束，不放入试题答案、书稿或私人事实，不改变模型参数。没有有依据的改法时 stage:none,instruction:空字符串,rationale:原因。", "stage_instructions": prompts, "feedback": evidence}
    response = invoke(command, packet, out, "proposal.json")
    result = response["result"]
    stage = result.get("stage")
    if stage != "none" and stage not in prompts:
        raise ContractError("unknown stage")
    text(result.get("rationale"), "rationale")
    if stage != "none":
        prompts[stage] = text(result.get("instruction"), "instruction")
    atomic_json(out / "prompts.json", prompts)
    atomic_json(out / "experiment.json", {"status": "candidate-not-adopted", "base_sha256": digest(read_json(base)),
                                          "candidate_sha256": digest(prompts), "feedback_sha256": digest(evidence),
                                          "proposal": response, "stage": stage})
    return {"status": "candidate-not-adopted", "prompts": str(out / "prompts.json"), "stage": stage}


def _propose_module(modules, evidence, command, out, base):
    editable = {k: {f: v[f] for f in ("version", "contract", "instruction", "examples", "failure_handling")}
                for k, v in modules["modules"].items() if v.get("instruction")}
    packet = {"instruction": ("根据可观察、已归因到阶段的失败，只修改一个阶段模块的一处：change 取 instruction（给出完整新指令）、"
                              "example（新增一个原创合成教学示例 {situation,good,bad,why}）或 failure_handling（新增一条 {signal,action}）。"
                              "返回JSON stage, change, instruction（不改时为空字符串）, example（不用时为null）, failure_handling（不用时为null）, rationale。"
                              "保留输出合同、来源/范围/独立性约束；不放入真实书稿、产物、试题答案或私人事实；不改变模型参数。"
                              "没有有依据的改法时 stage:none, change:none。"),
              "modules": editable, "feedback": evidence}
    response = invoke(command, packet, out, "proposal.json")
    result = response["result"]
    stage, change = result.get("stage"), result.get("change")
    text(result.get("rationale"), "rationale")
    candidate = copy.deepcopy(modules)
    if stage != "none":
        if stage not in editable or change not in {"instruction", "example", "failure_handling"}:
            raise ContractError("candidate must change one editable module by instruction/example/failure_handling")
        module = candidate["modules"][stage]
        if change == "instruction":
            module["instruction"] = text(result.get("instruction"), "instruction")
        elif change == "example":
            item = result.get("example") or {}
            for field in ("situation", "good", "bad", "why"):
                text(item.get(field), f"example.{field}")
            module["examples"].append({f: item[f] for f in ("situation", "good", "bad", "why")})
        else:
            item = result.get("failure_handling") or {}
            for field in ("signal", "action"):
                text(item.get(field), f"failure_handling.{field}")
            module["failure_handling"].append({f: item[f] for f in ("signal", "action")})
        tag = digest(module)[:8]
        module["version"] = f"{module['version'].split('+')[0]}+cand-{tag}"
        candidate["version"] = f"{modules['version'].split('+')[0]}+cand-{tag}"
    atomic_json(out / "modules.json", candidate)
    atomic_json(out / "experiment.json", {"status": "candidate-not-adopted", "base_sha256": digest(read_json(base)),
                                          "candidate_sha256": digest(candidate), "feedback_sha256": digest(evidence),
                                          "proposal": response, "stage": stage, "change": change})
    return {"status": "candidate-not-adopted", "modules": str(out / "modules.json"), "stage": stage, "change": change}


def pooled_failures(roots):
    """Problems recurring in two or more products are workflow candidates; others stay local."""
    import production_metrics as metrics
    seen = defaultdict(lambda: {"products": set(), "count": 0, "genres": set()})
    for root in roots:
        report_ = metrics.failures(root)
        for item in report_["items"]:
            key = (item["stage"], item["class"])
            seen[key]["products"].add(report_["product"])
            seen[key]["count"] += 1
            seen[key]["genres"].update(report_.get("genres") or report_["profiles"])
    rows = [{"stage": s, "class": c, "products": sorted(v["products"]), "count": v["count"], "genres_or_profiles": sorted(v["genres"])}
            for (s, c), v in seen.items()]
    rows.sort(key=lambda r: (-len(r["products"]), -r["count"]))
    return {"recurring": [r for r in rows if len(r["products"]) >= 2], "single_product": [r for r in rows if len(r["products"]) < 2],
            "rule": "只有跨书重复出现的问题才成为工作流候选；单书问题按书级或类型级建议处理"}


def compare(baseline, candidate, baseline_eval, candidate_eval, split, out=None):
    old, new = read_state(baseline), read_state(candidate)
    a, b = report(baseline_eval), report(candidate_eval)
    for root, state, evaluation in ((baseline, old, a), (candidate, new, b)):
        task = state["tasks"].get("build", {})
        if task.get("status") != "done" or not task.get("output"):
            raise ContractError("comparison requires completed production builds")
        built = read_json(Path(root) / task["output"])["result"]
        package = Path(root) / built["package"]
        manifest = verify(package)
        if (evaluation["variant"] != "candidate" or evaluation["build_id"] != manifest["build_id"]
                or evaluation["package_sha256"] != digest(tree_hashes(package))):
            raise ContractError("evaluation must bind the corresponding production package")
    same_sources = [{k: s[k] for k in ("raw_sha256", "role", "period")} for s in old["sources"]] == [{k: s[k] for k in ("raw_sha256", "role", "period")} for s in new["sources"]]
    if not same_sources or old["product"] != new["product"] or a["suite_sha256"] != b["suite_sha256"]:
        raise ContractError("comparison requires same source, task scope and suite")
    def executors(root, state):
        return sorted({(e["executor"]["host"], e["executor"]["model"]) for t in state["tasks"].values()
                       if t.get("output") and t["kind"] != "build" and t.get("mode") != "python" and t["kind"] not in {"audit", "ledger"}
                       for e in [read_json(Path(root) / t["output"])]})
    if executors(baseline, old) != executors(candidate, new):
        raise ContractError("different host/model conditions cannot establish workflow improvement")
    scores_a = {x["id"]: x["scores"] for x in a["cases"]}
    scores_b = {x["id"]: x["scores"] for x in b["cases"]}
    nonregression = (a["status"] == b["status"] == "passed" and scores_a.keys() == scores_b.keys()
                     and all(scores_b[c][d] >= scores_a[c][d] for c in scores_a for d in scores_a[c]))
    import production_metrics as metrics
    modules = lambda s: digest(read_json(s["prompts"])) if Path(s.get("prompts", "")).is_file() else None
    result = {"status": "observation-only", "split": split, "product": new["product"]["id"], "source_sha256": digest(old["sources"]),
              "baseline_modules_sha256": modules(old), "candidate_modules_sha256": modules(new),
              "quality_nonregression": nonregression, "baseline_usage": old["usage"], "candidate_usage": new["usage"],
              "scores": {"baseline": scores_a, "candidate": scores_b}, "productivity": metrics.compare(baseline, candidate),
              "limits": ["elapsed_seconds is summed task time, not parallel wall time", "unknown token/currency fields remain unknown",
                         "optimizer proposal cost must be included separately", "one source cannot establish generalization; no automatic adoption"]}
    if out:
        atomic_json(out, result)
    return result


def _ledger(path):
    path = Path(path)
    data = read_json(path) if path.exists() else {"schema_version": LEDGER, "entries": {}}
    if data.get("schema_version") != LEDGER:
        raise ContractError("unknown experience ledger")
    return data


def experience_add(path, entry_id, stage, rule, conditions, counterexamples, tuned_on, candidate_modules, scope="book"):
    """Reusable operating rules only; book text, answers and reviews stay in private runs."""
    slug(entry_id)
    if scope not in SCOPES[:2]:
        raise ContractError("new experience starts at book or genre scope; global requires promotion")
    path = Path(path)
    with locked(path.parent):
        data = _ledger(path)
        if entry_id in data["entries"]:
            raise ContractError("experience entry exists")
        data["entries"][entry_id] = {"stage": text(stage, "stage"), "rule": text(rule, "rule"),
                                     "conditions": strings(conditions, "conditions"), "counterexamples": strings(counterexamples, "counterexamples", allow_empty=True),
                                     "scope": scope, "status": "candidate", "tuned_on": strings(tuned_on, "tuned_on"),
                                     "candidate_modules_sha256": digest(read_json(candidate_modules)), "validated_on": [], "time": time.time()}
        atomic_json(path, data)
    return data["entries"][entry_id]


def experience_promote(path, entry_id, comparison):
    """Global only after held-out-source comparison on an untuned book with the same candidate modules."""
    path = Path(path)
    evidence = read_json(comparison)
    with locked(path.parent):
        data = _ledger(path)
        entry = data["entries"].get(entry_id)
        if not entry:
            raise ContractError("unknown experience entry")
        reasons = []
        if evidence.get("split") != "held-out-source":
            reasons.append("comparison was not on a held-out source")
        if evidence.get("product") in entry["tuned_on"]:
            reasons.append("validation book was used for tuning")
        if evidence.get("candidate_modules_sha256") != entry["candidate_modules_sha256"]:
            reasons.append("comparison ran different modules")
        if not evidence.get("quality_nonregression"):
            reasons.append("quality regressed or evaluations did not pass")
        record = {"product": evidence.get("product"), "comparison_sha256": digest(evidence), "time": time.time(), "reasons": reasons}
        entry["validated_on"].append(record)
        if not reasons:
            entry.update(status="validated", scope="global")
        atomic_json(path, data)
    return {"id": entry_id, "status": entry["status"], "scope": entry["scope"], "reasons": reasons}


def experience_reject(path, entry_id, reason):
    path = Path(path)
    with locked(path.parent):
        data = _ledger(path)
        entry = data["entries"].get(entry_id)
        if not entry:
            raise ContractError("unknown experience entry")
        entry.update(status="rejected", rejected_because=text(reason, "reason"))
        atomic_json(path, data)
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--base", type=Path, default=MODULES)
    for key in ("feedback", "worker", "out"):
        p.add_argument("--"+key, type=Path, required=True)
    p = sub.add_parser("failures")
    p.add_argument("--root", action="append", type=Path, required=True)
    p = sub.add_parser("compare")
    for key in ("baseline", "candidate", "baseline-eval", "candidate-eval"):
        p.add_argument("--"+key, type=Path, required=True)
    p.add_argument("--split", choices=("development", "held-out-source"), required=True)
    p.add_argument("--out", type=Path)
    p = sub.add_parser("experience")
    p.add_argument("action", choices=("add", "promote", "reject", "list"))
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--id")
    p.add_argument("--stage")
    p.add_argument("--rule")
    p.add_argument("--condition", action="append", default=[])
    p.add_argument("--counterexample", action="append", default=[])
    p.add_argument("--tuned-on", action="append", default=[])
    p.add_argument("--modules", type=Path)
    p.add_argument("--scope", choices=SCOPES[:2], default="book")
    p.add_argument("--comparison", type=Path)
    p.add_argument("--reason")
    args = parser.parse_args()
    try:
        if args.cmd == "propose":
            result = propose(args.base, args.feedback, read_json(args.worker), args.out)
        elif args.cmd == "failures":
            result = pooled_failures(args.root)
        elif args.cmd == "compare":
            result = compare(args.baseline, args.candidate, args.baseline_eval, args.candidate_eval, args.split, args.out)
        elif args.action == "add":
            result = experience_add(args.ledger, args.id, args.stage, args.rule, args.condition, args.counterexample,
                                    args.tuned_on, args.modules, args.scope)
        elif args.action == "promote":
            result = experience_promote(args.ledger, args.id, args.comparison)
        elif args.action == "reject":
            result = experience_reject(args.ledger, args.id, args.reason)
        else:
            result = _ledger(args.ledger)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ContractError, OSError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
