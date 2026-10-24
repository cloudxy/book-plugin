"""Build a private candidate, verify it, then publish only a behavior-tested payload."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from book_skill_common import (ContractError, SCHEMA, VERSION, bridge_state, contained,
    digest, engine_hash, input_snapshot, json_bytes, procedure_hash, source_hashes, read_json, read_yaml, section,
    slug, tree_hashes, verify_package, write_json)
from thinking_audit import audit, validate

PLUGIN = Path(__file__).resolve().parents[1]

RUNTIME = """## 运用方式

默认直接回答用户当前的问题。用已蒸馏的思想理解事实，自主形成解释、判断或建议；新问题没有原书现成答案，也可以作有根据的推演。
思想决定注意哪些事实、怎样解释关系和取舍，叙事口吻决定怎样展开回答。分析围绕用户的处境，呈现结论、关键理由及有用的下一步。
核心不够时，按需展开相关模型、限定、反例和完整范例。
依据关系迁移范例，不按相似词语复用旧结论；没有预制卡不构成停止理由。
存在实质竞争解释时比较其前提；信息不足时给有根据的分支，或询问最有区分力的问题。
新事实改变前提时修正受影响的判断。书中价值与用户目标冲突时说明取舍，不擅自替换目标。
当下的推演由当前事实、书中关系及明确的迁移假设支持，不要求每句判断在原书里有对应原句。自己的新判断不冒称原作者说过；用户提供的真实处境不标成虚构或合成。
unresolved 条目仅作为缺口或待查解释，不作为已经核验的断言依据。
按适合任务的书籍章法自然成文，保留事实和限定；不虚构用户经历，不强制统一回答模板。
用户要原话、出处、书内情节或某个具体主张的归属，或分析遇到会改变结论的来源疑点时，查短证据与上下文；需要时再查全文。日常分析不逐句检索、不用引文拼接代替回答，也不固定用篇名和年代开头。查证时如实说明可查范围。
当前世界的事实按任务需要另行核实，旧书不替今天的事实作证。程序只处理其实际适用的计算或执行。
多轮或会话压缩后重新确认核心、适用语体与新事实。呈现结论及关键理由，无须披露完整内部思维。

## 按需展开

- [思想关系、适用条件及反证](references/thinking/model.yaml)
- [原书重建、书外应用与条件变化范例](references/thinking/EXAMPLES.md)
- [叙事与口吻的来源及适用语体](references/expression/PROFILE.md)
- [短证据、说话者与上下文](references/evidence/anchors.yaml)
- [阅读范围与缺口](references/overview.md)
"""

PERSONA_RUNTIME = """## 运用方式

由上面的作者定向、联合核心和表达机制共同组织当前回答。让它们实际决定注意什么、怎样重新理解题目、怎样取舍与成文；按问题选择并组合路径，篇幅和任务改变时仍保留关键习惯。展开的次序和收束方式由本书与当前问题决定。
直接形成当下的解释、判断、建议或作品。新问题没有原书原句，也可以用已重建的关系与当前事实作新的、有条件的判断。需要时展开相关路径、反证和完整范例，把范例迁移到关系相似而表面不同的处境。
作品中的价值、性情和张力影响取舍；与用户目标发生实质冲突时把取舍说明白。新的事实应修正依赖它的判断；稳定的认识倾向不随意重置。保留有理由的锋芒、犹疑或留白，适应解释、闲谈、行动与写作的不同需要。
当前事实由当前材料承担，作者、叙述者、人物和编者各有归属。自己的新判断不冒称原作者的新表态；真实对话不虚构用户经历，创作任务才构造虚构场景。unresolved条目保留为缺口。
用户要原话、出处或情节归属，或来源疑点会改变判断时，按需查短证据与上下文，再视需要查全文。日常回答运用已审机制，不逐句找相似名句。当前世界的变化另行核实，程序按其真实适用范围调用。
多轮及压缩后保持作者定向、当前任务和已知事实，结合新增事实继续。呈现回答与关键理由，无须披露完整内部思维。

## 按需展开

