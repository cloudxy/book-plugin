"""旧素材原型（portfolio/1），非升级后的 Skill 交付出口。

新中立组合清单与完整被测包使用 skill_portfolio.py；此模块仅兼容旧实验。

出口对齐写作侧既有合同：素材卡（可信级=拆书、定位级引用、不复制原文）、
知识点候选（claim 条目）、L2 文风锚（PROFILE 运行摘要）。人员 skill
（如 nuwa 产）只登记、禁入事实链，不导出任何素材。只有过闸（l1-check
passed）且过闸后未被改动的 L1 产物才可导出；原文不可读时拒导出——
防复制原文是出口闸，无原文不能验就不能出口。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from book_skill_common import (ContractError, digest, load_source, qnorm, read_json, read_yaml, section,
    slug, text, write_json)

PORTFOLIO_SCHEMA = "portfolio/1"
TIERS = ("L1", "L2", "L3")
VERBATIM_LIMIT = 15  # 写作侧拆书级引用上限；更长连续重合视为复制原文


def manifest_path(ws):
    return Path(ws) / "books" / "portfolio" / "MANIFEST.yaml"


def register(ws, source_type, key_id, period, title, tier=None, slug_name=None, kind=None, notes=""):
    if source_type not in {"book", "person"}:
        raise ContractError("source_type must be book or person")
    for value, label in ((key_id, "key id"), (period, "period"), (title, "title")):
        text(value, label)
    key = f"{source_type}:{key_id}@{period}"
    entry = {"key": key, "source_type": source_type, "title": title, "period": period, "notes": notes}
    if source_type == "book":
        entry.update(slug=slug(text(slug_name, "slug")), tier=text(tier, "tier"),
                     kind=text(kind, "kind"), fact_chain="allowed")
        if entry["tier"] not in TIERS:
            raise ContractError("book tier must be L1/L2/L3")
    else:
        entry.update(tier="external", fact_chain="forbidden",
                     notes=notes or "人的思维模板：无原文锚定，禁入事实链")
    path = manifest_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": PORTFOLIO_SCHEMA, "entries": []}
    if path.is_file():
        data = read_yaml(path)
        if data.get("schema_version") != PORTFOLIO_SCHEMA:
            raise ContractError("unsupported portfolio schema")
    if any(item.get("key") == key for item in data["entries"]):
        raise ContractError(f"portfolio key already registered: {key}")
    data["entries"].append(entry)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return entry


def verbatim_hit(statement, span_text):
    normalized = qnorm(statement)
    window = VERBATIM_LIMIT + 1
    span_text = qnorm(span_text)
    return any(normalized[i:i + window] in span_text for i in range(len(normalized) - window + 1))


def export(ws, out, keys=None):
    path = manifest_path(ws)
    data = read_yaml(path) if path.is_file() else None
    if not data or data.get("schema_version") != PORTFOLIO_SCHEMA:
        raise ContractError("portfolio manifest missing or unsupported: register first")
    selected = data["entries"]
    if keys:
        selected = [entry for entry in selected if entry["key"] in keys]
        if len(selected) != len(keys):
            raise ContractError("unknown portfolio key")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    inventory, claim_lines, violations, cards = [], [], [], 0
    for entry in selected:
        if entry["source_type"] != "book":
            inventory.append({"key": entry["key"], "tier": entry["tier"],
                              "fact_chain": entry["fact_chain"], "exported": "inventory-only"})
            continue
        book = Path(ws) / "books" / entry["slug"]
        gate = read_json(Path(ws) / ".work" / entry["slug"] / "l1-check.json")
        if gate.get("status") != "passed":
            raise ContractError(f"{entry['key']}: L1 gates not passed; refuse export")
        material_file = book / "l1/material.yaml"
        if digest(material_file.read_bytes()) != gate.get("material_sha256"):
            raise ContractError(f"{entry['key']}: L1 material changed after gates; re-run check")
        material = read_yaml(material_file)
        if material["source"]["text_sha256"] != gate.get("source_text_sha256"):
            raise ContractError(f"{entry['key']}: gate result does not bind this material; re-run check")
        src = qnorm(load_source(Path(material["source"]["path"])))
        if digest(src.encode()) != material["source"]["text_sha256"]:
            raise ContractError(f"{entry['key']}: registered source file no longer matches its hash")
        record = {"key": entry["key"], "tier": entry["tier"], "kind": entry["kind"],
                  "fact_chain": entry["fact_chain"], "cards": 0, "claims": 0}
        seq = 0
        for item in material["entries"]:
            if verbatim_hit(item["statement"], src[item["start"]:item["end"]][:4000]):
                violations.append({"key": entry["key"], "id": item["id"]})
                continue
            seq += 1
            card_id = f"{entry['slug']}-M{seq:04d}"
            short = re.sub(r"[\s/\\:*?\"<>|，。；：、]+", "", item["statement"])[:8] or item["id"]
            domain = str(item.get("domain") or "未分")
            body = (f"# {card_id} {short}\n\n"
                    f"- 来源：拆:{entry['title']}\n"
                    f"- 内容：{item['statement']}（定位：{item['locator']}）\n"
                    f"- 可用处：{item.get('use') or entry['kind'] + ' 素材：' + item['kind']}\n"
                    f"- 可信级：拆书\n"
                    f"- 域：{domain}\n")
            card = out / "素材" / domain / f"{card_id}-{short}.md"
            card.parent.mkdir(parents=True, exist_ok=True)
            card.write_text(body, encoding="utf-8")
            cards += 1
            record["cards"] += 1
            if item["kind"] == "claim":
                claim_lines.append(json.dumps(
                    {"id": item["id"], "statement": item["statement"], "locator": item["locator"],
                     "source": f"拆:{entry['title']}", "epistemic_status": item["epistemic_status"]},
                    ensure_ascii=False))
                record["claims"] += 1
        if entry["tier"] in ("L2", "L3"):
            profile = book / "expression/PROFILE.md"
            if not profile.is_file():
                raise ContractError(f"{entry['key']}: L2/L3 entry requires expression/PROFILE.md for the style anchor")
            summary = section(profile.read_text(encoding="utf-8"), "运行摘要")
            anchor = out / "文风锚" / f"{entry['slug']}.md"
            anchor.parent.mkdir(parents=True, exist_ok=True)
            anchor.write_text(f"# {entry['title']} 文风锚\n\n来源：{entry['key']}（运行摘要，供写作侧文风定向）\n\n{summary}\n",
                              encoding="utf-8")
            record["style_anchor"] = True
        inventory.append(record)
    if claim_lines:
        target = out / "知识点" / "claims.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(claim_lines) + "\n", encoding="utf-8")
    report = {"schema_version": PORTFOLIO_SCHEMA, "entries": inventory,
              "cards": cards, "claims": len(claim_lines), "verbatim_skipped": violations}
    write_json(out / "PORTFOLIO_EXPORT.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("register", help="登记组合清单；重复 key 拒绝")
    p.add_argument("--ws", required=True, type=Path)
    p.add_argument("--source-type", required=True, choices=("book", "person"))
    p.add_argument("--key-id", required=True, help="书 slug 或人物标识")
    p.add_argument("--period", required=True, help="时期；同作者多书以时期区分")
    p.add_argument("--title", required=True)
    p.add_argument("--tier", help="book 必填 L1/L2/L3")
    p.add_argument("--kind", help="book 必填类型（四类配重之一）")
    p.add_argument("--notes", default="")
    p = sub.add_parser("export", help="导出写作侧材料包；person 只进清单不导素材")
    p.add_argument("--ws", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--key", action="append", help="只导指定 key，可多次")
    args = ap.parse_args()
    if args.cmd == "register":
        entry = register(args.ws, args.source_type, args.key_id, args.period, args.title,
                         args.tier, args.key_id, args.kind, args.notes)
        print(f"已登记：{entry['key']}（tier={entry['tier']}，fact_chain={entry['fact_chain']}）")
        return 0
    report = export(args.ws, args.out, args.key)
    print(f"导出完成：素材卡 {report['cards']}，知识点 {report['claims']}，"
          f"复制原文拦截 {len(report['verbatim_skipped'])} — {args.out / 'PORTFOLIO_EXPORT.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
