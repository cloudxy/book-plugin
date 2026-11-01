"""Bounded feedback-driven prompt candidates and evidence comparisons; no training.

Implements a small reflective search experiment, not the full MIPRO/GEPA systems.
Candidates remain private until cross-source evidence supports normal versioning.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from book_skill_common import ContractError, digest, read_json, text, tree_hashes
from distill_skill import verify
from production import PROMPTS, read_state
from production_eval import invoke, report
from production_common import atomic_json


def propose(base, feedback, command, out):
    out = Path(out).resolve()
    if out.exists():
        raise ContractError("experiment directory exists; preserve earlier evidence")
    out.mkdir(parents=True)
    prompts = read_json(base)
    evidence = read_json(feedback)
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


def compare(baseline, candidate, baseline_eval, candidate_eval, split):
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
        return sorted({(e["executor"]["host"], e["executor"]["model"]) for t in state["tasks"].values() if t.get("output") and t["kind"] != "build" for e in [read_json(Path(root) / t["output"])]})
    if executors(baseline, old) != executors(candidate, new):
        raise ContractError("different host/model conditions cannot establish workflow improvement")
    scores_a = {x["id"]: x["scores"] for x in a["cases"]}
    scores_b = {x["id"]: x["scores"] for x in b["cases"]}
    nonregression = (a["status"] == b["status"] == "passed" and scores_a.keys() == scores_b.keys()
                     and all(scores_b[c][d] >= scores_a[c][d] for c in scores_a for d in scores_a[c]))
    return {"status": "observation-only", "split": split, "source_sha256": digest(old["sources"]),
            "quality_nonregression": nonregression, "baseline_usage": old["usage"], "candidate_usage": new["usage"],
            "scores": {"baseline": scores_a, "candidate": scores_b},
            "limits": ["elapsed_seconds is summed task time, not parallel wall time", "unknown token/currency fields remain unknown",
                       "optimizer proposal cost must be included separately", "one source cannot establish generalization; no automatic adoption"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--base", type=Path, default=PROMPTS)
    for key in ("feedback", "worker", "out"):
        p.add_argument("--"+key, type=Path, required=True)
    p = sub.add_parser("compare")
    for key in ("baseline", "candidate", "baseline-eval", "candidate-eval"):
        p.add_argument("--"+key, type=Path, required=True)
    p.add_argument("--split", choices=("development", "held-out-source"), required=True)
    args = parser.parse_args()
    try:
        result = propose(args.base, args.feedback, read_json(args.worker), args.out) if args.cmd == "propose" else compare(args.baseline, args.candidate, args.baseline_eval, args.candidate_eval, args.split)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ContractError, OSError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
