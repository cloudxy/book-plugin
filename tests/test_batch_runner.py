# -*- coding: utf-8 -*-
"""batch_runner 补测：产线（pipeline/state.json）分支、下一步动作卡与过滤。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
sys.path.insert(0, str(ROOT / "tests"))
import production as p  # noqa: E402
from batch_runner import book_state, next_action, read_tier, status  # noqa: E402
from support.books import synthetic_source  # noqa: E402


class BatchRunnerProductionState(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-batch-prod-test-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.book = self.ws / "books" / "prod-book"
        self.book.mkdir(parents=True)
        self.src = self.ws / "src.txt"
        synthetic_source(self.src, sections=3, repeat=2)
        product = {"id": "synthetic", "object": "book", "title": "Synthetic", "period": "v1",
                   "purpose": "Contract tests", "profiles": ["knowledge"]}
        p.init(self.book / "pipeline", [{"path": str(self.src), "role": "synthetic", "period": "v1"}],
               product, {"chunk_chars": 200, "merge_fanout": 2})

    def test_production_book_is_tier_l2_with_l1_not_used(self):
        state = book_state(self.ws, self.book)
        self.assertEqual(state["tier"], "L2")
        self.assertTrue(state["l1_started"])
        self.assertEqual(state["l1_gates"], "not-used")
        self.assertEqual(state["source_gates"], "pending")
        self.assertIn("production", state)
        self.assertTrue(next_action(state).startswith("production.py run/resume："))

    def test_next_action_production_branches(self):
        self.assertIn("sync", next_action({"production": {"status": "stale-source"}}))
        self.assertIn("production.py evaluate", next_action({"production": {"status": "built-pending-runtime"}}))
        self.assertIn("deliver", next_action({"production": {"status": "tested-trial"}}))
        self.assertIn("不是 Skill", next_action({"production": {"status": "material-ready"}}))
        self.assertIn("已隔离缺口", next_action({"production": {"status": "blocked", "lifecycle": {"blocked": [{"reason": "gap"}]}}}))
        self.assertEqual(next_action({"production": {"status": "pending", "ready": ["read", "merge"]}}),
                         "production.py run/resume：read, merge")

    def test_next_action_tiered_books(self):
        self.assertIn("production.py init", next_action({"tier": None, "l1_started": False}))
        self.assertIn("L1 init", next_action({"tier": "L1", "l1_started": False}))
        self.assertIn("过闸", next_action({"tier": "L1", "l1_started": True, "l1_gates": None}))
        self.assertIn("skill_portfolio.py register",
                      next_action({"tier": "L1", "l1_started": True, "l1_gates": "passed"}))
        self.assertIn("L2 重建", next_action({"tier": "L2", "l1_started": True, "l1_gates": "passed",
                                              "l2_started": False}))
        self.assertIn("来源闸", next_action({"tier": "L2", "l1_started": True, "l1_gates": "passed",
                                             "l2_started": True, "source_gates": None}))
        self.assertIn("验收/发布", next_action({"tier": "L2", "l1_started": True, "l1_gates": "passed",
                                                "l2_started": True, "source_gates": "passed"}))


class BatchRunnerStatus(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-batch-status-test-")
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

    def test_portfolio_directory_is_excluded(self):
        self.book("real-book", "L1")
        portfolio = self.ws / "books" / "portfolio"
        portfolio.mkdir()
        (portfolio / "PIPELINE_STATE.md").write_text("# PIPELINE_STATE\n\n档位: L1\n", encoding="utf-8")
        self.assertEqual([s["slug"] for s in status(self.ws)], ["real-book"])

    def test_slug_filter_and_empty_listing(self):
        self.book("alpha", "L1")
        self.book("beta", "L2")
        self.assertEqual([s["slug"] for s in status(self.ws, slugs=["beta"])], ["beta"])
        self.assertEqual(status(self.ws, slugs=["ghost"]), [])
        self.assertEqual(status(self.ws / "nowhere"), [])

    def test_read_tier_parses_only_registered_line(self):
        path = self.ws / "state.md"
        path.write_text("# PIPELINE_STATE\n\n档位: L3\n", encoding="utf-8")
        self.assertEqual(read_tier(path), "L3")
        path.write_text("# PIPELINE_STATE\n\n档位:L4\n", encoding="utf-8")   # 缺空格不匹配
        self.assertIsNone(read_tier(path))
        self.assertIsNone(read_tier(self.ws / "missing.md"))


if __name__ == "__main__":
    unittest.main()
