"""Neutral, relocatable portfolio of actual tested book/person Skills."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from book_skill_common import ContractError, digest, read_json, slug, tree_hashes
from production_common import atomic_json, locked, file_hash
from distill_skill import verify
from production_eval import report

INPUT_DESCRIPTION = "当前任务事实及任务要求；精确引文另需原文"

def register(ws, package, evaluation):
    ws, package, evaluation = Path(ws).resolve(), Path(package).resolve(), Path(evaluation).resolve()
    manifest, accepted = verify(package), report(evaluation)
    if accepted["status"] != "passed" or accepted["variant"] != "candidate" or accepted["build_id"] != manifest["build_id"] or accepted["package_sha256"] != digest(tree_hashes(package)):
        raise ContractError("portfolio requires actual tested candidate, not baseline or edited label")
    root = ws / "books/portfolio"
    with locked(root):
        path = root / "skills.json"
        data = read_json(path) if path.exists() else {"schema_version": "skill-portfolio/1", "entries": {}}
        key = manifest["product"]["id"]
        data["entries"][key] = {"package": str(package), "evaluation": str(evaluation), "build_id": manifest["build_id"]}
        atomic_json(path, data)
    return data["entries"][key]


def verified_summary(accepted):
    return {"status": "tested-trial", "hosts": accepted["hosts"], "case_ids": [c["id"] for c in accepted["cases"]],
            "evidence_sha256": accepted["evidence_sha256"], "suite_sha256": accepted["suite_sha256"],
            "relocated": accepted["relocated"], "isolation_limit": accepted["isolation_limit"]}


def verify_portfolio(out):
    out = Path(out)
    manifest = read_json(out / "PORTFOLIO.json")
    if manifest.get("schema_version") != "skill-portfolio/1":
        raise ContractError("unknown portfolio schema")
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
    if set(p.name for p in (out / "skills").iterdir()) != seen:
        raise ContractError("stale/unlisted Skill in portfolio")
    return manifest


def export(ws, out, keys=None, replace=False):
    ws, out = Path(ws).resolve(), Path(out).absolute()
    data = read_json(ws / "books/portfolio/skills.json")
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
            records.append({"id": key, "path": f"skills/{key}", "build_id": manifest["build_id"],
                            "product": manifest["product"], "uses": model["uses"], "limits": model["limits"],
                            "inputs": INPUT_DESCRIPTION, "outputs": model["uses"],
                            "dependencies": manifest["dependencies"], "source_scope": manifest["source_scope"],
                            "verification_sha256": file_hash(receipt), "verified": verified_summary(accepted)})
        atomic_json(stage / "PORTFOLIO.json", {"schema_version": "skill-portfolio/1", "entries": records})
        verify_portfolio(stage)
        backup = None
        if out.exists():
            backup = out.parent / f".{out.name}-previous-{digest(tree_hashes(out))[:16]}"
            if backup.exists():
                import uuid
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
    p = sub.add_parser("export")
    p.add_argument("--ws", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--key", action="append")
    p.add_argument("--replace", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("out", type=Path)
    args = parser.parse_args()
    try:
        result = register(args.ws, args.package, args.evaluation) if args.cmd == "register" else export(args.ws, args.out, args.key, args.replace) if args.cmd == "export" else verify_portfolio(args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ContractError, OSError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
