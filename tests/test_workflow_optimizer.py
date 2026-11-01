# -*- coding: utf-8 -*-
"""workflow_optimizer.propose 的有界实验合同：候选永不自动采纳，坏候选必须拒。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
import workflow_optimizer as opt  # noqa: E402
from book_skill_common import ContractError, read_json, write_json  # noqa: E402

FAKE_WORKER = r"""# -*- coding: utf-8 -*-
import json, sys
control = json.loads(open(sys.argv[1], encoding="utf-8").read())
sys.stdin.read()                      # 消费 packet，内容不进结果
print(json.dumps({"result": control}))
"""


class OptimizerPropose(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-optimizer-test-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.base = self.ws / "prompts.json"
        write_json(self.base, {"read": "read-instruction", "merge": "merge-instruction",
                               "synthesize": "synthesize-instruction", "review": "review-instruction"})
        self.feedback = self.ws / "feedback.json"
        write_json(self.feedback, {"failures": [{"task": "read-01", "reason": "synthetic observation"}]})
        self.worker = self.ws / "fake_worker.py"
        self.worker.write_text(FAKE_WORKER, encoding="utf-8")

    def propose(self, stage, instruction=""):
        control = self.ws / "control.json"
        write_json(control, {"stage": stage, "instruction": instruction, "rationale": "synthetic failure link"})
        return opt.propose(self.base, self.feedback, [sys.executable, "-B", str(self.worker), str(control)],
                           self.ws / "experiment")

    def test_stage_none_keeps_prompts_unchanged(self):
        result = self.propose("none")
        self.assertEqual(result["status"], "candidate-not-adopted")
        self.assertEqual(result["stage"], "none")
        self.assertEqual(read_json(self.base),
                         {"read": "read-instruction", "merge": "merge-instruction",
                          "synthesize": "synthesize-instruction", "review": "review-instruction"})
        experiment = read_json(self.ws / "experiment" / "experiment.json")
        self.assertEqual(experiment["base_sha256"], experiment["candidate_sha256"])

    def test_valid_stage_rewrites_only_that_stage(self):
        result = self.propose("read", "revised read instruction")
        self.assertEqual(result["stage"], "read")
        prompts = read_json(self.ws / "experiment" / "prompts.json")
        self.assertEqual(prompts["read"], "revised read instruction")
        self.assertEqual(prompts["synthesize"], "synthesize-instruction")
        self.assertNotEqual(read_json(self.ws / "experiment" / "experiment.json")["base_sha256"],
                            read_json(self.ws / "experiment" / "experiment.json")["candidate_sha256"])

    def test_unknown_stage_is_rejected(self):
        with self.assertRaises(ContractError):
            self.propose("bogus")

    def test_existing_experiment_directory_is_preserved(self):
        (self.ws / "experiment").mkdir()
        with self.assertRaises(ContractError):
            self.propose("read")
        self.assertEqual(list((self.ws / "experiment").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
