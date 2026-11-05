"""Neutral, relocatable portfolio of actual tested book/person Skills.

skill-portfolio/2 entries carry what a downstream selector needs: object, period,
trigger, inputs/outputs, capabilities and limits, dependencies, package version,
build and content hash, tested cases/hosts/loading. Planned items stay pending and
are never counted as usable Skills. skill-portfolio/1 exports still verify.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

from book_skill_common import ContractError, digest, read_json, slug, text, tree_hashes
from production_common import atomic_json, locked, file_hash
from distill_skill import verify
from production_eval import report

SCHEMA = "skill-portfolio/2"
LEGACY_SCHEMA = "skill-portfolio/1"
INPUT_DESCRIPTION = "当前任务事实及任务要求；精确引文另需原文"


def _registry(ws):
    path = Path(ws) / "books/portfolio/skills.json"
    data = read_json(path) if path.exists() else {"schema_version": LEGACY_SCHEMA, "entries": {}}
    data.setdefault("planned", {})
    return path, data


def register(ws, package, evaluation):
    ws, package, evaluation = Path(ws).resolve(), Path(package).resolve(), Path(evaluation).resolve()
    manifest, accepted = verify(package), report(evaluation)
    if accepted["status"] != "passed" or accepted["variant"] != "candidate" or accepted["build_id"] != manifest["build_id"] or accepted["package_sha256"] != digest(tree_hashes(package)):
        raise ContractError("portfolio requires actual tested candidate, not baseline or edited label")
    root = ws / "books/portfolio"
    with locked(root):
        path, data = _registry(ws)
        key = manifest["product"]["id"]
        data["entries"][key] = {"package": str(package), "evaluation": str(evaluation), "build_id": manifest["build_id"]}
        data["planned"].pop(key, None)
        atomic_json(path, data)
    return data["entries"][key]


def plan(ws, key, obj, title, note):
    """A requested book/person Skill without a tested package: listed as pending, never as usable."""
    slug(key)
    if obj not in {"book", "person"}:
        raise ContractError("object must be book/person")
    root = Path(ws).resolve() / "books/portfolio"
    with locked(root):
        path, data = _registry(ws)
        if key in data["entries"]:
            raise ContractError("already registered as a tested Skill")
        data["planned"][key] = {"object": obj, "title": text(title, "title"), "note": text(note, "note"), "time": time.time()}
        atomic_json(path, data)
    return data["planned"][key]


def verified_summary(accepted):
    return {"status": "tested-trial", "hosts": accepted["hosts"], "case_ids": [c["id"] for c in accepted["cases"]],
            "evidence_sha256": accepted["evidence_sha256"], "suite_sha256": accepted["suite_sha256"],
            "relocated": accepted["relocated"], "isolation_limit": accepted["isolation_limit"]}


def verified_summary_v2(accepted):
    return {**verified_summary(accepted), "tier": "L2-trial", "loading": accepted.get("loading", "inline-v1"),
            "dimensions": accepted.get("dimensions", ["application", "fidelity", "utility"]),
            "not_applicable": accepted.get("not_applicable", {}), "targets": accepted["targets"],
            "held_out_cases": [c["id"] for c in accepted["cases"] if c.get("held_out")]}


def describe(dest, manifest, model, accepted):
    product = manifest["product"]
    return {"id": product["id"], "path": f"skills/{product['id']}", "object": product["object"], "title": product["title"],
            "period": product["period"], "edition": product.get("edition"), "purpose": product["purpose"],
            "profiles": product.get("profiles", []), "trigger": model["description"], "uses": model["uses"],
            "inputs": model.get("inputs") or [INPUT_DESCRIPTION], "outputs": model["uses"], "limits": model["limits"],
            "capabilities": [{"id": c["id"], "name": c["name"], "kind": c["kind"], **({"voice": c["voice"]} if "voice" in c else {})}
                             for c in model["capabilities"]],
            "dependencies": manifest["dependencies"], "source_scope": manifest["source_scope"],
            "package": {"schema_version": manifest["schema_version"], "version": manifest["version"], "build_id": manifest["build_id"],
                        "content_sha256": digest(tree_hashes(dest))},
            "verified": verified_summary_v2(accepted)}


def _verify_legacy(out, manifest):
    seen = set()
    for entry in manifest["entries"]:
        sid = slug(entry["id"])
        if sid in seen or entry["path"] != f"skills/{sid}":
            raise ContractError("duplicate or nonportable portfolio entry")
        seen.add(sid)
        actual = verify(out / entry["path"])
        if actual["build_id"] != entry["build_id"] or actual["product"] != entry["product"]:
            raise ContractError("portfolio entry does not match package")
        model = read_json(out / entry["path"] / "references/capabilities.json")["model"]
        for field in ("uses", "limits"):
            if entry[field] != model[field]:
                raise ContractError("portfolio capability metadata changed")
        if entry["inputs"] != INPUT_DESCRIPTION or entry["outputs"] != model["uses"]:
            raise ContractError("portfolio input/output metadata changed")
        for field in ("source_scope", "dependencies"):
            if entry[field] != actual[field]:
                raise ContractError("portfolio source/dependency metadata changed")
        receipt = out / "verification" / f"{sid}.json"
        accepted = read_json(receipt)
        if file_hash(receipt) != entry["verification_sha256"] or entry["verified"] != verified_summary(accepted) or accepted["build_id"] != actual["build_id"] or accepted["status"] != "passed" or accepted["variant"] != "candidate":
            raise ContractError("portfolio verification receipt changed or mismatched")
        if accepted["package_sha256"] != digest(tree_hashes(out / entry["path"])):
            raise ContractError("whole tested package changed, including manifest")
    return seen


def verify_portfolio(out):
    out = Path(out)
    manifest = read_json(out / "PORTFOLIO.json")
    if manifest.get("schema_version") == LEGACY_SCHEMA:
        seen = _verify_legacy(out, manifest)
    elif manifest.get("schema_version") == SCHEMA:
        seen = set()
        for entry in manifest["entries"]:
            sid = slug(entry["id"])
            if sid in seen or entry["path"] != f"skills/{sid}":
                raise ContractError("duplicate or nonportable portfolio entry")
            seen.add(sid)
            actual = verify(out / entry["path"])
            model = read_json(out / entry["path"] / "references/capabilities.json")["model"]
            receipt = out / "verification" / f"{sid}.json"
            accepted = read_json(receipt)
            if file_hash(receipt) != entry["verification_sha256"] or accepted["build_id"] != actual["build_id"] or accepted["status"] != "passed" or accepted["variant"] != "candidate":
                raise ContractError("portfolio verification receipt changed or mismatched")
            if accepted["package_sha256"] != digest(tree_hashes(out / entry["path"])):
                raise ContractError("whole tested package changed, including manifest")
            if {k: v for k, v in entry.items() if k != "verification_sha256"} != describe(out / entry["path"], actual, model, accepted):
                raise ContractError("portfolio entry metadata differs from the tested package")
        for item in manifest.get("pending", []):
            if item.get("status") != "pending-build" or "path" in item or slug(item["id"]) in seen:
                raise ContractError("pending items cannot carry packages or count as usable")
        if manifest.get("counts") != {"usable_skills": len(seen), "pending": len(manifest.get("pending", []))}:
            raise ContractError("portfolio counts differ from entries")
    else:
        raise ContractError("unknown portfolio schema")
    if set(p.name for p in (out / "skills").iterdir()) != seen:
        raise ContractError("stale/unlisted Skill in portfolio")
    return manifest


def export(ws, out, keys=None, replace=False):
    ws, out = Path(ws).resolve(), Path(out).absolute()
    _, data = _registry(ws)
    selected = keys or list(data["entries"])
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(data["entries"]):
        raise ContractError("nonempty unique known portfolio keys required")
    if out.is_symlink() or (out.exists() and not replace):
        raise ContractError("target exists; --replace keeps a snapshot before switching")
    for key in selected:
        for field in ("package", "evaluation"):
            path = Path(data["entries"][key][field]).resolve()
            if out.resolve().is_relative_to(path) or path.is_relative_to(out.resolve()):
                raise ContractError("export must be separate from packages and evaluations")
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".portfolio-", dir=out.parent))
    try:
        records = []
        for key in selected:
            item = data["entries"][key]
            package = Path(item["package"])
            accepted, manifest = report(item["evaluation"]), verify(package)
            if accepted["status"] != "passed" or accepted["variant"] != "candidate" or accepted["build_id"] != manifest["build_id"] or accepted["package_sha256"] != digest(tree_hashes(package)):
                raise ContractError("stale evaluation or changed registered package")
            dest = stage / "skills" / key
            shutil.copytree(package, dest)
            model = read_json(dest / "references/capabilities.json")["model"]
            receipt = stage / "verification" / f"{key}.json"
            # No local paths, private questions, answers or evaluator identities in the handoff.
            accepted = {k: v for k, v in accepted.items() if k not in {"generation_sessions"}}
            atomic_json(receipt, accepted)
            records.append({**describe(dest, manifest, model, accepted), "verification_sha256": file_hash(receipt)})
        pending = [{"id": k, "object": v["object"], "title": v["title"], "status": "pending-build", "note": v["note"]}
                   for k, v in sorted(data["planned"].items()) if k not in selected]
        atomic_json(stage / "PORTFOLIO.json", {"schema_version": SCHEMA, "entries": records, "pending": pending,
                                               "counts": {"usable_skills": len(records), "pending": len(pending)},
                                               "note": "已测范围是事实记录；pending 条目没有可用包，不计入可用 Skill。"})
        verify_portfolio(stage)
        backup = None
        if out.exists():
            backup = out.parent / f".{out.name}-previous-{digest(tree_hashes(out))[:16]}"
            if backup.exists():
                backup = backup.with_name(backup.name + "-" + uuid.uuid4().hex[:8])
            os.replace(out, backup)
        try:
            os.replace(stage, out)
        except BaseException:
            if backup:
                os.replace(backup, out)
            raise
        return verify_portfolio(out)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("register")
    for key in ("ws", "package", "evaluation"):
        p.add_argument("--"+key, type=Path, required=True)
    p = sub.add_parser("plan")
    p.add_argument("--ws", type=Path, required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--object", choices=("book", "person"), required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--note", required=True)
    p = sub.add_parser("export")
    p.add_argument("--ws", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--key", action="append")
    p.add_argument("--replace", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("out", type=Path)
    args = parser.parse_args()
    try:
        if args.cmd == "register":
            result = register(args.ws, args.package, args.evaluation)
        elif args.cmd == "plan":
            result = plan(args.ws, args.id, args.object, args.title, args.note)
        elif args.cmd == "export":
            result = export(args.ws, args.out, args.key, args.replace)
        else:
            result = verify_portfolio(args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ContractError, OSError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
