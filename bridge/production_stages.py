"""Stage modules of the production DAG: contracts, packets, result checks, layout, repair routing.

A run pins the module set named in state["prompts"]. Flat 0.5.0 instruction files
stay valid for runs started with them; kinds they lack use the bundled module set.
Packets carry only the task's dependency closure. Oversized review/audit work is
split by budget into independent parts and aggregated by script, never truncated.
"""
from __future__ import annotations

import bisect
import json
import math
from pathlib import Path
import re

from book_skill_common import ContractError, digest, read_json, text
from production_common import strings
from distill_skill import KINDS, MODEL_SCHEMA, MODEL_SCHEMA_V2, REALITY, VOICES, validate_model

REFERENCES = Path(__file__).resolve().parents[1] / "skills/book-workflow/references"
LEGACY_PROMPTS = REFERENCES / "production-prompts.json"
MODULES = REFERENCES / "production-modules.json"
GENRES = ("argument", "narrative", "serial", "poetry", "science")
PYTHON_KINDS = {"build", "audit", "ledger"}
OUTPUT = {"read": "read/2", "merge": "merge/2", "audit-part": "audit/1", "synthesize": MODEL_SCHEMA_V2,
          "review": "review/2", "review-part": "review-part/1"}
AUDIT_PROBLEMS = ("faithfulness", "qualifier", "voice", "purpose", "omission")
RISK_FLAGS = ("numbers-units", "causal-extrapolation", "cross-unit", "voice-confusion")
ENTRY_STATUS = ("explicit", "inferred", "unresolved")
REPAIR_STAGES = ("read", "merge", "synthesize")
DEFAULT_PART_CHARS = 200000
_CACHE = {}


def load(path):
    path = Path(path)
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _CACHE:
        if len(_CACHE) > 32:
            _CACHE.clear()
        _CACHE[key] = read_json(path)
    return _CACHE[key]


def module_data(state):
    return load(state.get("prompts") or MODULES)


def legacy(state):
    return module_data(state).get("schema_version") != "stage-modules/1"


def bundled():
    return load(MODULES)


def features(state):
    return {} if legacy(state) else module_data(state).get("features", {})


def stage_module(state, kind):
    """The exact module a task runs with; its digest is part of the task cache key."""
    data = module_data(state)
    if data.get("schema_version") == "stage-modules/1":
        return data["modules"][kind]
    if kind in data:
        return {"legacy_instruction": data[kind]}
    if kind == "build":
        return {"legacy_instruction": None}  # frozen 0.5.0 build contract
    return bundled()["modules"][kind]


def genres_for(state, source=None):
    product = state["product"]
    chosen = (source or {}).get("genres") or product.get("genres")
    if not chosen:
        mapping = (bundled() if legacy(state) else module_data(state))["profile_genres"]
        chosen = sorted({g for p in product["profiles"] for g in mapping.get(p, [])})
    return chosen


def templates(state, source=None):
    data = bundled() if legacy(state) else module_data(state)
    product = state["product"]
    result = {"profiles": {k: data["profiles"][k] for k in product["profiles"]},
              "genres": {g: data["genres"][g] for g in genres_for(state, source)}}
    if product["object"] == "person":
        result["person_voices"] = data["person_voices"]
    return result


def entry_types(state, source=None):
    data = bundled() if legacy(state) else module_data(state)
    return {o for g in genres_for(state, source) for o in data["genres"][g]["objects"]} | {"other"}


# ---- intake: body boundary, issues and positions that map back to chapter/page/timecode

HEADING = re.compile(r"^[ \t]*(?:#{1,6}[ \t]+\S.*|第[0-9一二三四五六七八九十百千零〇两]+[章节回卷篇部集讲].*|卷[0-9一二三四五六七八九十百千零〇]+.*"
                     r"|(?:Chapter|CHAPTER|Part|PART|Book|BOOK)[ \t]+[0-9IVXLCivxlc]+\b.*)$", re.M)
