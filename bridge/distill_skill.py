"""Purpose-specific trial Skills. Never claims book-skill/2 or L3 acceptance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import uuid

import yaml

from book_skill_common import ContractError, contained, digest, read_json, slug, text, tree_hashes
from production_common import VERSION, atomic_json, strings

SCHEMA = "distilled-skill/1"
MODEL_SCHEMA = "distilled-capability/1"
KINDS = ("knowledge", "thought", "narrative", "expression")


def validate_model(model, unit_ids):
    if model.get("schema_version") != MODEL_SCHEMA:
        raise ContractError("wrong capability schema")
    for field in ("description", "core"):
        text(model.get(field), field)
    strings(model.get("uses"), "uses")
    strings(model.get("limits"), "limits")
    capabilities = model.get("capabilities")
    examples = model.get("examples")
    if not isinstance(capabilities, list) or not capabilities or not isinstance(examples, list) or not examples:
        raise ContractError("capabilities and complete examples required")
    ids = set()
    for cap in capabilities:
        cid = slug(cap.get("id"))
        if cid in ids:
            raise ContractError("duplicate capability id")
        ids.add(cid)
        if cap.get("kind") not in KINDS or cap.get("epistemic_status") not in {"explicit", "reconstructed"}:
            raise ContractError(f"{cid}: unsupported kind or unresolved capability")
        for field in ("name", "trigger"):
            text(cap.get(field), f"{cid}.{field}")
        for field in ("actions", "conditions", "changes", "evidence"):
            strings(cap.get(field), f"{cid}.{field}")
        if not set(cap["evidence"]) <= set(unit_ids):
            raise ContractError(f"{cid}: unknown source units")
    covered, example_ids = set(), set()
    for example in examples:
        eid = slug(example.get("id"))
        if eid in example_ids or eid in ids:
            raise ContractError("duplicate example id")
        example_ids.add(eid)
        refs = strings(example.get("capabilities"), f"{eid}.capabilities")
        if not set(refs) <= ids:
            raise ContractError("example references unknown capability")
        covered.update(refs)
        for field in ("task", "answer", "changed_task", "changed_answer"):
            text(example.get(field), f"{eid}.{field}")
        if example.get("origin") not in {"synthetic", "source_reconstruction"}:
            raise ContractError("example origin required")
    if covered != ids:
        raise ContractError("every runtime capability needs an application and changed-condition example")
    procedures = model.get("procedures", {})
    text(procedures.get("reason"), "procedures.reason")
    if procedures.get("status") != "not_applicable":
        raise ContractError("executable procedures must use the existing cangjie/four-gate route")
    return model


def check_links(root, files):
    for rel in files:
        if not rel.endswith(".md"):
            continue
        body = contained(root, rel).read_text(encoding="utf-8")
        # Runtime packages contain no local absolute paths, including in fenced instructions.
        if re.search(r"(?:/Users/|/private/|/home/|[A-Z]:\\\\)", body):
            raise ContractError(f"nonportable runtime path in {rel}")
        for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", body):
            if re.match(r"https?://|mailto:|#", target):
                continue
            from urllib.parse import unquote
            path = (root / rel).parent / unquote(target.split("#", 1)[0])
            if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                raise ContractError(f"broken/external package link: {rel}: {target}")


def verify(root):
    root = Path(root)
    manifest = read_json(root / "book-workflow-manifest.json")
    if manifest.get("schema_version") != SCHEMA:
        raise ContractError("not a production trial Skill")
    files = tree_hashes(root)
    files.pop("book-workflow-manifest.json", None)
    if files != manifest.get("files") or digest(files) != manifest.get("build_id"):
        raise ContractError("Skill payload missing, changed or unlisted")
    if [p for p in files if Path(p).name == "SKILL.md"] != ["SKILL.md"]:
        raise ContractError("exactly one Skill entry required")
    data = read_json(root / "references/capabilities.json")
    validate_model(data["model"], data["units"])
    if manifest.get("product") != data["product"] or manifest.get("source_scope") != data["sources"]:
        raise ContractError("manifest metadata differs from hashed payload")
    if manifest.get("acceptance") != "trial-unverified":
        raise ContractError("acceptance belongs to external bound evidence, not editable package labels")
    check_links(root, files)
    return manifest


def build(root, state):
    """Called only after the scheduler verifies the source-review dependency."""
    root = Path(root)
    synthesis = read_json(root / state["tasks"]["synthesize"]["output"])["result"]
    review = read_json(root / state["tasks"]["review"]["output"])
    synth = read_json(root / state["tasks"]["synthesize"]["output"])
    if review["result"]["verdict"] != "pass" or review["executor"]["session_id"] == synth["executor"]["session_id"]:
        raise ContractError("independent source review required")
    validate_model(synthesis, state["units"])
    product = state["product"]
    sources = [{k: v for k, v in source.items() if k not in {"path", "snapshot"}} for source in state["sources"]]
    data = {"product": product, "sources": sources, "units": list(state["units"]), "model": synthesis}
    stage = Path(tempfile.mkdtemp(prefix=".build-", dir=root))
    try:
        atomic_json(stage / "references/capabilities.json", data)
        content = ["# 能力与条件\n"]
        for cap in synthesis["capabilities"]:
            content += [f"## {cap['name']} ({cap['id']})", f"触发：{cap['trigger']}", "动作：\n" + "\n".join(f"- {v}" for v in cap["actions"]),
                        "条件：" + "；".join(cap["conditions"]), "何时调整：" + "；".join(cap["changes"]),
                        "来源单元：" + ", ".join(cap["evidence"]) + f"；解释状态：{cap['epistemic_status']}\n"]
        (stage / "references/abilities.md").write_text("\n\n".join(content), encoding="utf-8")
        examples = ["# 完整应用范例\n"]
        for ex in synthesis["examples"]:
            examples += [f"## {ex['id']} ({ex['origin']})", "涉及能力：" + ", ".join(ex["capabilities"]),
                         f"任务：{ex['task']}\n\n{ex['answer']}", f"条件改变：{ex['changed_task']}\n\n{ex['changed_answer']}"]
        (stage / "references/examples.md").write_text("\n\n".join(examples), encoding="utf-8")
        front = yaml.safe_dump({"name": product["id"], "description": synthesis["description"]}, allow_unicode=True, sort_keys=False).strip()
        entry = (f"---\n{front}\n---\n\n# {product['title']}\n\n"
                 f"适用：{'；'.join(synthesis['uses'])}\n\n## 能力核心\n\n{synthesis['core']}\n\n"
                 "## 运用\n\n依据当前任务选择[能力与条件](references/abilities.md)，需要时读取[完整范例及变化情境](references/examples.md)。"
                 "把方法应用于用户提供的新事实，直接完成用户要求的解释、判断或作品。"
                 "未知事实标为假设；条件变化时调整相关判断。精确原文查询需用户另提供原文，不编造引文。\n\n"
                 "## 适用范围\n\n" + "\n".join(f"- {v}" for v in synthesis["limits"]) + "\n\n"
                 f"对象：{product['object']}；材料时期/版本：{product['period']}。"
                 "包内材料用于迁移已提取的方法与知识，不代表作者未公开思想或对现实事实的自动认证。\n")
        (stage / "SKILL.md").write_text(entry, encoding="utf-8")
        files = tree_hashes(stage)
        build_id = digest(files)
        manifest = {"schema_version": SCHEMA, "version": VERSION, "build_id": build_id, "files": files,
                    "product": product, "source_scope": sources, "dependencies": [], "acceptance": "trial-unverified"}
        atomic_json(stage / "book-workflow-manifest.json", manifest)
        verify(stage)
        target = root / "packages" / build_id / product["id"]
        if target.exists():
            try:
                verify(target)
            except (ContractError, OSError):
                quarantine = root / "quarantine" / f"{build_id}-{uuid.uuid4().hex}"
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                target.rename(quarantine)
                stage.rename(target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            stage.rename(target)
        return {"package": str(target.relative_to(root)), "build_id": build_id, "acceptance": "pending-runtime"}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.package), ensure_ascii=False, indent=2))
    except (ContractError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
