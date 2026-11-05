"""Purpose-specific trial Skills. Never claims book-skill/2 or L3 acceptance.

distilled-capability/1 packages keep their original contract and bytes. Version 2
adds voice/reality boundaries and purpose assets: thought needs episodes and
habits/paths, expression needs PROFILE; knowledge needs neither author asset.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote
import uuid

import yaml

from book_skill_common import ContractError, contained, digest, read_json, slug, text, tree_hashes
from production_common import VERSION, atomic_json, strings

SCHEMA = "distilled-skill/1"
SCHEMA_V2 = "distilled-skill/2"
MODEL_SCHEMA = "distilled-capability/1"
MODEL_SCHEMA_V2 = "distilled-capability/2"
KINDS = ("knowledge", "thought", "narrative", "expression")
VOICES = ("author", "quoted", "editor", "narrator", "character", "persona",
          "self-account", "others-account", "later-interpretation")
REALITY = ("source-claim-unverified", "in-story-only", "method-or-viewpoint")
REALITY_TEXT = {"source-claim-unverified": "书内主张，现实未核", "in-story-only": "故事内机制，不外推现实",
                "method-or-viewpoint": "方法或视角，不是事实主张"}
PURPOSE_ASSETS = {"thought": ("episodes", "habits"), "expression": ("profile",)}
# Runtime packages must not depend on the producing machine.
NONPORTABLE = re.compile(r"/Users/|/home/|/private/|/tmp/|/var/folders/|/Volumes/|/opt/|/mnt/|file://|(?<![A-Za-z])[A-Za-z]:[\\/]")


def _capabilities(model, unit_ids, v2):
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
        if v2:
            if cap.get("voice") not in VOICES:
                raise ContractError(f"{cid}: voice attribution required")
            if cap.get("reality") not in REALITY:
                raise ContractError(f"{cid}: reality boundary required")
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
    return ids, example_ids


def _purpose_assets(model, unit_ids, profiles, ids, taken):
    episodes, habits, profile = model.get("episodes"), model.get("habits"), model.get("profile")
    if not isinstance(episodes, list) or not isinstance(habits, list):
        raise ContractError("episodes and habits lists required (empty when not applicable)")
    if "thought" in profiles and (not episodes or not habits):
        raise ContractError("thought purpose requires episodes and habits/paths")
    used = set()
    for item in episodes:
        eid = slug(item.get("id"))
        if eid in taken:
            raise ContractError("duplicate episode id")
        taken.add(eid)
        refs = strings(item.get("capabilities"), f"{eid}.capabilities")
        if not set(refs) <= ids:
            raise ContractError(f"{eid}: unknown capability")
        used.update(refs)
        for field in ("problem", "tradeoff", "revision"):
            text(item.get(field), f"{eid}.{field}")
        strings(item.get("path"), f"{eid}.path")
        if not set(strings(item.get("evidence"), f"{eid}.evidence")) <= set(unit_ids):
            raise ContractError(f"{eid}: unknown source units")
    thought = {c["id"] for c in model["capabilities"] if c["kind"] == "thought"}
    if "thought" in profiles and not thought <= used:
        raise ContractError("each thought capability needs an episode")
    for item in habits:
        hid = slug(item.get("id"))
        if hid in taken:
            raise ContractError("duplicate habit id")
        taken.add(hid)
        for field in ("name", "when", "counter_signal"):
            text(item.get(field), f"{hid}.{field}")
        strings(item.get("steps"), f"{hid}.steps")
        if not set(strings(item.get("evidence"), f"{hid}.evidence")) <= set(unit_ids):
            raise ContractError(f"{hid}: unknown source units")
    if "expression" in profiles:
        if not isinstance(profile, dict):
            raise ContractError("expression purpose requires PROFILE")
        if profile.get("voice_layer") not in VOICES:
            raise ContractError("PROFILE voice layer required")
        for field in ("structure", "rhythm", "devices", "diction", "avoid", "evidence"):
            strings(profile.get(field), f"profile.{field}")
        if not set(profile["evidence"]) <= set(unit_ids):
            raise ContractError("PROFILE cites unknown source units")
    elif profile is not None:
        raise ContractError("PROFILE belongs only to expression purpose")


def validate_model(model, unit_ids, profiles=None):
    version = model.get("schema_version")
    if version not in {MODEL_SCHEMA, MODEL_SCHEMA_V2}:
        raise ContractError("wrong capability schema")
    v2 = version == MODEL_SCHEMA_V2
    for field in ("description", "core"):
        text(model.get(field), field)
    strings(model.get("uses"), "uses")
    strings(model.get("limits"), "limits")
    ids, taken = _capabilities(model, unit_ids, v2)
    if v2:
        if profiles is None or not set(profiles) <= set(KINDS) or not profiles:
            raise ContractError("purpose profiles required to validate assets")
        strings(model.get("inputs"), "inputs")
        _purpose_assets(model, unit_ids, profiles, ids, taken)
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
        if NONPORTABLE.search(body):
            raise ContractError(f"nonportable runtime path in {rel}")
        for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", body):
            if re.match(r"https?://|mailto:|#", target):
                continue
            path = (root / rel).parent / unquote(target.split("#", 1)[0])
            if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                raise ContractError(f"broken/external package link: {rel}: {target}")


def verify(root):
    root = Path(root)
    manifest = read_json(root / "book-workflow-manifest.json")
    if manifest.get("schema_version") not in {SCHEMA, SCHEMA_V2}:
        raise ContractError("not a production trial Skill")
    files = tree_hashes(root)
    files.pop("book-workflow-manifest.json", None)
    if files != manifest.get("files") or digest(files) != manifest.get("build_id"):
        raise ContractError("Skill payload missing, changed or unlisted")
    if [p for p in files if Path(p).name == "SKILL.md"] != ["SKILL.md"]:
        raise ContractError("exactly one Skill entry required")
    data = read_json(root / "references/capabilities.json")
    expected = MODEL_SCHEMA_V2 if manifest["schema_version"] == SCHEMA_V2 else MODEL_SCHEMA
    if data["model"].get("schema_version") != expected:
        raise ContractError("manifest cannot relabel the capability schema")
    validate_model(data["model"], data["units"], data["product"].get("profiles"))
    if manifest.get("product") != data["product"] or manifest.get("source_scope") != data["sources"]:
        raise ContractError("manifest metadata differs from hashed payload")
    if manifest.get("acceptance") != "trial-unverified":
        raise ContractError("acceptance belongs to external bound evidence, not editable package labels")
    if manifest["schema_version"] == SCHEMA_V2:
        assets = sorted(p for p in files if p.startswith("references/") and p != "references/capabilities.json")
        if manifest.get("assets") != assets or manifest.get("profiles") != data["product"]["profiles"]:
            raise ContractError("manifest asset inventory differs from payload")
        for need in (a for kind in data["product"]["profiles"] for a in PURPOSE_ASSETS.get(kind, ())):
            if ASSET_FILES[need] not in files:
                raise ContractError(f"purpose asset missing: {need}")
    check_links(root, files)
    return manifest


def _render_v1(stage, synthesis, product):
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


ASSET_FILES = {"abilities": "references/abilities.md", "examples": "references/examples.md",
               "episodes": "references/episodes.md", "habits": "references/habits.md", "profile": "references/PROFILE.md"}


def _render_v2(stage, synthesis, product):
    content = ["# 能力与条件\n"]
    for cap in synthesis["capabilities"]:
        content += [f"## {cap['name']} ({cap['id']})", f"触发：{cap['trigger']}", "动作：\n" + "\n".join(f"- {v}" for v in cap["actions"]),
                    "条件：" + "；".join(cap["conditions"]), "何时调整：" + "；".join(cap["changes"]),
                    f"声音：{cap['voice']}；材料边界：{REALITY_TEXT[cap['reality']]}；解释状态：{cap['epistemic_status']}",
                    "来源单元：" + ", ".join(cap["evidence"]) + "\n"]
    (stage / ASSET_FILES["abilities"]).write_text("\n\n".join(content), encoding="utf-8")
    examples = ["# 完整应用范例\n"]
    for ex in synthesis["examples"]:
        examples += [f"## {ex['id']} ({ex['origin']})", "涉及能力：" + ", ".join(ex["capabilities"]),
                     f"任务：{ex['task']}\n\n{ex['answer']}", f"条件改变：{ex['changed_task']}\n\n{ex['changed_answer']}"]
    (stage / ASSET_FILES["examples"]).write_text("\n\n".join(examples), encoding="utf-8")
    links = ["依据当前任务选择[能力与条件](references/abilities.md)，需要时读取[完整范例及变化情境](references/examples.md)。"]
    if synthesis["episodes"]:
        body = ["# 判断过程（episodes）\n"]
        for ep in synthesis["episodes"]:
            body += [f"## {ep['id']}", "涉及能力：" + ", ".join(ep["capabilities"]), f"问题：{ep['problem']}",
                     "判断路径：\n" + "\n".join(f"{i}. {v}" for i, v in enumerate(ep["path"], 1)),
                     f"取舍：{ep['tradeoff']}", f"修正：{ep['revision']}", "来源单元：" + ", ".join(ep["evidence"]) + "\n"]
        (stage / ASSET_FILES["episodes"]).write_text("\n\n".join(body), encoding="utf-8")
        links.append("需要迁移判断方式时读取[判断过程](references/episodes.md)，按其路径处理新问题，不照搬原情境结论。")
    if synthesis["habits"]:
        body = ["# 思考习惯与路径\n"]
        for habit in synthesis["habits"]:
            body += [f"## {habit['name']} ({habit['id']})", f"何时使用：{habit['when']}",
                     "步骤：\n" + "\n".join(f"{i}. {v}" for i, v in enumerate(habit["steps"], 1)),
                     f"出现以下信号时停用或修正：{habit['counter_signal']}", "来源单元：" + ", ".join(habit["evidence"]) + "\n"]
        (stage / ASSET_FILES["habits"]).write_text("\n\n".join(body), encoding="utf-8")
        links.append("[思考习惯与路径](references/habits.md)说明何时启用、如何推进及何时停用。")
    if synthesis.get("profile"):
        prof = synthesis["profile"]
        body = ["# 表达 PROFILE\n", f"声音层：{prof['voice_layer']}"]
        for field, label in (("structure", "结构"), ("rhythm", "节奏"), ("devices", "手法"), ("diction", "措辞"), ("avoid", "避免")):
            body.append(f"## {label}\n\n" + "\n".join(f"- {v}" for v in prof[field]))
        body.append("来源单元：" + ", ".join(prof["evidence"]) + "\n")
        (stage / ASSET_FILES["profile"]).write_text("\n\n".join(body), encoding="utf-8")
        links.append("成文任务按[表达 PROFILE](references/PROFILE.md)组织结构与节奏；表达习惯不冒称原话。")
    front = yaml.safe_dump({"name": product["id"], "description": synthesis["description"]}, allow_unicode=True, sort_keys=False).strip()
    entry = (f"---\n{front}\n---\n\n# {product['title']}\n\n"
             f"适用：{'；'.join(synthesis['uses'])}\n\n## 能力核心\n\n{synthesis['core']}\n\n"
             "## 运用\n\n" + "".join(links) +
             "把方法应用于用户提供的新事实，直接完成用户要求的解释、判断或作品。"
             "未知事实标为假设；条件变化时调整相关判断。精确原文查询需用户另提供原文，不编造引文。\n\n"
             "## 需要的输入\n\n" + "\n".join(f"- {v}" for v in synthesis["inputs"]) + "\n\n"
             "## 材料边界\n\n每项能力标明声音与材料边界：书内主张现实未核，不能当作已核实的现实事实；"
             "故事内机制只在故事内成立，不外推现实；用于虚构创作时，改写或新推演须标为新创，不冒称原作或本人原话。"
             "被引者、人物或他人评价不等于作者或本人立场。\n\n"
             "## 适用范围\n\n" + "\n".join(f"- {v}" for v in synthesis["limits"]) + "\n\n"
             f"对象：{product['object']}；材料时期/版本：{product['period']}；用途：{'、'.join(product['profiles'])}。"
             "包内材料用于迁移已提取的方法与知识，不代表作者未公开思想或对现实事实的自动认证。\n")
    (stage / "SKILL.md").write_text(entry, encoding="utf-8")


def build(root, state):
    """Called only after the scheduler verifies the source-review dependency."""
    root = Path(root)
    synthesis = read_json(root / state["tasks"]["synthesize"]["output"])["result"]
    review = read_json(root / state["tasks"]["review"]["output"])
    synth = read_json(root / state["tasks"]["synthesize"]["output"])
    if review["result"]["verdict"] != "pass" or review["executor"]["session_id"] == synth["executor"]["session_id"]:
        raise ContractError("independent source review required")
    product = state["product"]
    validate_model(synthesis, state["units"], product.get("profiles"))
    v2 = synthesis["schema_version"] == MODEL_SCHEMA_V2
    sources = [{k: v for k, v in source.items() if k not in {"path", "snapshot"}} for source in state["sources"]]
    data = {"product": product, "sources": sources, "units": list(state["units"]), "model": synthesis}
    stage = Path(tempfile.mkdtemp(prefix=".build-", dir=root))
    try:
        atomic_json(stage / "references/capabilities.json", data)
        (_render_v2 if v2 else _render_v1)(stage, synthesis, product)
        files = tree_hashes(stage)
        build_id = digest(files)
        manifest = {"schema_version": SCHEMA_V2 if v2 else SCHEMA, "version": VERSION if v2 else "0.5.0", "build_id": build_id,
                    "files": files, "product": product, "source_scope": sources, "dependencies": [], "acceptance": "trial-unverified"}
        if v2:
            manifest.update(profiles=product["profiles"], inputs=synthesis["inputs"],
                            assets=sorted(p for p in files if p.startswith("references/") and p != "references/capabilities.json"))
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
