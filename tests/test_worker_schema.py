# -*- coding: utf-8 -*-
"""worker_schema 各阶段结构化输出合同：包裹应答形状，且不给答题侧泄漏多余字段。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
import worker_schema as ws  # noqa: E402


class WorkerSchemaStages(unittest.TestCase):
    def test_read_and_merge_require_observation_shape(self):
        for stage in ("read", "merge"):
            schema = ws.for_packet({"stage": stage})
            self.assertEqual(set(schema["properties"]),
                             {"covered_units", "findings", "limitations", "open_connections"})
            self.assertEqual(set(schema["required"]),
                             {"covered_units", "findings", "limitations", "open_connections"})
            self.assertFalse(schema["additionalProperties"])

    def test_answer_packet_schema_is_answer_only(self):
        schema = ws.for_packet({"conversation": [{"role": "user", "content": "synthetic"}]})
        self.assertEqual(set(schema["properties"]), {"answer"})
        self.assertFalse(schema["additionalProperties"])

    def test_review_packet_schema_is_dimensions_only(self):
        schema = ws.for_packet({"rubric": "synthetic", "answers": ["synthetic"]})
        self.assertEqual(set(schema["properties"]), {"dimensions", "hard_failures"})
        self.assertEqual(set(schema["properties"]["dimensions"]["properties"]),
                         {"fidelity", "application", "utility"})
        score = schema["properties"]["dimensions"]["properties"]["utility"]
        self.assertEqual(score["properties"]["score"]["minimum"], 0)
        self.assertEqual(score["properties"]["score"]["maximum"], 3)

    def test_unknown_packet_has_no_schema(self):
        self.assertIsNone(ws.for_packet({"stage": "bogus"}))
        self.assertIsNone(ws.for_packet({}))


if __name__ == "__main__":
    unittest.main()