PAGE = re.compile(r"\[(?:p\.?|page|页)[ \t]*(\d+)\]|^[ \t]*[-—][ \t]*(\d+)[ \t]*[-—][ \t]*$", re.I | re.M)
TIMECODE = re.compile(r"(?<!\d)(\d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2})(?!\d)")


def body_range(body, boundary):
    if not boundary:
        return 0, len(body)
    start = boundary.get("start", 0)
    end = boundary.get("end", len(body))
    if boundary.get("start_marker"):
        start = body.find(boundary["start_marker"])
        if start < 0:
            raise ContractError("body start marker not found")
    if boundary.get("end_marker"):
        end = body.find(boundary["end_marker"], start)
        if end < 0:
            raise ContractError("body end marker not found")
    if not 0 <= start < end <= len(body):
        raise ContractError("empty or invalid declared body range")
    return start, end


def position_index(body):
    headings = [(m.start(), m.group(0).strip()[:80]) for m in HEADING.finditer(body)]
    pages = [(m.start(), int(m.group(1) or m.group(2))) for m in PAGE.finditer(body)]
    feeds = [i for i, ch in enumerate(body) if ch == "\f"]
    return {"headings": headings, "pages": pages, "feeds": feeds, "newlines": [i for i, ch in enumerate(body) if ch == "\n"]}


def locate(body, index, start, end):
    """Automatic position reference; exact quotations stay optional."""
    lines = index["newlines"]
    result = {"lines": [bisect.bisect_left(lines, start) + 1, bisect.bisect_left(lines, max(start, end - 1)) + 1]}
    heads = index["headings"]
    before = bisect.bisect_right([p for p, _ in heads], start) - 1
    inside = [h for p, h in heads if start <= p < end]
    if before >= 0 or inside:
        result["headings"] = ([heads[before][1]] if before >= 0 else []) + inside[:5]
    marks = index["pages"]
    i = bisect.bisect_right([p for p, _ in marks], start) - 1
    if i >= 0:
        result["page"] = marks[i][1]
    elif index["feeds"]:
        result["page"] = bisect.bisect_left(index["feeds"], start) + 1
    codes = TIMECODE.findall(body[start:end])
    if codes:
        result["timecodes"] = [codes[0], codes[-1]]
    return result


def source_issues(body):
    found = []
    if "�" in body:
        found.append(f"replacement characters: {body.count(chr(0xfffd))} (possible OCR/encoding loss)")
    controls = sum(1 for ch in body if ord(ch) < 32 and ch not in "\n\r\t\f")
    if controls:
        found.append(f"control characters: {controls}")
    return found


# ---- packets

def compact(result):
    return {k: result[k] for k in ("covered_units", "findings", "conflicts", "limitations", "open_connections") if k in result}


def output_of(root, state, tid):
    return read_json(Path(root) / state["tasks"][tid]["output"])["result"]


def source_meta(state, uid):
    unit = state["units"][uid]
    source = next(s for s in state["sources"] if s["id"] == unit["source"])
    return source, {k: v for k, v in source.items() if k not in {"path", "snapshot"}}


def source_text(root, state, uid):
    unit = state["units"][uid]
    source = next(s for s in state["sources"] if s["id"] == unit["source"])
    value = (Path(root) / source["snapshot"]).read_text(encoding="utf-8")[unit["start"]:unit["end"]]
    if digest(value.encode()) != unit["sha256"]:
        raise ContractError("source snapshot changed")
    return value


def review_ids(model):
    ids = [c["id"] for c in model["capabilities"]] + [e["id"] for e in model["examples"]]
    if model.get("schema_version") == MODEL_SCHEMA_V2:
        ids += [x["id"] for x in model.get("episodes", [])] + [x["id"] for x in model.get("habits", [])]
        ids += ["PROFILE"] if model.get("profile") else []
    return ids


