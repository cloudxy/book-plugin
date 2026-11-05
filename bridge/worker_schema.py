"""Structured-output contracts for the optional command adapter."""
from distill_skill import KINDS, REALITY, VOICES
from production_stages import AUDIT_PROBLEMS, ENTRY_STATUS, REPAIR_STAGES, RISK_FLAGS

BASE_DIMENSIONS = ("fidelity", "application", "utility")
ATTRIBUTION = ("read", "synthesize", "examples", "build", "evaluation", "unknown")


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def array(items):
    return {"type": "array", "items": items}


def choice(*values):
    return {"type": "string", "enum": list(values)}


TEXT = {"type": "string"}
TEXTS = array(TEXT)
SCORE = obj({"score": {"type": "integer", "minimum": 0, "maximum": 3}, "reason": TEXT, "excerpt": TEXT})
REPAIRS = array(obj({"stage": choice(*REPAIR_STAGES), "targets": TEXTS, "problem": TEXT}))


def _decisions(ids):
    decision = obj({"verdict": choice("pass", "fail"), "reason": TEXT})
    return obj({i: decision for i in ids})


def _synthesis(packet):
    v2 = packet.get("output_contract") == "distilled-capability/2"
    fields = {"id": TEXT, "kind": choice(*KINDS), "name": TEXT, "trigger": TEXT, "actions": TEXTS, "conditions": TEXTS,
              "changes": TEXTS, "evidence": TEXTS, "epistemic_status": choice("explicit", "reconstructed")}
    if v2:
        fields.update(voice=choice(*VOICES), reality=choice(*REALITY))
    example = obj({"id": TEXT, "capabilities": TEXTS, "task": TEXT, "answer": TEXT, "changed_task": TEXT,
                   "changed_answer": TEXT, "origin": choice("synthetic", "source_reconstruction")})
    body = {"schema_version": choice("distilled-capability/2" if v2 else "distilled-capability/1"), "description": TEXT, "core": TEXT,
            "uses": TEXTS, "limits": TEXTS, "capabilities": array(obj(fields)), "examples": array(example),
            "procedures": obj({"status": choice("not_applicable", "requires_legacy_gate"), "reason": TEXT})}
    if v2:
        body["inputs"] = TEXTS
        body["episodes"] = array(obj({"id": TEXT, "capabilities": TEXTS, "problem": TEXT, "path": TEXTS, "tradeoff": TEXT,
                                      "revision": TEXT, "evidence": TEXTS}))
        body["habits"] = array(obj({"id": TEXT, "name": TEXT, "steps": TEXTS, "when": TEXT, "counter_signal": TEXT, "evidence": TEXTS}))
        if "expression" in packet.get("product", {}).get("profiles", []):
            body["profile"] = obj({"voice_layer": choice(*VOICES), "structure": TEXTS, "rhythm": TEXTS, "devices": TEXTS,
                                   "diction": TEXTS, "avoid": TEXTS, "evidence": TEXTS})
    return obj(body)


def for_packet(packet):
    stage = packet.get("stage")
    contract = packet.get("output_contract")
    if stage in {"read", "merge"}:
        body = {"covered_units": TEXTS, "findings": TEXT, "limitations": TEXTS, "open_connections": TEXTS}
        if contract == "read/2":
            entry = obj({"type": choice(*packet["entry_types"]), "content": TEXT, "voice": choice(*VOICES),
                         "status": choice(*ENTRY_STATUS), "reality": choice(*REALITY)})
            body.update(entries=array(entry), risk_flags=array(choice(*RISK_FLAGS)))
        if contract == "merge/2":
            body["conflicts"] = TEXTS
        return obj(body)
    if stage == "audit-part":
        decision = obj({"verdict": choice("pass", "fail"), "problems": array(choice(*AUDIT_PROBLEMS)), "reason": TEXT})
        return obj({"decisions": obj({uid: decision for uid in packet["items"]}), "notes": TEXT})
    if stage == "synthesize":
        return _synthesis(packet)
    if stage in {"review", "review-part"}:
        model = packet["inputs"]["synthesize"]
        ids = packet.get("decision_ids") or [item["id"] for item in model["capabilities"] + model["examples"]]
        body = {"decisions": _decisions(ids), "issues": TEXTS, "coverage_assessment": TEXT}
        if contract in {"review/2", "review-part/1"}:
            body["repairs"] = REPAIRS
        if stage == "review":
            body = {"verdict": choice("pass", "fail"), **body}
        return obj(body)
    if "conversation" in packet:
        return obj({"answer": TEXT})
    if "rubric" in packet and "answers" in packet:
        dims = packet.get("dimensions") or BASE_DIMENSIONS
        body = {"dimensions": obj({d: SCORE for d in dims}), "hard_failures": TEXTS}
        if packet.get("attribution_required"):
            body["attribution"] = array(obj({"stage": choice(*ATTRIBUTION), "capabilities": TEXTS, "problem": TEXT, "evidence": TEXT}))
        return obj(body)
    return None
