"""Synthetic contract tests; fixture answers/reviews are not model eval results."""
from __future__ import annotations

import copy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
from book_skill_common import (ContractError, DIMENSIONS, STYLE_DIMENSIONS, digest,
    input_snapshot, read_json, read_yaml, source_hashes, tree_hashes, verify_package, write_json)
from thinking_audit import audit, validate
from build_book_skill import build_candidate, publish
from eval_book_skill import collect, prepare, report_run


class ThinkingContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-thinking-test-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.book = self.ws / "books/thinking-book"
        shutil.copytree(ROOT / "tests/fixtures/thinking-book", self.book)
        self.source = self.ws / "source.md"
        shutil.copyfile(ROOT / "tests/fixtures/thinking-source.md", self.source)
        self.modelpath = self.book / "thinking/model.yaml"

    def yaml(self, path, data):
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))

    def approve_source_fixture(self):
        """Simulated reviewer solely for contract tests, not a real book verdict."""
        result = validate(self.book, self.source)
        record = {"input_sha256": result["input_sha256"], "reviewer": "synthetic-test-reviewer",
                  "independent": True, "checks": {key: {"status": "passed", "rationale": "synthetic test oracle"}
                                                    for key in result["checks"]}}
        write_json(self.book / "eval/source-review.json", record)
        self.assertEqual(audit(self.book, self.source)["status"], "passed")

    def candidate(self):
        self.approve_source_fixture()
        return build_candidate(self.book, self.source, self.ws)

    def suite(self, all_groups=True):
        groups = range(1, 16) if all_groups else [2]
        cases = [{"id": f"C{i:02}-01", "group": f"C{i:02}", "prompt": "synthetic fixture input",
                  "required": True, "held_out": True, "expected_dimensions": list(DIMENSIONS),
                  "rubric": ["synthetic structural test oracle, not a real semantic score"]} for i in groups]
        path = self.ws / "suite.yaml"
        self.yaml(path, {"cases": cases})
        return path

    def prepare_run(self, all_groups=True, variant="candidate"):
        return prepare(self.candidate(), self.suite(all_groups), self.ws / "run", variant)

    def populate_fixture(self, run, approve_user=True):
        suite = read_json(run / "suite.json")
        hashes = {}
        for case in suite["cases"]:
            cid = case["id"]
            output = {"case_id": cid, "answers": ["synthetic fixture output; not a model run"],
                      "executor": "fixture-executor", "host": "test", "model": "test-only",
                      "session_id": cid, "isolated": True, "loading_evidence": "fixture only"}
            raw = self.ws / f"{cid}.json"
            write_json(raw, output)
            collect(run, cid, raw)
            hashes[cid] = digest(output)
            write_json(run / "reviews" / f"{cid}.json", {
                "answer_sha256": digest(output), "rubric_sha256": digest(case),
                "reviewer": "fixture-reviewer", "independent": True, "blind": True,
                "dimensions": {d: {"score": 2, "rationale": "synthetic test oracle"} for d in DIMENSIONS},
                "expression": {d: {"score": 2, "rationale": "synthetic test oracle"} for d in STYLE_DIMENSIONS},
                "hard_failures": [],
            })
        if approve_user:
            config = read_json(run / "run.json")
            write_json(run / "user-expression.json", {
                "build_id": config["build_id"], "suite_sha256": config["suite_sha256"],
                "output_sha256": hashes, "reviewer_role": "user", "approved": True,
                "rationale": "SIMULATED USER RECORD FOR CONTRACT TEST ONLY",
            })

    def test_source_hit_without_semantics_is_pending(self):
        result = audit(self.book, self.source)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["structural"], "passed")
        with self.assertRaises(ContractError):
            build_candidate(self.book, self.source, self.ws)

    def test_quote_context_source_and_relationship_mutants(self):
        evidence_path = self.book / "evidence/anchors.yaml"
        evidence = read_yaml(evidence_path)
        model = read_yaml(self.modelpath)
        mutants = []
        for mutate in (
            lambda e: e["anchors"][0].update(quote="原文不存在的伪造引文"),
            lambda e: e["anchors"][0].update(start=99999),
            lambda e: e["anchors"][0]["context"].update(start=0),
            lambda e: e["source"].update(raw_sha256="0" * 64),
        ):
            changed = copy.deepcopy(evidence); mutate(changed); mutants.append(changed)
        for changed in mutants:
            with self.subTest(changed=changed):
                self.yaml(evidence_path, changed)
                self.assertEqual(audit(self.book, self.source)["status"], "failed")
        self.yaml(evidence_path, evidence)
        for field, value in (("from", "missing"), ("to", "missing"), ("type", "imagined")):
            changed = copy.deepcopy(model); changed["relations"][0][field] = value
            self.yaml(self.modelpath, changed)
            self.assertEqual(audit(self.book, self.source)["status"], "failed")

    def test_unresolved_duplicate_and_empty_core_are_rejected(self):
        original = read_yaml(self.modelpath)
        for mode in ("unresolved", "duplicate", "empty"):
            model = copy.deepcopy(original)
            if mode == "unresolved": model["claims"][0]["epistemic_status"] = "unresolved"
            if mode == "duplicate": model["concepts"][0]["id"] = model["claims"][0]["id"]
            if mode == "empty": model["core"]["text"] = ""
            self.yaml(self.modelpath, model)
            self.assertEqual(audit(self.book, self.source)["status"], "failed", mode)

    def test_cycles_are_legal_when_all_references_are_known(self):
        model = read_yaml(self.modelpath)
        model["claims"][0]["depends_on"] = ["R-scope"]
        self.yaml(self.modelpath, model)
        self.assertEqual(audit(self.book, self.source)["status"], "pending")

    def test_yaml_duplicate_keys_fail(self):
        self.modelpath.write_text(self.modelpath.read_text() + "\nschema_version: book-skill/1\n")
        self.assertEqual(audit(self.book, self.source)["status"], "failed")

    def test_style_and_example_contracts(self):
        path = self.book / "expression/PROFILE.md"
        original = path.read_text()
        path.write_text(original.replace("## 运行摘要", "## 其他"))
        self.assertEqual(audit(self.book, self.source)["status"], "failed")
        path.write_text(original + "\n## 运行摘要\n重复\n")
        self.assertEqual(audit(self.book, self.source)["status"], "failed")
        # Source metadata must not become mandatory runtime instructions.
        path.write_text(original.replace("## 来源条目\n", ""))
        self.assertEqual(audit(self.book, self.source)["status"], "failed")
        path.write_text(original)
        path = self.book / "thinking/EXAMPLES.md"
        path.write_text(path.read_text().replace("condition_variant", "application"))
        self.assertEqual(audit(self.book, self.source)["status"], "failed")

    def test_every_material_change_revokes_source_review(self):
        self.approve_source_fixture()
        for rel in ("thinking/model.yaml", "thinking/EXAMPLES.md", "expression/PROFILE.md", "coverage-audit.md"):
            path = self.book / rel; original = path.read_text()
            path.write_text(original + "\n# changed\n")
            self.assertEqual(audit(self.book, self.source)["status"], "failed", rel)
            path.write_text(original)
        self.source.write_text(self.source.read_text() + "\n新原文\n")
        self.assertEqual(audit(self.book, self.source)["status"], "failed")

    def test_na_cannot_hide_a_procedure_bundle(self):
        (self.book / ".cangjie/capabilities").mkdir(parents=True)
        self.assertEqual(audit(self.book, self.source)["status"], "failed")

    def test_english_quote_limit_and_missing_r_quotes_are_enforced(self):
        book = self.ws / "english-procedure"
        card = book / ".cangjie/capabilities/cards/test.md"
        card.parent.mkdir(parents=True)
        source = self.ws / "english.txt"
        for words, expected in ((80, 0), (101, 1)):
            quote = " ".join(["condition"] * words)
            source.write_text(quote)
            card.write_text("## R — source\n\n> " + quote + "\n\n## I — interpretation\nSynthetic.\n")
            result = subprocess.run([sys.executable, str(ROOT / "bridge/cangjie_to_dsh.py"),
                "--book-dir", str(book), "--source", str(source), "--task", "english-procedure",
                "--ws", str(self.ws)], capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        card.write_text("## I — missing source\nNo R quotes.\n")
        result = subprocess.run([sys.executable, str(ROOT / "bridge/cangjie_to_dsh.py"),
            "--book-dir", str(book), "--source", str(source), "--task", "english-procedure",
            "--ws", str(self.ws)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)

    def test_review_targets_and_independence_are_required(self):
        self.approve_source_fixture()
        path = self.book / "eval/source-review.json"
        record = read_json(path)
        for field, value in (("independent", False), ("reviewer", "synthetic-fixture-author"), ("checks", {})):
            changed = copy.deepcopy(record); changed[field] = value
            write_json(path, changed)
            self.assertEqual(audit(self.book, self.source)["status"], "failed")

    def test_candidate_is_portable_and_contains_actual_core_and_voice(self):
        package = self.candidate()
        model = read_yaml(self.modelpath)
        entry = (package / "SKILL.md").read_text()
        self.assertIn(model["core"]["text"].strip(), entry)
        self.assertIn("从当前条件起笔", entry)
        self.assertNotIn(str(self.ws), entry)
        self.assertEqual(len(list(package.rglob("SKILL.md"))), 1)
        self.assertTrue((package / "references/thinking/EXAMPLES.md").is_file())
        copied = self.ws / "standalone"
        shutil.copytree(package, copied)
        shutil.rmtree(self.book)
        verify_package(copied)

    def test_candidate_tamper_missing_and_unlisted_files_fail(self):
        package = self.candidate()
        path = package / "references/thinking/CORE.md"
        original = path.read_bytes()
        path.write_text("changed")
        with self.assertRaises(ContractError): verify_package(package)
        path.unlink()
        with self.assertRaises(ContractError): verify_package(package)
        path.write_bytes(original)
        (package / "unlisted.md").write_text("unlisted")
        with self.assertRaises(ContractError): verify_package(package)

    def test_prepare_does_not_leak_rubric_or_expected_dimensions(self):
        run = self.prepare_run()
        packet = read_json(run / "packets/C01-01.json")
        self.assertEqual(set(packet), {"case_id", "turns", "book_scope", "instruction", "skill"})
        with self.assertRaises(ContractError):
            prepare(run / "skill", self.ws / "suite.yaml", run)

    def test_absent_outputs_are_pending_not_passed(self):
        run = self.prepare_run()
        report = report_run(run)
        self.assertEqual(report["status"], "pending")
        self.assertEqual(report["planned"], 15)
        self.assertEqual(report["actual"], 0)
        self.assertEqual(report["passed"], 0)

    def test_actual_outputs_need_reviews_and_user_style_acceptance(self):
        run = self.prepare_run()
        self.populate_fixture(run, False)
        self.assertEqual(report_run(run, True)["status"], "structural_passed")
        self.assertEqual(report_run(run)["status"], "pending")
        (run / "reviews/C02-01.json").unlink()
        self.assertIn("C02-01", report_run(run)["pending"])

    def test_incomplete_group_coverage_cannot_release(self):
        run = self.prepare_run(False)
        self.populate_fixture(run)
        self.assertEqual(report_run(run)["status"], "pending")

    def test_stale_answers_rubrics_and_bad_scores_fail(self):
        run = self.prepare_run()
        self.populate_fixture(run)
        self.assertEqual(report_run(run)["status"], "passed")
        path = run / "reviews/C01-01.json"; original = read_json(path)
        for mutation in ("stale", "low", "self", "missing", "preservation"):
            review = copy.deepcopy(original)
            if mutation == "stale": review["answer_sha256"] = "0" * 64
            if mutation == "low": review["dimensions"]["inference"]["score"] = 1
            if mutation == "self": review["reviewer"] = "fixture-executor"
            if mutation == "missing": review["hard_failures"] = None
            if mutation == "preservation": review["expression"]["preservation"] = {"status": "not_applicable", "rationale": "bad"}
            write_json(path, review)
            self.assertEqual(report_run(run)["status"], "failed", mutation)
        write_json(path, original)
        suite = read_json(run / "suite.json"); suite["cases"][0]["rubric"] = "changed"
        write_json(run / "suite.json", suite)
        with self.assertRaises(ContractError): report_run(run)

    def test_changed_answers_and_shared_sessions_fail(self):
        run = self.prepare_run(); self.populate_fixture(run)
        path = run / "outputs/C02-01.json"; output = read_json(path)
        output["session_id"] = "C01-01"
        write_json(path, output)
        self.assertEqual(report_run(run)["status"], "failed")

    def test_mixed_host_models_are_reported(self):
        run = self.prepare_run(); self.populate_fixture(run)
        path = run / "outputs/C02-01.json"; output = read_json(path)
        output["model"] = "different-model"
        write_json(path, output)
        self.assertIn("host_or_model_changed_within_run", report_run(run)["failed"])

    def test_material_changes_after_prepare_fail(self):
        run = self.prepare_run()
        (run / "skill/SKILL.md").write_text("changed")
        with self.assertRaises(ContractError): report_run(run)

    def test_changed_question_packets_fail(self):
        run = self.prepare_run()
        packet = run / "packets/C01-01.json"
        record = read_json(packet); record["turns"] = ["different actual question"]
        write_json(packet, record)
        with self.assertRaises(ContractError): report_run(run)

    def test_multi_turn_packets_hide_future_inputs(self):
        candidate = self.candidate()
        suite_path = self.suite(False)
        suite = read_yaml(suite_path)
        suite["cases"][0].pop("prompt")
        suite["cases"][0]["turns"] = [{"role": "user", "content": "first"}, {"role": "user", "content": "future secret"}]
        self.yaml(suite_path, suite)
        run = prepare(candidate, suite_path, self.ws / "run")
        first = read_json(run / "packets/C02-01/turn-01.json")
        self.assertEqual(first["turns"], ["first"])
        self.assertNotIn("future secret", str(first))
        self.assertNotIn("turns", read_json(run / "packets/C02-01.json"))

    def test_publication_uses_exact_tested_payload_and_preserves_old_install(self):
        run = self.prepare_run(); self.populate_fixture(run)
        acceptance = run / "acceptance.json"
        write_json(acceptance, report_run(run))
        out = self.ws / "install/thinking-book"
        publish(run / "skill", acceptance, out)
        self.assertEqual(tree_hashes(out), tree_hashes(run / "skill"))
        with self.assertRaises(ContractError): publish(run / "skill", acceptance, out)
        publish(run / "skill", acceptance, out, replace=True)
        self.assertEqual(len(list(out.parent.glob(".thinking-book-previous-*"))), 1)
        (run / "outputs/C01-01.json").unlink()
        with self.assertRaises(ContractError): publish(run / "skill", acceptance, self.ws / "install2")

    def test_baseline_cannot_authorize_candidate_publication(self):
        run = self.prepare_run(variant="none"); self.populate_fixture(run)
        write_json(run / "acceptance.json", report_run(run))
        candidate = next((self.ws / ".work/thinking-book/builds").glob("*/package/thinking-book"))
        with self.assertRaises(ContractError):
            publish(candidate, run / "acceptance.json", self.ws / "illegal-install")

    def test_program_compile_and_stale_gate_receipt(self):
        source_extra = (ROOT / "tests/fixtures/source-book.md").read_text()
        self.source.write_text(self.source.read_text() + "\n" + source_extra)
        evidence_path = self.book / "evidence/anchors.yaml"
        evidence = read_yaml(evidence_path); evidence["source"] = source_hashes(self.source)
        self.yaml(evidence_path, evidence)
        bundle_dir = self.book / ".cangjie/capabilities"
        shutil.copytree(ROOT / "tests/fixtures/books/demo-book/.cangjie/capabilities", bundle_dir)
        bundle = read_yaml(bundle_dir / "verified.yaml")
        bundle.update(schema_version=1, book={"title": "Synthetic tool", "source_pack": "fixture"},
            entry={"name": "synthetic-tool", "description": "Use this synthetic handbook to calculate totals and check the input units.",
                   "core_principles": ["Use source rules", "Check units", "Ask for missing inputs"],
                   "out_of_scope": ["Unknown tasks"], "stop_conditions": ["Missing inputs"]},
            router_entry={"name": "synthetic-tool", "description": "Route synthetic source tasks to the appropriate arithmetic or decision procedure."})
        for cap in bundle["capabilities"]:
            cap["promotion"] = {"destination": "router"}
            cap["also_read"] = []
        self.yaml(bundle_dir / "verified.yaml", bundle)
        (bundle_dir / "book").mkdir(exist_ok=True)
        (bundle_dir / "book/overview.md").write_text("# Synthetic overview\nSource fixture only.\n")
        (bundle_dir / "book/glossary.md").write_text("# Synthetic glossary\nTest terms.\n")
        model = read_yaml(self.modelpath); model["procedures"] = {"status": "bundle"}
        self.yaml(self.modelpath, model)
        self.approve_source_fixture()
        with self.assertRaises(ContractError): build_candidate(self.book, self.source, self.ws)
        shutil.copytree(ROOT / "tools", self.ws / "tools")
        (self.ws / ".dsh").mkdir()
        for script, extra in (("cangjie_to_dsh.py", ["--book-dir", str(self.book), "--source", str(self.source)]),
                              ("run_audit.py", [])):
            result = subprocess.run([sys.executable, str(ROOT / "bridge" / script),
                                     "--ws", str(self.ws), "--task", self.book.name, *extra], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        package = build_candidate(self.book, self.source, self.ws)
        self.assertTrue((package / "references/procedures/INDEX.md").is_file())
        self.assertFalse(list(package.rglob("ENTRY.md")))
        self.assertEqual(len(list(package.rglob("SKILL.md"))), 1)
        self.assertEqual((package / "references/procedures/resources/compound-patience.svg").read_bytes(),
                         (bundle_dir / "resources/compound-patience.svg").read_bytes())
        # Changing a card cannot reuse the old source review or passing gate receipt.
        card = bundle_dir / "cards/compound-patience.md"
        card.write_text(card.read_text() + "\nchanged\n")
        self.assertEqual(audit(self.book, self.source)["status"], "failed")
        self.approve_source_fixture()
        with self.assertRaises(ContractError): build_candidate(self.book, self.source, self.ws)


if __name__ == "__main__":
    unittest.main(verbosity=2)