def target_evidence(model):
    caps = {c["id"]: list(c["evidence"]) for c in model["capabilities"]}
    out = dict(caps)
    for e in model["examples"]:
        out[e["id"]] = sorted({u for c in e["capabilities"] for u in caps.get(c, [])})
    if model.get("schema_version") == MODEL_SCHEMA_V2:
        for x in model.get("episodes", []) + model.get("habits", []):
            out[x["id"]] = list(x["evidence"])
        if model.get("profile"):
            out["PROFILE"] = list(model["profile"]["evidence"])
    return out


def cited_units(model):
    return sorted({u for units in target_evidence(model).values() for u in units})


def audit_summary(root, state):
    t = state["tasks"].get("audit")
    if not t or t["status"] != "done":
        return None
    result = output_of(root, state, "audit")
    return {k: result.get(k) for k in ("verdict", "failed_units", "gaps", "sample")}


def _legacy_packet(root, state, tid, prompt):
    t = state["tasks"][tid]
    data = {"schema_version": "book-production/1", "task_id": tid, "stage": t["kind"], "instruction": prompt,
            "product": state["product"], "feedback": t.get("feedback"), "inputs": {}}
    for dep in (["synthesize"] if t["kind"] == "review" else t["deps"]):
        data["inputs"][dep] = output_of(root, state, dep)
    if t["kind"] == "read":
        data["source_unit"] = {"id": tid, **state["units"][tid], "text": source_text(root, state, tid)}
        data["source_metadata"] = source_meta(state, tid)[1]
    elif t["kind"] == "review":
        model = data["inputs"]["synthesize"]
        uids = sorted({u for c in model["capabilities"] for u in c["evidence"]})
        data["source_units"] = {uid: source_text(root, state, uid) for uid in uids}
        data["sources"] = [{k: v for k, v in s.items() if k not in {"path", "snapshot"}} for s in state["sources"]]
        data["reading_findings"] = {uid: output_of(root, state, uid) for uid in state["units"]}
    elif t["kind"] == "synthesize":
        data["source_units"] = list(state["units"])
        data["output_schema"] = MODEL_SCHEMA
    return data


def packet(root, state, tid):
    t = state["tasks"][tid]
    kind = t["kind"]
    module = stage_module(state, kind)
    if "legacy_instruction" in module:
        return _legacy_packet(root, state, tid, module["legacy_instruction"] or "")
    data = {"schema_version": "book-production/1", "task_id": tid, "stage": kind, "instruction": module["instruction"],
            "module": {k: module[k] for k in ("version", "contract", "examples", "failure_handling")},
            "output_contract": OUTPUT[kind], "product": state["product"], "feedback": t.get("feedback"), "inputs": {}}
    if kind == "read":
        source, meta = source_meta(state, tid)
        data["templates"] = templates(state, source)
        data["source_unit"] = {"id": tid, **state["units"][tid], "text": source_text(root, state, tid)}
        data["source_metadata"] = meta
        data["entry_types"] = sorted(entry_types(state, source))
        return data
    data["templates"] = templates(state)
    if kind == "merge":
        data["inputs"] = {dep: compact(output_of(root, state, dep)) for dep in t["deps"]}
    elif kind == "audit-part":
        data["items"] = {uid: {"text": source_text(root, state, uid), "locator": state["units"][uid].get("locator"),
                               "reading": output_of(root, state, uid)} for uid in t["items"]}
    elif kind == "synthesize":
        data["inputs"] = {dep: compact(output_of(root, state, dep)) for dep in t["deps"] if dep != "audit"}
        data["source_units"] = list(state["units"])
        data["audit"] = audit_summary(root, state)
        data["output_schema"] = MODEL_SCHEMA if legacy(state) else MODEL_SCHEMA_V2
        if legacy(state):
            data["output_contract"] = MODEL_SCHEMA
    elif kind in {"review", "review-part"}:
        model = output_of(root, state, "synthesize")
        data["inputs"] = {"synthesize": model}
        data["sources"] = [{k: v for k, v in s.items() if k not in {"path", "snapshot"}} for s in state["sources"]]
        cited = set(cited_units(model))
        units = list(state["units"]) if kind == "review" else t["items"]
        data["reading_findings"] = {uid: compact(output_of(root, state, uid)) for uid in units}
        data["source_units"] = {uid: source_text(root, state, uid) for uid in units if uid in cited}
        data["decision_ids"] = review_ids(model) if kind == "review" else t["assigned"]
        data["audit"] = audit_summary(root, state)
        if kind == "review-part":
            data["assigned"] = t["assigned"]
    return data


