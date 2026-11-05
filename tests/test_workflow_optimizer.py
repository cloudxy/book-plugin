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



class ModuleCandidates(unittest.TestCase):
    """阶段模块候选：一次只改一个模块的一处，版本打候选标记，源文件不变。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-optimizer-modules-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.base = self.ws / "modules.json"
        write_json(self.base, read_json(opt.MODULES))
        self.feedback = self.ws / "feedback.json"
        write_json(self.feedback, {"recurring": [{"stage": "read", "class": "repair:review", "products": ["a", "b"]}]})
        self.worker = self.ws / "fake_worker.py"
        self.worker.write_text(FAKE_WORKER, encoding="utf-8")

    def propose(self, control, name="experiment"):
        path = self.ws / f"{name}.json"
        write_json(path, control)
        return opt.propose(self.base, self.feedback, [sys.executable, "-B", str(self.worker), str(path)], self.ws / name)

    def test_example_candidate_tags_only_that_module(self):
        example = {"situation": "synthetic", "good": "g", "bad": "b", "why": "w"}
        result = self.propose({"stage": "read", "change": "example", "instruction": "", "example": example,
                               "failure_handling": None, "rationale": "recurring qualifier loss in two books"})
        candidate = read_json(Path(result["modules"]))
        base = read_json(self.base)
        self.assertEqual(candidate["modules"]["read"]["examples"][-1], example)
        self.assertTrue(candidate["modules"]["read"]["version"].startswith("read/2+cand-"))
        self.assertEqual(candidate["modules"]["synthesize"], base["modules"]["synthesize"])
        self.assertEqual(read_json(self.base), base)

    def test_candidate_must_target_one_editable_module(self):
        for control in ({"stage": "build", "change": "instruction", "instruction": "x", "example": None, "failure_handling": None, "rationale": "r"},
                        {"stage": "read", "change": "everything", "instruction": "x", "example": None, "failure_handling": None, "rationale": "r"}):
            with self.assertRaises(ContractError):
                self.propose(control, name=control["stage"] + control["change"])


class ExperienceLedger(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-experience-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.ledger = self.ws / "experience.json"
        self.modules = self.ws / "candidate.json"
        write_json(self.modules, {"schema_version": "stage-modules/1", "version": "cand"})
        opt.experience_add(self.ledger, "keep-qualifiers", "read", "Copy limiting conditions into entry content",
                           ["argument genre"], ["purely narrative scenes"], ["book-a", "book-b"], self.modules)

    def comparison(self, **changes):
        from book_skill_common import digest
        data = {"split": "held-out-source", "product": "book-c", "quality_nonregression": True,
                "candidate_modules_sha256": digest(read_json(self.modules)), **changes}
        path = self.ws / "comparison.json"
        write_json(path, data)
        return path

    def test_global_scope_needs_untuned_held_out_book(self):
        for changes, reason in (({"split": "development"}, "held-out"), ({"product": "book-a"}, "tuning"),
                                ({"quality_nonregression": False}, "regressed"), ({"candidate_modules_sha256": "x"}, "different modules")):
            outcome = opt.experience_promote(self.ledger, "keep-qualifiers", self.comparison(**changes))
            self.assertEqual(outcome["scope"], "book")
            self.assertTrue(any(reason in r for r in outcome["reasons"]), outcome)
        outcome = opt.experience_promote(self.ledger, "keep-qualifiers", self.comparison())
        self.assertEqual((outcome["status"], outcome["scope"]), ("validated", "global"))

    def test_new_entries_cannot_start_global(self):
        with self.assertRaises(ContractError):
            opt.experience_add(self.ledger, "other", "read", "rule", ["c"], [], ["book-a"], self.modules, scope="global")


class PooledFailures(unittest.TestCase):
    def test_only_cross_book_problems_become_workflow_candidates(self):
        import production as p
        sys.path.insert(0, str(ROOT / "tests"))
        from support.production import drive, result
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            roots = []
            for name in ("book-a", "book-b"):
                src = ws / f"{name}.txt"
                src.write_text("Synthetic conditions before conclusions.\n" * 12)
                root = ws / name
                p.init(root, [{"path": str(src), "role": "x", "period": "v1"}],
                       {"id": name, "object": "book", "title": name, "period": "v1", "purpose": "t", "profiles": ["knowledge"]},
                       {"chunk_chars": 200, "merge_fanout": 2})
                first = p.claim(root, "t")
                p.collect(root, first["task_id"], first["claim_token"], {}, {"host": "h", "model": "m", "session_id": "s"},
                          error="worker exited 1", detail="Selected model is at capacity")
                if name == "book-a":
                    p.policy_set(root, {"max_calls": 90}, "single-book adjustment")
                roots.append(root)
            pooled = opt.pooled_failures(roots)
            self.assertIn(("read", "transient"), {(r["stage"], r["class"]) for r in pooled["recurring"]})
            self.assertIn(("orchestration", "intervention:policy"), {(r["stage"], r["class"]) for r in pooled["single_product"]})


if __name__ == "__main__":
    unittest.main()
