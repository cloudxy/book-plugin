"""Source/structure checks plus explicit, hash-bound semantic review records.

Exit 0: reviewed; 1: failed; 2: usage; 3: semantic review pending.
Mechanical quote hits never grant semantic approval.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from book_skill_common import (ContractError, SCHEMA, SUPPORTED_SCHEMAS, digest, input_snapshot, load_source,
    markdown_records, qnorm, read_json, read_yaml, section, slug, text, write_json)


def items(value, label):
    if not isinstance(value, list):
        raise ContractError(f"{label}: list required")
    return value


def references(value, known, label, required=True):
    refs = items(value, label)
    if required and not refs:
        raise ContractError(f"{label}: references required")
    if any(not isinstance(ref, str) or ref not in known for ref in refs):
        raise ContractError(f"{label}: unknown reference")
    return refs


def validate(book, source):
    book = Path(book)
    snapshot = input_snapshot(book, source)
    model = read_yaml(book / "thinking/model.yaml")
    schema = model.get("schema_version")
    if schema not in SUPPORTED_SCHEMAS:
        raise ContractError(f"unsupported model schema: {schema}")
    persona = schema == SCHEMA
    meta = model.get("book", {})
    slug(meta.get("id"))
    for name in ("title", "author", "edition", "kind", "description"):
        text(meta.get(name), f"book.{name}")
    text(model.get("authored_by"), "authored_by")
    scope = model.get("scope", {})
    for name in ("coverage", "includes", "excludes"):
        text(scope.get(name), f"scope.{name}")
    evidence = read_yaml(book / "evidence/anchors.yaml")
    if evidence.get("schema_version") != schema or evidence.get("source") != snapshot["source"]:
        raise ContractError("evidence source version/hash/normalization differs from actual source")
    src = qnorm(load_source(source))
    anchors = {}
    for anchor in items(evidence.get("anchors"), "anchors"):
        aid = text(anchor.get("id"), "anchor.id")
        if aid in anchors:
            raise ContractError(f"duplicate anchor id: {aid}")
        quote = text(anchor.get("quote"), f"{aid}.quote")
        normalized = qnorm(quote)
        limit = len(normalized) <= 150 if re_cjk(quote) else len(quote.split()) <= 100
        if not limit:
            raise ContractError(f"{aid}: quote exceeds short-quote limit")
        start = anchor.get("start")
        if type(start) is not int or start < 0 or src[start:start + len(normalized)] != normalized:
            raise ContractError(f"{aid}: quote not at declared qnorm offset")
        text(anchor.get("locator"), f"{aid}.locator")
        context = anchor.get("context", {})
        for name in ("text", "speaker", "audience", "period", "level"):
            text(context.get(name), f"{aid}.context.{name}")
        cstart, ctext = context.get("start"), qnorm(context["text"])
        if (type(cstart) is not int or cstart < 0 or src[cstart:cstart + len(ctext)] != ctext
                or not (cstart <= start and start + len(normalized) <= cstart + len(ctext))):
            raise ContractError(f"{aid}: context does not contain the declared quote instance")
        anchors[aid] = anchor
    if not anchors:
        raise ContractError("at least one source anchor required")

    episodes = {}
    if persona:
        from author_persona import episodes_from
        episodes = episodes_from(book, snapshot, src, anchors)
    nodes, kinds = {}, {}
    node_kinds = ("concerns", "concepts", "claims", "relations", "operators", "conflicts")
    if persona:
        node_kinds += ("habits", "paths")
    for kind in node_kinds:
        values = items(model.get(kind), kind)
        required = kind in {"concerns", "operators", "habits", "paths"} if persona else kind != "conflicts"
        if required and not values:
            raise ContractError(f"{kind}: at least one item required")
        for node in values:
            nid = text(node.get("id"), f"{kind}.id")
            if nid in nodes:
                raise ContractError(f"duplicate model id: {nid}")
            if node.get("epistemic_status") not in {"explicit", "reconstructed", "unresolved"}:
                raise ContractError(f"{nid}: invalid epistemic_status")
            for field in ("statement", "conditions", "speaker"):
                text(node.get(field), f"{nid}.{field}")
            references(node.get("anchors"), anchors, f"{nid}.anchors")
            nodes[nid], kinds[nid] = node, kind
    for nid, node in nodes.items():
        for field in ("depends_on", "limits"):
            references(node.get(field, []), nodes, f"{nid}.{field}", False)
        if kinds[nid] == "relations":
            references([node.get("from"), node.get("to")], nodes, f"{nid}.endpoints")
            if node.get("type") not in {"causal", "conditional", "value", "analogy", "narrative",
                                        "supports", "constrains", "contradicts", "depends_on"}:
                raise ContractError(f"{nid}: unknown relation type")
        if kinds[nid] == "operators":
            references(node.get("uses"), nodes, f"{nid}.uses")
            for field in ("intent", "inputs", "move", "warrant", "alternatives", "blocked_by", "revise_when"):
                text(node.get(field), f"{nid}.{field}")

    if persona:
        from author_persona import node_contracts
        node_contracts(nodes, kinds, episodes)
    core = model.get("core", {})
    text(core.get("text"), "core.text")
    pending = list(references(core.get("include"), nodes, "core.include"))
    closure = set()
    while pending:
        nid = pending.pop()
        if nid in closure:
            continue
        closure.add(nid)
        node = nodes[nid]
        if node["epistemic_status"] == "unresolved":
            raise ContractError(f"unresolved node in core dependency closure: {nid}")
        pending += node.get("depends_on", []) + node.get("limits", []) + node.get("uses", [])
        if kinds[nid] == "relations":
            pending += [node["from"], node["to"]]
        if kinds[nid] == "paths":
            pending += node["habits"] + node["operators"]
    if not any(kinds[nid] == "operators" for nid in closure):
        raise ContractError("core must include at least one usable thought operation")

    profile = (book / "expression/PROFILE.md").read_text(encoding="utf-8")
    summary = section(profile, "运行摘要")
    if markdown_records(summary):
        raise ContractError("runtime summary contains source metadata: end it with a separate level-two heading")
    styles = {}
    for style in markdown_records(profile):
        sid = text(style.get("id"), "style.id")
        if sid in styles:
            raise ContractError(f"duplicate style id: {sid}")
        for field in ("instruction", "context", "function", "limits"):
            text(style.get(field), f"{sid}.{field}")
        references(style.get("anchors"), anchors, f"{sid}.anchors")
        references(style.get("uses"), nodes, f"{sid}.uses")
        styles[sid] = style
    if not styles:
        raise ContractError("profile needs source-grounded style records in YAML fences")

    examples = {}
    for example in markdown_records((book / "thinking/EXAMPLES.md").read_text(encoding="utf-8")):
        eid = text(example.get("id"), "example.id")
        if eid in examples:
            raise ContractError(f"duplicate example id: {eid}")
        if example.get("kind") not in {"source_reconstruction", "application", "condition_variant"}:
            raise ContractError(f"{eid}: distinguish source reconstruction and synthetic application")
        for field in ("prompt", "answer", "rationale", "assumptions", "change_if"):
            text(example.get(field), f"{eid}.{field}")
        references(example.get("anchors"), anchors, f"{eid}.anchors")
        references(example.get("uses"), nodes, f"{eid}.uses")
        references(example.get("expression"), styles, f"{eid}.expression")
        examples[eid] = example
    if not any(e["kind"] == "source_reconstruction" for e in examples.values()):
        raise ContractError("at least one original argument/narrative reconstruction required")
    for nid in closure:
        if kinds[nid] != "operators":
            continue
        refs = references(nodes[nid].get("examples"), examples, f"{nid}.examples")
        if not {"application", "condition_variant"}.issubset({examples[e]["kind"] for e in refs}):
            raise ContractError(f"{nid}: application and condition-change examples required")
        if any(nid not in examples[e]["uses"] for e in refs):
            raise ContractError(f"{nid}: example does not use this operation")
    author_targets = {}
    if persona:
        from author_persona import persona_contracts
        author_targets = persona_contracts(model, nodes, kinds, episodes, styles, examples, closure)
    procedures = model.get("procedures", {})
    if procedures.get("status") == "not_applicable":
        text(procedures.get("reason"), "procedures.reason")
        if snapshot["procedures"] is not None:
            raise ContractError("procedure Bundle exists: cannot declare not_applicable")
    elif procedures.get("status") == "bundle":
        if snapshot["procedures"] is None:
            raise ContractError("declared procedure Bundle is missing")
    else:
        raise ContractError("procedures.status must be bundle or not_applicable")
    checks = ["core", "coverage", "procedure_applicability"]
    checks += [f"anchor:{x}" for x in anchors]
    checks += [f"node:{x}" for x in nodes]
    checks += [f"style:{x}" for x in styles]
    checks += [f"example:{x}" for x in examples]
    if persona:
        checks += ["author"] + [f"episode:{x}" for x in episodes]
    if procedures["status"] == "bundle":
        bundle = read_yaml(book / ".cangjie/capabilities/verified.yaml")
        for cap in items(bundle.get("capabilities"), "procedure capabilities"):
            if cap.get("status", "active") == "active":
                checks.append("procedure_contract:" + text(cap.get("capability_id"), "capability_id"))
    if len(checks) != len(set(checks)):
        raise ContractError("duplicate review target/procedure id")
    return {"model": model, "evidence": evidence, "snapshot": snapshot,
            "input_sha256": digest(snapshot), "checks": sorted(checks),
            "core_closure": sorted(closure), "styles": styles, "examples": examples,
            "episodes": episodes, "author_targets": author_targets}


def re_cjk(value):
    return any("\u3400" <= c <= "\u9fff" for c in value)


def audit(book, source, review=None):
    try:
        data = validate(book, source)
        result = {"schema_version": data["model"]["schema_version"], "status": "pending", "structural": "passed",
                  "semantic": "pending", "input_sha256": data["input_sha256"],
                  "checks": data["checks"], "core_closure": data["core_closure"]}
        path = Path(review) if review else Path(book) / "eval/source-review.json"
        if path.is_file():
            record = read_json(path)
            if record.get("input_sha256") != data["input_sha256"]:
                raise ContractError("semantic review is stale: source/model/style/examples changed")
            reviewer = text(record.get("reviewer"), "reviewer")
            if record.get("independent") is not True or reviewer == data["model"]["authored_by"]:
                raise ContractError("independent semantic reviewer required")
            checks = record.get("checks", {})
            if set(checks) != set(data["checks"]):
                raise ContractError("semantic review must address every current target")
            for target, verdict in checks.items():
                text(verdict.get("rationale"), f"{target}.review rationale")
                if verdict.get("status") not in {"passed", "failed", "pending"}:
                    raise ContractError(f"{target}: invalid review status")
            statuses = {v["status"] for v in checks.values()}
            state = "failed" if "failed" in statuses else "pending" if "pending" in statuses else "passed"
            result.update(status=state, semantic=state, reviewer=reviewer,
                          review_sha256=digest(path.read_bytes()))
        return result
    except (ContractError, OSError, TypeError, KeyError, AttributeError, ValueError) as exc:
        return {"schema_version": SCHEMA, "status": "failed", "error": str(exc)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book-dir", required=True, type=Path)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--ws", required=True, type=Path)
    ap.add_argument("--review", type=Path)
    ap.add_argument("--prepare-review", type=Path, help="create pending template; never overwrite")
    args = ap.parse_args()
    result = audit(args.book_dir, args.source, args.review)
    if args.prepare_review:
        try:
            prepared = validate(args.book_dir, args.source)
            result = {"schema_version": prepared["model"]["schema_version"], "status": "pending", "structural": "passed",
                      "semantic": "pending", "input_sha256": prepared["input_sha256"],
                      "checks": prepared["checks"]}
        except (ContractError, OSError, ValueError, TypeError, KeyError) as exc:
            result = {"schema_version": SCHEMA, "status": "failed", "error": str(exc)}
    if args.prepare_review and result.get("structural") == "passed":
        template = {"input_sha256": result["input_sha256"], "reviewer": "",
                    "independent": False, "checks": {key: {"status": "pending", "rationale": ""}
                                                       for key in result["checks"]}}
        if args.prepare_review.exists():
            ap.error("review template already exists; preserve existing review")
        write_json(args.prepare_review, template)
    task = slug(args.book_dir.name)
    path = args.ws / ".work" / task / "thinking-audit.json"
    write_json(path, result)
    print(f"思想来源检查: {result['status']} — {path}")
    if result.get("error"):
        print(result["error"])
    return {"passed": 0, "failed": 1, "pending": 3}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