# ---- result contracts

def _executor(executor):
    for field in ("session_id", "host", "model"):
        text(executor.get(field), f"executor.{field}")


def _generator_sessions(root, state, kinds=("read", "merge", "synthesize"), only=None):
    sessions = set()
    for tid, t in state["tasks"].items():
        if t["status"] == "done" and t["kind"] in kinds and (only is None or tid in only):
            sessions.add(read_json(Path(root) / t["output"])["executor"]["session_id"])
    return sessions


def _repairs(state, model, value):
    strings([r.get("problem") for r in value] or ["-"], "repairs.problem")
    caps = set(review_ids(model)) if model else set()
    merges = {tid for tid, t in state["tasks"].items() if t["kind"] == "merge"}
    for item in value:
        stage = item.get("stage")
        if stage not in REPAIR_STAGES:
            raise ContractError("repair stage must be read/merge/synthesize")
        targets = strings(item.get("targets"), "repairs.targets", allow_empty=True)
        allowed = {"read": set(state["units"]), "merge": merges, "synthesize": caps}[stage]
        if not set(targets) <= allowed:
            raise ContractError(f"repair targets unknown for {stage}")


def validate_result(root, state, tid, result, executor):
    t = state["tasks"][tid]
    kind = t["kind"]
    _executor(executor)
    module = stage_module(state, kind)
    old = "legacy_instruction" in module
    if kind in {"read", "merge"}:
        strings(result.get("covered_units"), "covered_units")
        expected = {tid} if kind == "read" else set()
        if kind == "merge":
            for dep in t["deps"]:
                expected.update(output_of(root, state, dep)["covered_units"])
        if set(result["covered_units"]) != expected:
            raise ContractError("reading/merge must account for every assigned unit")
        text(result.get("findings"), "findings")
        strings(result.get("limitations"), "limitations", allow_empty=True)
        strings(result.get("open_connections"), "open_connections", allow_empty=True)
        if old:
            return
        if kind == "merge":
            strings(result.get("conflicts"), "conflicts", allow_empty=True)
            return
        allowed = entry_types(state, source_meta(state, tid)[0])
        entries = result.get("entries")
        if not isinstance(entries, list):
            raise ContractError("typed entries list required (may be empty)")
        for entry in entries:
            if entry.get("type") not in allowed:
                raise ContractError(f"entry type not in selected templates: {entry.get('type')}")
            text(entry.get("content"), "entry.content")
            if entry.get("voice") not in VOICES or entry.get("status") not in ENTRY_STATUS or entry.get("reality") not in REALITY:
                raise ContractError("entry voice/status/reality required")
        if not set(strings(result.get("risk_flags"), "risk_flags", allow_empty=True)) <= set(RISK_FLAGS):
            raise ContractError("unknown risk flag")
    elif kind == "audit-part":
        if executor["session_id"] in _generator_sessions(root, state, ("read",), set(t["items"])):
            raise ContractError("audit session must be independent of the sampled readers")
        decisions = result.get("decisions", {})
        if set(decisions) != set(t["items"]):
            raise ContractError("audit must decide every sampled unit")
        for uid, value in decisions.items():
            if value.get("verdict") not in {"pass", "fail"}:
                raise ContractError(f"invalid audit verdict: {uid}")
            text(value.get("reason"), f"{uid}.reason")
            problems = strings(value.get("problems"), f"{uid}.problems", allow_empty=value["verdict"] == "pass")
            if not set(problems) <= set(AUDIT_PROBLEMS):
                raise ContractError("unknown audit problem")
        text(result.get("notes"), "notes")
    elif kind == "synthesize":
        expected = MODEL_SCHEMA if old or legacy(state) else MODEL_SCHEMA_V2
        if result.get("schema_version") != expected:
            raise ContractError(f"synthesis must use {expected}")
        validate_model(result, state["units"], state["product"]["profiles"])
    elif kind in {"review", "review-part"}:
        if executor["session_id"] in _generator_sessions(root, state):
            raise ContractError("review session must be independent of all generators")
        model = output_of(root, state, "synthesize")
        expected = set(review_ids(model)) if kind == "review" else set(t["assigned"])
        decisions = result.get("decisions", {})
        if set(decisions) != expected:
            raise ContractError("review must cover each capability and example")
        for key, value in decisions.items():
            if value.get("verdict") not in {"pass", "fail"}:
                raise ContractError(f"invalid review verdict: {key}")
            text(value.get("reason"), f"{key}.reason")
        strings(result.get("issues"), "issues", allow_empty=True)
        text(result.get("coverage_assessment"), "coverage_assessment")
        if not old:
            if not isinstance(result.get("repairs"), list):
                raise ContractError("repairs list required (empty when nothing to repair)")
            _repairs(state, model, result["repairs"])
        if kind == "review":
            failing = result["issues"] or any(v["verdict"] != "pass" for v in decisions.values()) or result.get("repairs")
            if result.get("verdict") not in {"pass", "fail"} or (result["verdict"] == "pass" and failing):
                raise ContractError("review aggregate conflicts with decisions")


