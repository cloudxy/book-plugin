"""旧 L1 素材原型，仅保留格式兼容；新生产入口为 production.py。

条目必须落在 qnorm 原文真实跨度上（span_sha256 回验），且每个十分位桶
至少一条已验条目。这只统计条目跨度，不能证明全文阅读或语义覆盖；条目
陈述是否忠于跨度由抽样语义复核负责，不在本脚本。人员来源（person）
不经此产线。Exit 0 passed / 1 failed / 2 usage。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from book_skill_common import (ContractError, digest, load_source, qnorm, read_yaml, slug,
    source_hashes, text, write_json)

L1_SCHEMA = "book-material/1"
BUCKETS = 10
ENTRY_KINDS = ("concept", "claim", "relation")
RELATION_TYPES = ("causal", "conditional", "value", "analogy", "narrative",
                  "supports", "constrains", "contradicts", "depends_on")


def bucket_ranges(length):
    return [(i * length // BUCKETS, (i + 1) * length // BUCKETS) for i in range(BUCKETS)]


def init(book, source, title, author, kind, edition):
    book = Path(book)
    path = book / "l1/material.yaml"
    if path.exists():
        raise ContractError("l1 material exists; resume by editing it, never re-init")
    data = {"schema_version": L1_SCHEMA,
            "source": {**source_hashes(source), "path": str(Path(source).resolve())},
            "book": {"id": slug(book.name), "title": text(title, "title"),
                     "author": text(author, "author"), "edition": edition or "未登记",
                     "kind": text(kind, "kind"), "description": "L1 素材档：概念/命题/关系＋定位"},
            "entries": []}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return data


def check(book, source, ws):
    try:
        result = _validate(book, source)
    except (ContractError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result = {"schema_version": L1_SCHEMA, "status": "failed", "error": str(exc)}
    path = Path(ws) / ".work" / slug(Path(book).name) / "l1-check.json"
    write_json(path, result)
    return result


def _validate(book, source):
    data = read_yaml(Path(book) / "l1/material.yaml")
    if data.get("schema_version") != L1_SCHEMA:
        raise ContractError(f"unsupported material schema: {data.get('schema_version')}")
    stored = data.get("source") or {}
    hashes = {key: stored.get(key) for key in ("raw_sha256", "text_sha256", "normalization")}
    if hashes != source_hashes(source):
        raise ContractError("material source version/hash differs from actual source")
    text(stored.get("path"), "source.path")
    meta = data.get("book", {})
    slug(meta.get("id"))
    for name in ("title", "author", "edition", "kind", "description"):
        text(meta.get(name), f"book.{name}")
    src = qnorm(load_source(source))
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ContractError("entries: at least one located entry required")
    ids = {}
    covered = [False] * BUCKETS
    for entry in entries:
        eid = text(entry.get("id"), "entry.id")
        if eid in ids:
            raise ContractError(f"duplicate entry id: {eid}")
        if entry.get("kind") not in ENTRY_KINDS:
            raise ContractError(f"{eid}: unknown entry kind")
        text(entry.get("statement"), f"{eid}.statement")
        text(entry.get("locator"), f"{eid}.locator")
        if entry.get("epistemic_status") not in {"explicit", "reconstructed", "unresolved"}:
            raise ContractError(f"{eid}: invalid epistemic_status")
        start, end = entry.get("start"), entry.get("end")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(src):
            raise ContractError(f"{eid}: span out of qnorm range")
        if entry.get("span_sha256") != digest(src[start:end].encode()):
            raise ContractError(f"{eid}: span hash mismatch (not at declared qnorm offset)")
        ids[eid] = entry
        for index, (bstart, bend) in enumerate(bucket_ranges(len(src))):
            if start < bend and bstart < end:
                covered[index] = True
    for eid, entry in ids.items():
        if entry.get("kind") != "relation":
            continue
        if entry.get("type") not in RELATION_TYPES:
            raise ContractError(f"{eid}: unknown relation type")
        for field in ("from", "to"):
            if entry.get(field) not in ids:
                raise ContractError(f"{eid}.{field}: unknown endpoint")
    missing = [i for i, hit in enumerate(covered) if not hit]
    if missing:
        raise ContractError(f"decile buckets without any verified entry: {missing}")
    kinds = [entry["kind"] for entry in ids.values()]
    return {"schema_version": L1_SCHEMA, "status": "passed",
            "verification_scope": "legacy-structure-and-location-only; not reading, semantics or Skill acceptance",
            "source_text_sha256": data["source"]["text_sha256"],
            "material_sha256": digest((Path(book) / "l1/material.yaml").read_bytes()),
            "book": meta,
            "stats": {"entries": len(ids), "by_kind": {k: kinds.count(k) for k in ENTRY_KINDS},
                      "buckets_covered": BUCKETS, "qnorm_length": len(src)}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="create l1/material.yaml skeleton; never overwrite")
    p.add_argument("--book-dir", required=True, type=Path)
    p.add_argument("--source", required=True, type=Path)
    for name in ("--title", "--author", "--kind"):
        p.add_argument(name, required=True)
    p.add_argument("--edition", default="未登记")
    p = sub.add_parser("check", help="machine gates: span hashes + decile coverage + schema")
    p.add_argument("--book-dir", required=True, type=Path)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--ws", required=True, type=Path)
    p = sub.add_parser("hash", help="span_sha256 for a qnorm range, used while registering entries")
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--start", required=True, type=int)
    p.add_argument("--end", required=True, type=int)
    args = ap.parse_args()
    if args.cmd == "init":
        init(args.book_dir, args.source, args.title, args.author, args.kind, args.edition)
        length = len(qnorm(load_source(args.source)))
        print(f"L1 骨架就绪：{args.book_dir}/l1/material.yaml")
        print(f"十分位桶阅读计划（每桶至少一条定位条目，qnorm 全长 {length}）：")
        for i, (start, end) in enumerate(bucket_ranges(length)):
            print(f"  桶{i}: qnorm[{start},{end})")
        return 0
    if args.cmd == "hash":
        src = qnorm(load_source(args.source))
        if not 0 <= args.start < args.end <= len(src):
            ap.error("range out of bounds")
        print(digest(src[args.start:args.end].encode()))
        return 0
    result = check(args.book_dir, args.source, args.ws)
    path = Path(args.ws) / ".work" / slug(args.book_dir.name) / "l1-check.json"
    print(f"L1 机器闸: {result['status']} — {path}")
    if result.get("error"):
        print(result["error"])
    return {"passed": 0, "failed": 1}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
