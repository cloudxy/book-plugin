# -*- coding: utf-8 -*-
"""合成产线响应：按任务包形状机械地返回合同合法的结果。

只证明调度与合同控制流程，不代表任何真实书籍或人物的阅读、综合与评审质量。
`legacy_result` 复现 0.5.0 扁平指令集的结果形状，用于迁移兼容用例。
"""
from __future__ import annotations

# Literal schema names keep this module import-free, so fake command workers start fast.
MODEL_SCHEMA = "distilled-capability/1"
MODEL_SCHEMA_V2 = "distilled-capability/2"
FINDINGS = "Synthetic: separate observation from explanation, specify conditions before trying a reversible change."


def executor(name):
    return {"host": "synthetic-test", "model": "no-model", "session_id": name}


def model(units, profiles=("knowledge",), v2=True):
    cap = {"id": "conditional", "kind": "thought" if "thought" in profiles else "knowledge", "name": "Conditional evidence",
           "trigger": "Uncertain reversible choice", "actions": ["Specify prediction", "Observe before generalizing"],
           "conditions": ["Change is reversible"], "changes": ["Irreversible cost requires other evidence"],
           "evidence": list(units), "epistemic_status": "reconstructed"}
    data = {"schema_version": MODEL_SCHEMA_V2 if v2 else MODEL_SCHEMA,
            "description": "Use for reversible choices with uncertain evidence.",
            "core": "State the prediction and conditions before trying a reversible change.",
            "uses": ["Explain conditional decisions"], "limits": ["Synthetic fixture; no quality evidence"],
            "capabilities": [cap],
            "examples": [{"id": "shop", "capabilities": ["conditional"], "task": "Extend hours?",
                          "answer": "Try one evening and measure costs.", "changed_task": "A year-long contract is required.",
                          "changed_answer": "Seek existing demand evidence first.", "origin": "synthetic"}],
            "procedures": {"status": "not_applicable", "reason": "Explanatory capability, no executable procedure"}}
    if v2:
        cap.update(voice="author", reality="method-or-viewpoint")
        data.update(inputs=["The user's facts and the decision at hand"], episodes=[], habits=[])
        if "thought" in profiles:
            data["episodes"] = [{"id": "trial-path", "capabilities": ["conditional"], "problem": "Unclear demand",
                                 "path": ["Classify reversibility", "Run a small trial"], "tradeoff": "Speed against cost",
                                 "revision": "Stop when cost turns irreversible", "evidence": list(units)[:1]}]
            data["habits"] = [{"id": "classify-first", "name": "Classify before acting", "steps": ["Ask if reversible", "Choose test or evidence"],
                               "when": "Uncertain choice", "counter_signal": "Irreversible commitment", "evidence": list(units)[:1]}]
        if "expression" in profiles:
            data["profile"] = {"voice_layer": "author", "structure": ["Claim then condition"], "rhythm": ["Short sentences"],
                               "devices": ["Contrast"], "diction": ["Plain"], "avoid": ["Quoting as original words"],
                               "evidence": list(units)[:1]}
    return data


def result(packet, profiles=None):
    stage = packet["stage"]
    profiles = profiles or packet.get("product", {}).get("profiles", ["knowledge"])
    if stage == "read":
        kind = next(t for t in packet["entry_types"] if t != "other")
        return {"covered_units": [packet["task_id"]], "findings": FINDINGS,
                "entries": [{"type": kind, "content": "Conditions precede conclusions.", "voice": "author",
                             "status": "explicit", "reality": "method-or-viewpoint"}],
                "risk_flags": [], "limitations": ["Synthetic fixture only"], "open_connections": []}
    if stage == "merge":
        return {"covered_units": [u for r in packet["inputs"].values() for u in r["covered_units"]], "findings": FINDINGS,
                "conflicts": [], "limitations": ["Synthetic fixture only"], "open_connections": []}
    if stage == "audit-part":
        return {"decisions": {u: {"verdict": "pass", "problems": [], "reason": "Synthetic audit."} for u in packet["items"]},
                "notes": "Synthetic, not a real audit."}
    if stage == "synthesize":
        return model(packet["source_units"], profiles)
    if stage in {"review", "review-part"}:
        body = {"decisions": {i: {"verdict": "pass", "reason": "Synthetic control-flow fixture."} for i in packet["decision_ids"]},
                "issues": [], "repairs": [], "coverage_assessment": "Synthetic, not real source review."}
        return {"verdict": "pass", **body} if stage == "review" else body
    raise AssertionError(stage)


def legacy_result(packet):
    stage = packet["stage"]
    if stage in {"read", "merge"}:
        units = [packet["task_id"]] if stage == "read" else [u for r in packet["inputs"].values() for u in r["covered_units"]]
        return {"covered_units": units, "findings": FINDINGS, "limitations": ["Synthetic fixture only"], "open_connections": []}
    if stage == "synthesize":
        return model(packet["source_units"], v2=False)
    if stage == "review":
        return {"verdict": "pass",
                "decisions": {i["id"]: {"verdict": "pass", "reason": "Synthetic control-flow fixture."}
                              for i in packet["inputs"]["synthesize"]["capabilities"] + packet["inputs"]["synthesize"]["examples"]},
                "issues": [], "coverage_assessment": "Synthetic, not real source review."}
    return result(packet, ["knowledge"])


def drive(production, root, respond=result, name=lambda packet: packet["claim_token"]):
    """Claim/collect until nothing is claimable; deterministic steps run inside claim."""
    stages = []
    while (packet := production.claim(root, "test")):
        stages.append(packet["stage"])
        production.collect(root, packet["task_id"], packet["claim_token"], respond(packet), executor(name(packet)))
    return stages