# ---- budget layout: split oversized review/audit work into independent parts

def part_limit(state, single=False):
    policy = state["policy"]
    limits = [policy.get("max_input_chars", 250000)]
    if not single:
        limits.append(policy.get("part_input_chars", DEFAULT_PART_CHARS))
    host = state.get("host_limits", {}).get("max_input_chars") or policy.get("host_max_input_chars")
    if host:
        limits.append(host)
    return int(min(limits) * (0.98 if single else 0.95))


def size(value):
    return len(json.dumps(value, ensure_ascii=False))


def _pack(order, cost, base, limit):
    parts, current, used = [], [], base
    for uid in order:
        if current and used + cost[uid] > limit:
            parts.append(current)
            current, used = [], base
        current.append(uid)
        used += cost[uid]
    if current:
        parts.append(current)
    return parts


def _apply(state, stage, parts, stage_deps, mode, extra=None):
    tasks = state["tasks"]
    prefix = f"{stage}-part-"
    wanted = {}
    for i, spec in enumerate(parts, 1):
        wanted[f"{prefix}{i:03}"] = spec
    for pid, spec in wanted.items():
        current = tasks.get(pid)
        if not (current and current["deps"] == spec["deps"] and current.get("items") == spec["items"]
                and current.get("assigned") == spec.get("assigned")):
            tasks[pid] = {"kind": f"{stage}-part", "deps": spec["deps"], "status": "queued", "attempts": 0,
                          "items": spec["items"], **({"assigned": spec["assigned"]} if "assigned" in spec else {})}
    for pid in [k for k in tasks if k.startswith(prefix) and k not in wanted]:
        del tasks[pid]
    t = tasks[stage]
    if t["deps"] != stage_deps or t.get("mode", "model") != mode:
        keep = {k: t[k] for k in ("accepted_gaps",) if k in t}
        tasks[stage] = {"kind": stage, "deps": stage_deps, "status": "queued", "attempts": 0, "mode": mode, **keep, **(extra or {})}


def layout(root, state):
    if features(state).get("audit"):
        _layout_audit(root, state)
    _layout_review(root, state)


def _done(state, tid, root):
    t = state["tasks"].get(tid)
    return bool(t and t["status"] == "done" and t.get("output") and (Path(root) / t["output"]).exists())