- [作者画像、习惯、路径与局限](references/AUTHOR_PROFILE.md)
- [思想、习惯与可变路径](references/thinking/model.yaml)
- [完整联合应用与条件变化](references/thinking/EXAMPLES.md)
- [表达机制及适用语体](references/expression/PROFILE.md)
- [短证据与声音层次](references/evidence/anchors.yaml)
- [完整推演片段的阅读记录](references/reading/episodes.yaml)
- [阅读与重建范围](references/overview.md)
"""


def check_procedures(book, source, ws, task):
    """A stale PASS line in Markdown cannot authorize a new Bundle."""
    # The explicitly requested legacy program route has no author model.
    # Its gates bind the Bundle and actual source, not thinking-only inputs.
    current = {"procedures": procedure_hash(book)}
    if current["procedures"] is None:
        return {"status": "not_applicable"}
    current["source"] = source_hashes(source)
    tdir = Path(ws) / ".work" / slug(task)
    receipt = read_json(tdir / "audit-result.json")
    manifest = read_json(tdir / "bridge-manifest.json")
    if (receipt.get("status") != "passed" or receipt.get("source") != current["source"]
            or receipt.get("procedures") != current["procedures"]
            or Path(manifest["book_dir"]).resolve() != Path(book).resolve()
            or receipt.get("audit_state") != bridge_state(tdir, True)):
        raise ContractError("procedure gates absent/stale: re-bridge and run all applicable gates")
    return receipt


def build_candidate(book, source, ws, review=None, task=None):
    book, source, ws = Path(book).resolve(), Path(source).resolve(), Path(ws).resolve()
    reviewed = audit(book, source, review)
    if reviewed["status"] != "passed":
        raise ContractError(f"source semantic review {reviewed['status']}: {reviewed.get('error', 'not completed')}")
    data = validate(book, source)
    model = data["model"]
    bid = slug(model["book"]["id"])
    receipt = check_procedures(book, source, ws, task or book.name)
    signature = digest({"inputs": data["snapshot"], "engine": engine_hash(),
                        "review": reviewed["review_sha256"]})
    build_root = ws / ".work" / bid / "builds" / signature[:20]
    build_root.mkdir(parents=True, exist_ok=True)
    previous = build_root / "package" / bid
    if previous.exists():
        manifest = verify_package(previous)
        if (manifest.get("input_sha256") != data["input_sha256"]
                or manifest.get("source_review_sha256") != reviewed["review_sha256"]
                or manifest.get("engine_sha256") != engine_hash()
                or (receipt["status"] != "not_applicable"
                    and manifest["procedures"].get("gate_receipt_sha256") != digest(receipt))):
            raise ContractError("existing candidate provenance is stale")
        (book / "thinking/CORE.md").write_bytes((previous / "references/thinking/CORE.md").read_bytes())
        if model["schema_version"] == SCHEMA:
            (book / "AUTHOR_PROFILE.md").write_bytes((previous / "references/AUTHOR_PROFILE.md").read_bytes())
        return previous
    files = {}
    def add(rel, content):
        files[rel] = content.encode() if isinstance(content, str) else content
    for src, dst in (("thinking/model.yaml", "references/thinking/model.yaml"),
                     ("thinking/EXAMPLES.md", "references/thinking/EXAMPLES.md"),
                     ("expression/PROFILE.md", "references/expression/PROFILE.md"),
                     ("evidence/anchors.yaml", "references/evidence/anchors.yaml"),
                     ("BOOK_OVERVIEW.md", "references/overview.md"),
                     ("coverage-audit.md", "references/coverage-audit.md")):
        add(dst, contained(book, src).read_bytes())
    core = model["core"]["text"].strip()
    add("references/thinking/CORE.md", "# 思想核心\n\n" + core + "\n")
    if model["schema_version"] == SCHEMA:
        from author_persona import author_profile
        add("references/reading/episodes.yaml", contained(book, "reading/episodes.yaml").read_bytes())
        add("references/AUTHOR_PROFILE.md", author_profile(model))
        add("references/author-targets.json", json_bytes(data["author_targets"]))
    if (book / "GLOSSARY.md").is_file():
        add("references/glossary.md", (book / "GLOSSARY.md").read_bytes())
    provenance = {"status": "not_applicable"}
    if receipt["status"] != "not_applicable":
        dependency = build_root / "upstream-single"
        if dependency.exists():
            # Never modify an upstream released tree. Each dependency is built once.
            raise ContractError(f"dependency already exists; choose new inputs or inspect {dependency}")
        cmd = [sys.executable, str(PLUGIN / "vendor/cangjie-skill/scripts/cangjie.py"),
               "compile", "--bundle", str(book / ".cangjie/capabilities"),
               "--out", str(dependency), "--output", "single"]
        result = subprocess.run(cmd, text=True, capture_output=True)
        (build_root / "upstream-build.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise ContractError("upstream compile failed; see private upstream-build.log")
        mapping = {}
        # Exclude the old routing entry and upstream release receipt, not merely rename them.
        for rel in tree_hashes(dependency):
            if rel.startswith(("references/", "resources/")):
                if Path(rel).name in {"SKILL.md", "ENTRY.md"}:
                    raise ContractError(f"nested upstream entry: {rel}")
                dest = "references/procedures/" + rel
                add(dest, (dependency / rel).read_bytes())
                mapping[rel] = dest
        bundle = read_yaml(book / ".cangjie/capabilities/verified.yaml")
        rows = ["# 程序调用索引", "", "只负责具体程序调用；未命中本表不代表整书思想不适用。", ""]
        for cap in bundle["capabilities"]:
            if cap.get("status", "active") != "active":
                continue
            name = slug(cap["slug"])
            path = f"references/capabilities/{name}.md"
            if path not in mapping:
                raise ContractError(f"missing compiled procedure: {name}")
            rows += [f"## {cap['capability_id']} {cap['title']}", "",
                     f"用途：{'；'.join(cap['intents'])}。", "",
                     f"[执行输入、输出与边界]({path})", ""]
        add("references/procedures/INDEX.md", "\n".join(rows))
        provenance = {"status": "passed", "bundle_sha256": data["snapshot"]["procedures"],
                      "upstream_files": tree_hashes(dependency), "mapping": mapping,
                      "gate_receipt_sha256": digest(receipt)}
    profile = section((book / "expression/PROFILE.md").read_text(), "运行摘要")
    fm = {"name": bid, "description": model["book"]["description"],
          "metadata": {"book-workflow.version": VERSION, "book-workflow.scope": model["scope"]["coverage"]}}
    entry = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n"
    entry += f"# {model['book']['title']}\n\n"
    entry += f"范围：{model['scope']['includes']}。\n\n未覆盖：{model['scope']['excludes']}。\n\n"
    if model["schema_version"] == SCHEMA:
        entry += "## 作者定向\n\n" + model["author"]["portrait"] + "\n\n"
    runtime = PERSONA_RUNTIME if model["schema_version"] == SCHEMA else RUNTIME
    entry += "## 思想核心\n\n" + core + "\n\n## 叙事与口吻\n\n" + profile + "\n\n" + runtime
    if receipt["status"] != "not_applicable":
        entry += "\n- [程序用途与调用索引](references/procedures/INDEX.md)\n"
    if "references/glossary.md" in files:
        entry += "\n- [共享术语](references/glossary.md)\n"
    add("SKILL.md", entry)
    hashes = {rel: digest(body) for rel, body in sorted(files.items())}
    if input_snapshot(book, source) != data["snapshot"]:
        raise ContractError("source inputs changed during build; discard mixed candidate and retry")
    build_id = digest(hashes)
    manifest = {"schema_version": model["schema_version"], "version": VERSION, "build_id": build_id,
                "product_kind": "author-persona" if model["schema_version"] == SCHEMA else "thinking-v1",
                "book_id": bid, "scope": model["scope"], "input_sha256": data["input_sha256"],
                "inputs": data["snapshot"], "engine_sha256": engine_hash(),
                "source_review_sha256": reviewed["review_sha256"], "procedures": provenance,
                "files": hashes}
    if model["schema_version"] == SCHEMA:
        manifest["author_targets"] = data["author_targets"]
    package = build_root / "package" / bid
    if package.exists():
        old = verify_package(package)
        if old != manifest:
            raise ContractError("existing candidate differs; preserve it for diagnosis")
        return package
    package.mkdir(parents=True)
    for rel, body in files.items():
        dest = contained(package, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    write_json(package / "book-workflow-manifest.json", manifest)
    verify_package(package)
    # CORE is a generated view; edits never create another source of truth.
    (book / "thinking/CORE.md").write_bytes(files["references/thinking/CORE.md"])
    if "references/AUTHOR_PROFILE.md" in files:
        (book / "AUTHOR_PROFILE.md").write_bytes(files["references/AUTHOR_PROFILE.md"])
    write_json(build_root / "source-audit.json", reviewed)
    return package


def publish(candidate, acceptance, out, replace=False):
    from eval_book_skill import report_run
    candidate, out = Path(candidate).resolve(), Path(out).absolute()
    manifest = verify_package(candidate)
    accepted = read_json(acceptance)
    run = Path(acceptance).resolve().parent
    current = report_run(run)
    if (accepted != current or current.get("status") != "passed"
            or current.get("variant") != "candidate"
            or current.get("build_id") != manifest["build_id"]
            or current.get("package_sha256") != digest(tree_hashes(candidate))):
        raise ContractError("acceptance is stale/incomplete; run report on actual reviewed outputs")
    if out.resolve().is_relative_to(candidate) or candidate.is_relative_to(out.resolve()):
        raise ContractError("installation must be separate from candidate tree")
    if out.is_symlink() or (out.exists() and not out.is_dir()):
        raise ContractError("installation target must be a regular directory")
    if out.exists() and not replace:
        raise ContractError("target exists; use --replace to preserve snapshot and switch")
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}-candidate-", dir=out.parent))
    backup = None
    try:
        shutil.copytree(candidate, stage, dirs_exist_ok=True)
        verify_package(stage)
        if out.exists():
            backup = out.parent / f".{out.name}-previous-{digest(tree_hashes(out))[:16]}"
            if backup.exists():
                raise ContractError(f"snapshot already exists: {backup}")
            os.replace(out, backup)
        try:
            os.replace(stage, out)
        except BaseException:
            if backup:
                os.replace(backup, out)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return out


def compile_procedures(book, ws, out, output="auto", source=None, task=None):
    book, ws = Path(book).resolve(), Path(ws).resolve()
    task = task or book.name
    if source is None:
        source = read_json(ws / ".work" / slug(task) / "bridge-manifest.json")["source"]
    if check_procedures(book, source, ws, task)["status"] != "passed":
        raise ContractError("no audited procedure Bundle")
    command = [sys.executable, str(PLUGIN / "vendor/cangjie-skill/scripts/cangjie.py"),
               "compile", "--bundle", str(book / ".cangjie/capabilities"),
               "--out", str(out), "--output", output]
    return subprocess.run(command).returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    candidate = sub.add_parser("candidate")
    for name in ("book-dir", "source", "ws"):
        candidate.add_argument(f"--{name}", required=True, type=Path)
    candidate.add_argument("--review", type=Path)
    candidate.add_argument("--task")
    verify = sub.add_parser("verify")
    verify.add_argument("--candidate", required=True, type=Path)
    release = sub.add_parser("publish")
    for name in ("candidate", "acceptance", "out"):
        release.add_argument(f"--{name}", required=True, type=Path)
    release.add_argument("--replace", action="store_true")
    procedures = sub.add_parser("procedures", help="gated legacy single/pack compilation")
    for name in ("book-dir", "ws", "out"):
        procedures.add_argument(f"--{name}", required=True, type=Path)
    procedures.add_argument("--source", type=Path)
    procedures.add_argument("--task")
    procedures.add_argument("--output", choices=("auto", "single", "pack"), default="auto")
    args = ap.parse_args()
    try:
        if args.command == "candidate":
            result = build_candidate(args.book_dir, args.source, args.ws, args.review, args.task)
        elif args.command == "verify":
            result = verify_package(args.candidate)["build_id"]
        elif args.command == "procedures":
            return compile_procedures(args.book_dir, args.ws, args.out, args.output, args.source, args.task)
        else:
            result = publish(args.candidate, args.acceptance, args.out, args.replace)
        print(result)
        return 0
    except (ContractError, OSError, KeyError, ValueError) as exc:
        print(f"构建拒绝: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
