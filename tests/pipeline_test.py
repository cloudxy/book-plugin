"""产线三件套合同测试；合成文本与条目不是真实书籍素材。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
from book_skill_common import ContractError, digest, qnorm, read_json  # noqa: E402
from batch_runner import book_state, next_action, status as batch_status  # noqa: E402
from export_portfolio import export, register, verbatim_hit  # noqa: E402
from l1_extract import check as l1_check, init as l1_init  # noqa: E402


def synthetic_source(path):
    parts = [f"第{i}节　" + f"这一节讨论领域{i}的方法论，主张{i}号命题，给出论证{i}与反例{i}的处理。" * 12
             for i in range(1, 31)]
    path.write_text("\n".join(parts), encoding="utf-8")


def bucket_entry(index, src, kind="claim"):
    start = index * len(src) // 10 + 3
    end = start + 30
    return {"id": f"E{index:02d}", "kind": kind,
            "statement": f"合成命题{index}：来自桶{index}的重述，不复制原文。",
            "locator": f"合成第{index}节", "start": start, "end": end,
            "span_sha256": digest(src[start:end].encode()), "epistemic_status": "explicit"}


class L1Gates(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-pipeline-test-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.book = self.ws / "books/pipeline-book"
        self.source = self.ws / "source.txt"
        synthetic_source(self.source)
        l1_init(self.book, self.source, "合成方法书", "合成作者", "论说与思想", "")
        self.path = self.book / "l1/material.yaml"
        self.src = qnorm(self.source.read_text(encoding="utf-8"))

    def material(self, entries):
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        data["entries"] = entries
        self.path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def test_gates_pass_and_stats(self):
        self.material([bucket_entry(i, self.src) for i in range(10)])
        result = l1_check(self.book, self.source, self.ws)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["stats"]["buckets_covered"], 10)
        self.assertEqual(result["stats"]["by_kind"]["claim"], 10)
        self.assertEqual(read_json(self.ws / ".work/pipeline-book/l1-check.json")["status"], "passed")

    def test_no_entries_fails(self):
        result = l1_check(self.book, self.source, self.ws)
        self.assertEqual(result["status"], "failed")

    def test_bad_span_hash_fails(self):
        entries = [bucket_entry(i, self.src) for i in range(10)]
        entries[3]["span_sha256"] = "0" * 64
        self.material(entries)
        self.assertIn("span hash mismatch", l1_check(self.book, self.source, self.ws)["error"])

    def test_missing_bucket_fails(self):
        self.material([bucket_entry(i, self.src) for i in range(10) if i != 7])
        self.assertIn("decile buckets", l1_check(self.book, self.source, self.ws)["error"])

    def test_relation_endpoint_and_duplicate(self):
        entries = [bucket_entry(i, self.src) for i in range(10)]
        entries.append({**bucket_entry(9, self.src, "relation"), "id": "R01", "type": "supports",
                        "from": "E00", "to": "missing"})
        self.material(entries)
        self.assertIn("unknown endpoint", l1_check(self.book, self.source, self.ws)["error"])
        entries[-1]["to"] = "E01"
        entries.append(dict(entries[0]))
        self.material(entries)
        self.assertIn("duplicate entry id", l1_check(self.book, self.source, self.ws)["error"])

    def test_reinit_refused(self):
        with self.assertRaises(ContractError):
            l1_init(self.book, self.source, "x", "y", "z", "")


class PortfolioExport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-portfolio-test-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.book = self.ws / "books/portfolio-book"
        self.source = self.ws / "source.txt"
        synthetic_source(self.source)
        l1_init(self.book, self.source, "合成素材书", "合成作者", "科学与专业学说", "")
        self.path = self.book / "l1/material.yaml"
        self.src = qnorm(self.source.read_text(encoding="utf-8"))
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        data["entries"] = [bucket_entry(i, self.src) for i in range(10)]
        self.path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.assertEqual(l1_check(self.book, self.source, self.ws)["status"], "passed")
        self.out = self.ws / "materials"

    def test_register_book_and_person(self):
        entry = register(self.ws, "book", "portfolio-book", "2026", "合成素材书",
                         "L1", "portfolio-book", "科学与专业学说")
        self.assertEqual(entry["fact_chain"], "allowed")
        person = register(self.ws, "person", "sun-wu", "春秋", "孙武")
        self.assertEqual(person["fact_chain"], "forbidden")
        self.assertEqual(person["tier"], "external")
        with self.assertRaises(ContractError):
            register(self.ws, "book", "portfolio-book", "2026", "合成素材书",
                     "L1", "portfolio-book", "科学与专业学说")
        with self.assertRaises(ContractError):
            register(self.ws, "book", "bad-tier", "2026", "x", "L9", "bad-tier", "y")

    def test_export_cards_and_claims(self):
        register(self.ws, "book", "portfolio-book", "2026", "合成素材书",
                 "L1", "portfolio-book", "科学与专业学说")
        register(self.ws, "person", "sun-wu", "春秋", "孙武")
        report = export(self.ws, self.out)
        self.assertEqual(report["cards"], 10)
        self.assertEqual(report["claims"], 10)
        card = next((self.out / "素材/未分").glob("portfolio-book-M0001-*.md"))
        body = card.read_text(encoding="utf-8")
        self.assertIn("可信级：拆书", body)
        self.assertIn("来源：拆:合成素材书", body)
        lines = (self.out / "知识点/claims.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 10)
        person = next(item for item in report["entries"] if item.get("exported") == "inventory-only")
        self.assertEqual(person["fact_chain"], "forbidden")

    def test_export_blocks_unchecked_or_tampered(self):
        register(self.ws, "book", "portfolio-book", "2026", "合成素材书",
                 "L1", "portfolio-book", "科学与专业学说")
        gate = self.ws / ".work/portfolio-book/l1-check.json"
        gate.unlink()
        with self.assertRaises(ContractError):
            export(self.ws, self.out)
        l1_check(self.book, self.source, self.ws)
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        data["entries"][0]["statement"] = "过闸后偷改的陈述"
        self.path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        with self.assertRaises(ContractError):
            export(self.ws, self.out)

    def test_export_style_anchor_for_l2(self):
        profile = self.book / "expression/PROFILE.md"
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text("# 表达规格\n\n## 运行摘要\n\n短句压实判断，先重述再转折。\n\n## 来源记录\n\n- 合成\n",
                           encoding="utf-8")
        register(self.ws, "book", "portfolio-book", "2026", "合成素材书",
                 "L2", "portfolio-book", "文学叙事")
        report = export(self.ws, self.out)
        anchor = self.out / "文风锚/portfolio-book.md"
        self.assertIn("短句压实判断", anchor.read_text(encoding="utf-8"))
        book_record = next(item for item in report["entries"] if item["key"].startswith("book:"))
        self.assertTrue(book_record["style_anchor"])
        profile.unlink()
        with self.assertRaises(ContractError):
            export(self.ws, self.out)

    def test_export_key_filter(self):
        entry = register(self.ws, "book", "portfolio-book", "2026", "合成素材书",
                         "L1", "portfolio-book", "科学与专业学说")
        register(self.ws, "person", "sun-wu", "春秋", "孙武")
        report = export(self.ws, self.out, [entry["key"]])
        self.assertEqual([item["key"] for item in report["entries"]], [entry["key"]])
        with self.assertRaises(ContractError):
            export(self.ws, self.out, ["book:none@never"])

    def test_verbatim_guard_skips_copy(self):
        copy = dict(bucket_entry(0, self.src))
        copy.update(id="E90", start=100, end=160, statement=self.src[100:150],
                    span_sha256=digest(self.src[100:160].encode()), locator="逐字复制段")
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        data["entries"].append(copy)
        self.path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.assertEqual(l1_check(self.book, self.source, self.ws)["status"], "passed")
        register(self.ws, "book", "portfolio-book", "2026", "合成素材书",
                 "L1", "portfolio-book", "科学与专业学说")
        report = export(self.ws, self.out)
        self.assertEqual(report["cards"], 10)
        self.assertEqual([skip["id"] for skip in report["verbatim_skipped"]], ["E90"])
        self.assertTrue(verbatim_hit(self.src[100:150], self.src[100:160]))
        self.assertFalse(verbatim_hit("完全重写的陈述，不含原文连续片段。", self.src[100:160]))


class BatchRunner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-batch-test-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)

    def book(self, name, tier=None):
        path = self.ws / "books" / name
        path.mkdir(parents=True)
        body = "# PIPELINE_STATE\n\n当前阶段: 0（未开始）\n"
        if tier:
            body += f"档位: {tier}\n"
        (path / "PIPELINE_STATE.md").write_text(body, encoding="utf-8")
        return path

    def test_plan_progression(self):
        book = self.book("batch-l1", "L1")
        self.book("batch-none")
        states = {item["slug"]: item for item in batch_status(self.ws)}
        self.assertIn("登记档位", next_action(states["batch-none"]))
        self.assertIn("L1 init", next_action(states["batch-l1"]))
        source = self.ws / "src.txt"
        synthetic_source(source)
        l1_init(book, source, "批量书", "作者", "论说与思想", "")
        self.assertIn("check", next_action(book_state(self.ws, book)))
        path = book / "l1/material.yaml"
        src = qnorm(source.read_text(encoding="utf-8"))
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["entries"] = [bucket_entry(i, src) for i in range(10)]
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        l1_check(book, source, self.ws)
        self.assertIn("register", next_action(book_state(self.ws, book)))
        self.assertEqual(len(batch_status(self.ws, tier="L1")), 1)


if __name__ == "__main__":
    unittest.main()