def _layout_review(root, state):
    tasks = state["tasks"]
    if not _done(state, "synthesize", root):
        return  # keep the current layout; dependency status makes parts stale
    reads = {u: tasks[u].get("output_hash") for u in state["units"]}
    key = digest({"synthesize": tasks["synthesize"].get("output_hash"), "reads": reads,
                  "single": part_limit(state, True), "part": part_limit(state),
                  "modules": [digest(stage_module(state, k)) for k in ("review", "review-part")]})
    record = state.setdefault("layout", {}).get("review")
    if record and record.get("key") == key and all(p in tasks for p in record.get("parts", [])):
        return
    if tasks["review"]["status"] == "done" or any(not _done(state, u, root) for u in state["units"]):
        return  # never re-layout a completed stage; refresh decides whether it is stale
    model = output_of(root, state, "synthesize")
    single = packet(root, state, "review")
    if size(single) <= part_limit(state, True):
        _apply(state, "review", [], ["synthesize"], "model")
        state["layout"]["review"] = {"key": key, "mode": "single", "parts": [], "packet_chars": size(single)}
        return
    cited = set(cited_units(model))
    cost = {}
    for uid in state["units"]:
        cost[uid] = size(uid) * 2 + size(compact(output_of(root, state, uid))) + 8
        if uid in cited:
            cost[uid] += size(source_text(root, state, uid)) + size(uid) + 4
    probe = dict(tasks)
    base_task = {"kind": "review-part", "deps": ["synthesize"], "status": "queued", "attempts": 0,
                 "items": [], "assigned": review_ids(model)}
    probe["review-part-000"] = base_task
    base = size(packet(root, {**state, "tasks": probe}, "review-part-000"))
    groups = _pack(list(state["units"]), cost, base, part_limit(state))
    evidence = target_evidence(model)
    parts = []
    for items in groups:
        members = set(items)
        assigned = [c["id"] for c in model["capabilities"] if members & set(evidence[c["id"]])]
        parts.append({"deps": ["synthesize"] + items, "items": items, "assigned": assigned})
    for target in review_ids(model):
        if any(target == c["id"] for c in model["capabilities"]):
            continue
        units = evidence.get(target) or []
        home = next((p for p in parts if set(p["items"]) & set(units)), parts[-1])
        home["assigned"].append(target)
    for cap in model["capabilities"]:
        if not any(cap["id"] in p["assigned"] for p in parts):
            parts[-1]["assigned"].append(cap["id"])
    _apply(state, "review", parts, [f"review-part-{i:03}" for i in range(1, len(parts) + 1)], "python")
    state["layout"]["review"] = {"key": key, "mode": "parts", "parts": [f"review-part-{i:03}" for i in range(1, len(parts) + 1)],
                                 "packet_chars": size(single), "part_limit": part_limit(state)}


def select_sample(root, state):
    """Stratified, seeded selection the extractor cannot steer; plus risk flags and repair expansions."""
    units = list(state["units"])
    n = len(units)
    k = min(n, max(10, math.ceil(0.1 * n)))
    seed = state["source_snapshot_hash"]
    strata = {}
    by_source = {}
    for uid in units:
        by_source.setdefault(state["units"][uid]["source"], []).append(uid)
    for source, members in by_source.items():
        for i, uid in enumerate(members):
            strata.setdefault((source, int(10 * i / len(members))), []).append(uid)
    queues = [sorted(v, key=lambda u: digest(seed + u)) for _, v in sorted(strata.items())]
    base = []
    while len(base) < k:
        for queue in queues:
            if queue and len(base) < k:
                base.append(queue.pop(0))
    flagged = [u for u in units if u not in base and output_of(root, state, u).get("risk_flags")]
    flagged = sorted(flagged, key=lambda u: digest(seed + u))[:math.ceil(k / 2)]
    expanded = [u for u in state.get("audit", {}).get("expanded", []) if u not in base and u not in flagged]
    return {"rule": "stratified by source and position decile, seeded by source snapshot; size min(N, max(10, ceil(0.1*N))); "
                    "plus up to ceil(k/2) risk-flagged units; plus failed units and neighbours after repair",
            "N": n, "k": k, "seed": seed, "base": sorted(base), "flagged": flagged, "expanded": expanded}


