"""Structured-output contracts for the optional command adapter."""


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def array(items):
    return {"type": "array", "items": items}


def choice(*values):
    return {"type": "string", "enum": list(values)}


TEXT = {"type": "string"}
TEXTS = array(TEXT)
SCORE = obj({"score": {"type": "integer", "minimum": 0, "maximum": 3}, "reason": TEXT, "excerpt": TEXT})


def for_packet(packet):
    stage = packet.get("stage")
    if stage in {"read", "merge"}:
        return obj({"covered_units": TEXTS, "findings": TEXT, "limitations": TEXTS, "open_connections": TEXTS})
    if stage == "synthesize":
        capability = obj({"id": TEXT, "kind": choice("knowledge", "thought", "narrative", "expression"), "name": TEXT,
                          "trigger": TEXT, "actions": TEXTS, "conditions": TEXTS, "changes": TEXTS,
                          "evidence": TEXTS, "epistemic_status": choice("explicit", "reconstructed")})
        example = obj({"id": TEXT, "capabilities": TEXTS, "task": TEXT, "answer": TEXT, "changed_task": TEXT,
                       "changed_answer": TEXT, "origin": choice("synthetic", "source_reconstruction")})
        return obj({"schema_version": choice("distilled-capability/1"), "description": TEXT, "core": TEXT,
                    "uses": TEXTS, "limits": TEXTS, "capabilities": array(capability), "examples": array(example),
                    "procedures": obj({"status": choice("not_applicable", "requires_legacy_gate"), "reason": TEXT})})
    if stage == "review":
        model = packet["inputs"]["synthesize"]
        decision = obj({"verdict": choice("pass", "fail"), "reason": TEXT})
        return obj({"verdict": choice("pass", "fail"), "decisions": obj({item["id"]: decision for item in model["capabilities"] + model["examples"]}),
                    "issues": TEXTS, "coverage_assessment": TEXT})
    if "conversation" in packet:
        return obj({"answer": TEXT})
    if "rubric" in packet and "answers" in packet:
        return obj({"dimensions": obj({d: SCORE for d in ("fidelity", "application", "utility")}), "hard_failures": TEXTS})
    return None