def _layout_audit(root, state):
    tasks = state["tasks"]
    reads = [u for u in state["units"]]
    if any(not _done(state, u, root) for u in reads):
        return
    key = digest({"reads": {u: tasks[u].get("output_hash") for u in reads}, "part": part_limit(state),
                  "expanded": state.get("audit", {}).get("expanded", []), "module": digest(stage_module(state, "audit-part"))})
    record = state.setdefault("layout", {}).get("audit")
    if record and record.get("key") == key and all(p in tasks for p in record.get("parts", [])):
        return
    if tasks["audit"]["status"] == "done":
        return
    sample = select_sample(root, state)
    order = sample["base"] + sample["flagged"] + sample["expanded"]
    cost = {u: size(source_text(root, state, u)) + size(output_of(root, state, u)) + size(u) * 2 + 64 for u in order}
    probe = dict(tasks)
    probe["audit-part-000"] = {"kind": "audit-part", "deps": [], "status": "queued", "attempts": 0, "items": []}
    base = size(packet(root, {**state, "tasks": probe}, "audit-part-000"))
    groups = _pack(order, cost, base, part_limit(state))
    parts = [{"deps": items, "items": items} for items in groups]
    names = [f"audit-part-{i:03}" for i in range(1, len(parts) + 1)]
    _apply(state, "audit", parts, names, "python")
    state.setdefault("audit", {})["sample"] = sample
    state["layout"]["audit"] = {"key": key, "parts": names, "part_limit": part_limit(state)}


# ---- deterministic aggregation and L1 materials

def aggregate_review(root, state):
    model = output_of(root, state, "synthesize")
    parts = state["tasks"]["review"]["deps"]
    decisions, issues, repairs, coverage = {}, [], [], []
    for pid in parts:
        result = output_of(root, state, pid)
        for key, value in result["decisions"].items():
            current = decisions.setdefault(key, {"verdict": "pass", "reasons": []})
            current["reasons"].append(f"[{pid}] {value['reason']}")
            if value["verdict"] == "fail":
                current["verdict"] = "fail"
        issues += [f"[{pid}] {v}" for v in result["issues"]]
        repairs += [r for r in result.get("repairs", []) if r not in repairs]
        coverage.append(f"[{pid}] {result['coverage_assessment']}")
    missing = set(review_ids(model)) - set(decisions)
    if missing:
        raise ContractError(f"review parts left targets undecided: {sorted(missing)}")
    final = {k: {"verdict": v["verdict"], "reason": "；".join(v["reasons"])} for k, v in decisions.items()}
    verdict = "pass" if not issues and not repairs and all(v["verdict"] == "pass" for v in final.values()) else "fail"
    return {"verdict": verdict, "decisions": final, "issues": issues, "repairs": repairs,
            "coverage_assessment": "\n".join(coverage), "parts": parts, "aggregation": "script: any part fail => fail"}


def aggregate_audit(root, state):
    t = state["tasks"]["audit"]
    decisions = {}
    for pid in t["deps"]:
        decisions.update(output_of(root, state, pid)["decisions"])
    failed = sorted(u for u, v in decisions.items() if v["verdict"] == "fail")
    accepted = set(t.get("accepted_gaps", []))
    gaps = [u for u in failed if u in accepted]
    open_failures = [u for u in failed if u not in accepted]
    verdict = "fail" if open_failures else "pass-with-gaps" if gaps else "pass"
    return {"verdict": verdict, "failed_units": open_failures, "gaps": gaps, "decisions": decisions,
            "sample": state.get("audit", {}).get("sample"), "parts": t["deps"]}


def write_ledger(root, state):
    root = Path(root)
    tasks = state["tasks"]
    out = root / "l1"
    top = [d for d in tasks["ledger"]["deps"] if d != "audit"]
    overview = ["# Overview（L1 内部材料，不是 Skill）\n"] + [f"## {d}\n\n{output_of(root, state, d)['findings']}" for d in top]
    entries = []
    units = []
    for uid, unit in state["units"].items():
        result = output_of(root, state, uid)
        for i, entry in enumerate(result.get("entries", []), 1):
            entries.append({"id": f"{uid}-e{i:03}", "unit": uid, "locator": unit.get("locator"), **entry})
        units.append({"id": uid, **{k: unit[k] for k in ("source", "start", "end", "sha256")}, "locator": unit.get("locator"),
                      "read_output_sha256": tasks[uid].get("output_hash"), "entries": len(result.get("entries", [])),
                      "limitations": result.get("limitations", [])})
    excluded = [{"source": s["id"], "ranges": s.get("excluded", [])} for s in state["sources"]]
    ledger = {"schema_version": "reading-ledger/1", "units": units, "excluded": excluded,
              "issues": {s["id"]: s.get("issues", []) for s in state["sources"]},
              "audit": output_of(root, state, "audit") if "audit" in tasks else None,
              "note": "底账记录全部声明正文的实际阅读任务；哈希只绑定内容和位置，不证明理解。"}
    out.mkdir(parents=True, exist_ok=True)
    from production_common import atomic_json
    atomic_json(out / "ledger.json", ledger)
    (out / "overview.md").write_text("\n\n".join(overview) + "\n", encoding="utf-8")
    (out / "entries.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    return {"ledger": "l1/ledger.json", "overview": "l1/overview.md", "entries": "l1/entries.jsonl",
            "units": len(units), "typed_entries": len(entries), "tier": "L1-material (not a Skill)"}


# ---- failure attribution: route a failure to the smallest stage that can repair it

def reset(task):
    task["status"] = "stale"
    task["attempts"] = 0
    for key in ("output_hash", "input_hash", "lease", "not_before", "blocked", "transient", "error"):
        task.pop(key, None)


def repair_rounds(state, origin):
    return state.get("repairs", {}).get(origin, 0)


def route_review_failure(state, result, now):
    """Review repairs go to read/merge/synthesize; synthesis always receives the review."""
    tasks = state["tasks"]
    routes = []
    for item in result.get("repairs") or []:
        stage, targets = item["stage"], item.get("targets", [])
        if stage == "synthesize":
            continue
        valid = [x for x in targets if x in tasks and tasks[x]["kind"] == stage]
        for tid in valid:
            tasks[tid]["feedback"] = {"origin": "review", "problem": item["problem"]}
            reset(tasks[tid])
        if valid:
            routes.append({"stage": stage, "targets": valid, "problem": item["problem"]})
    synth = tasks["synthesize"]
    if legacy(state) and "legacy_instruction" in stage_module(state, "synthesize"):
        synth["feedback"] = result
    else:
        synth["feedback"] = {"origin": "review", "issues": result.get("issues", []),
                             "failed": {k: v for k, v in result.get("decisions", {}).items() if v["verdict"] != "pass"},
                             "repairs": [r for r in result.get("repairs", []) if r["stage"] == "synthesize"]}
    reset(synth)
    routes.append({"stage": "synthesize", "targets": [k for k, v in result.get("decisions", {}).items() if v["verdict"] != "pass"]})
    state.setdefault("repairs", {})["review"] = repair_rounds(state, "review") + 1
    return routes


def route_audit_failure(state, result, now):
    tasks = state["tasks"]
    failed = result["failed_units"]
    for uid in failed:
        decision = result["decisions"][uid]
        tasks[uid]["feedback"] = {"origin": "audit", "problems": decision["problems"], "problem": decision["reason"]}
        reset(tasks[uid])
    units = list(state["units"])
    expanded = state.setdefault("audit", {}).setdefault("expanded", [])
    for uid in failed:
        i = units.index(uid)
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(units) and state["units"][units[j]]["source"] == state["units"][uid]["source"] and units[j] not in expanded:
                expanded.append(units[j])
    state.setdefault("repairs", {})["audit"] = repair_rounds(state, "audit") + 1
    return [{"stage": "read", "targets": failed, "problem": "independent sampled audit failed; neighbours added to the next sample"}]
