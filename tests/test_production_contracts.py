"""Synthetic contracts for production; these tests do not measure book quality."""
from pathlib import Path
import copy
import json
import shutil
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
sys.path.insert(0, str(ROOT / "tests"))
import production as p
import production_eval as ev
import production_stages as stages
import distill_skill as ds
import skill_portfolio as port
from production_common import atomic_json
from book_skill_common import ContractError, read_json
from support.production import drive, executor, legacy_result, model, result

SOURCE = "Synthetic source: conditions before conclusions. Reversible trials can inform action.\n" * 12


def suite_for(targets=("conditional",)):
    return {"schema_version": "production-eval/1",
            "cases": [{"id": g, "group": g,
                       "turns": ["Explain this uncertain choice."] + (["The choice is now irreversible."] if g == "correction" else []),
                       "rubric": "Synthetic review only.", "targets": list(targets),
                       "condition": "changed" if g == "changed" else "normal", "held_out": g == "changed"}
                      for g in sorted(ev.GROUPS)]}


def review(config, score=2, failures=(), attribution=()):
    return {"result": {"dimensions": {d: {"score": score, "reason": "Synthetic evidence.", "excerpt": "Specify the conditions"}
                                      for d in config["dimensions"]},
                       "hard_failures": list(failures), "attribution": list(attribution)}}


class ProductionBase(unittest.TestCase):
    profiles = ["knowledge"]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="production-contract-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.root = self.ws / "pipeline"
        self.src = self.ws / "source.txt"
        self.src.write_text(SOURCE)
        self.product = {"id": "synthetic", "object": "book", "title": "Synthetic", "period": "v1",
                        "purpose": "Contract tests", "profiles": list(self.profiles)}
        p.init(self.root, [{"path": str(self.src), "role": "synthetic", "period": "v1"}],
               self.product, {"chunk_chars": 200, "merge_fanout": 2})

    def finish(self, respond=result):
        drive(p, self.root, respond)
        return p.status(self.root)

    def evaluated(self, loading="inline"):
        built = self.finish()
        candidate = self.root / built["package"]
        suite = suite_for()
        path = self.ws / "suite.json"
        atomic_json(path, suite)
        run = self.ws / "evaluation"
        config = ev.prepare(candidate, path, run, {"text": self.src.read_text()}, loading=loading, production=self.root)
        self.assertEqual(ev.report(run)["status"], "pending")
        for case in suite["cases"]:
            for i in range(len(case["turns"])):
                ev.collect_answer(run, case["id"], i,
                                  {"result": {"answer": "Specify the conditions before drawing a conclusion."},
                                   "executor": {**executor(case["id"] + str(i)), "observed_reads": ["SKILL.md", "references/abilities.md"]}})
            ev.collect_review(run, case["id"], {**review(config), "executor": executor("review-" + case["id"])})
        self.assertEqual(ev.report(run)["status"], "passed")
        return candidate, run, suite


class ProductionContracts(ProductionBase):
    def test_complete_read_ranges_and_no_semantic_claim(self):
        state = p.read_state(self.root)
        ranges = sorted((u["start"], u["end"]) for u in state["units"].values())
        self.assertEqual(ranges[0][0], 0)
        self.assertEqual(ranges[-1][1], len(self.src.read_text()))
        self.assertTrue(all(a[1] == b[0] for a, b in zip(ranges, ranges[1:])))
        self.assertEqual(p.status(self.root)["status"], "pending")

    def test_deterministic_steps_never_reach_the_host(self):
        seen = drive(p, self.root)
        self.assertFalse(set(seen) & {"build", "audit", "ledger"})
        self.assertIn("audit-part", seen)
        status = p.status(self.root)
        self.assertEqual(status["status"], "built-pending-runtime")
        self.assertEqual(status["lifecycle"]["stage"], "built")
        self.assertTrue((self.root / "l1/ledger.json").is_file())

    def test_claim_cap_and_expired_results(self):
        a = p.claim(self.root, "a")
        b = p.claim(self.root, "b")
        self.assertIsNone(p.claim(self.root, "c"))
        state = p.read_state(self.root)
        state["tasks"][a["task_id"]]["lease"]["until"] = time.time() - 1
        p.save(self.root, state)
        c = p.claim(self.root, "c", a["task_id"])
        with self.assertRaises(ContractError):
            p.collect(self.root, a["task_id"], a["claim_token"], result(a), executor("old"))
        p.collect(self.root, c["task_id"], c["claim_token"], result(c), executor("new"))

    def test_late_result_accepted_when_lease_not_reclaimed(self):
        a = p.claim(self.root, "a")
        state = p.read_state(self.root)
        state["tasks"][a["task_id"]]["lease"]["until"] = time.time() - 1  # machine slept past the lease
        p.save(self.root, state)
        p.collect(self.root, a["task_id"], a["claim_token"], result(a), executor("late"))
        self.assertEqual(p.read_state(self.root)["tasks"][a["task_id"]]["status"], "done")

    def test_failure_budget_and_resume(self):
        a = p.claim(self.root, "a")
        p.collect(self.root, a["task_id"], a["claim_token"], {}, executor("fail"), error="transient")
        b = p.claim(self.root, "b", a["task_id"])
        self.assertEqual(b["attempt"], 2)
        p.collect(self.root, b["task_id"], b["claim_token"], result(b), executor("ok"))
        self.assertEqual(self.finish()["status"], "built-pending-runtime")

    def test_transient_failure_backs_off_without_spending_attempts(self):
        a = p.claim(self.root, "a")
        p.collect(self.root, a["task_id"], a["claim_token"], {}, executor("x"), error="worker exited 1",
                  detail="ERROR: Selected model is at capacity")
        self.assertIsNone(p.claim(self.root, "b", a["task_id"]))
        status = p.status(self.root)
        self.assertEqual(status["backoff"][0]["task_id"], a["task_id"])
        state = p.read_state(self.root)
        self.assertEqual(state["tasks"][a["task_id"]]["error_class"], "transient")
        for _ in range(3):  # more transient failures than max_attempts, still within the transient budget
            state = p.read_state(self.root)
            state["tasks"][a["task_id"]]["not_before"] = 0
            p.save(self.root, state)
            again = p.claim(self.root, "b", a["task_id"])
            p.collect(self.root, again["task_id"], again["claim_token"], {}, executor("y"), error="503 overloaded")
        state = p.read_state(self.root)
        state["tasks"][a["task_id"]]["not_before"] = 0
        p.save(self.root, state)
        final = p.claim(self.root, "b", a["task_id"])
        self.assertEqual(final["attempt"], 5)
        events = [e for e in p.read_state(self.root)["events"] if e.get("type") == "attempt" and e["task_id"] == a["task_id"]]
        self.assertEqual({e["class"] for e in events}, {"transient"})

    def test_changed_source_reuses_unaffected_units(self):
        self.finish()
        self.src.write_text(self.src.read_text().replace("Synthetic", "Xynthetic", 1))
        self.assertEqual(p.status(self.root)["status"], "stale-source")
        p.sync(self.root)
        state = p.read_state(self.root)
        reads = [t for t in state["tasks"].values() if t["kind"] == "read"]
        self.assertEqual(sum(t["status"] == "stale" for t in reads), 1)
        self.assertTrue(any(t["status"] == "done" for t in reads))
        self.assertEqual(state["tasks"]["build"]["status"], "stale")
        self.assertTrue(any(e.get("type") == "cache" and e["reused"] > 0 for e in state["events"]))

    def test_stage_tamper_propagates_in_one_status(self):
        self.finish()
        state = p.read_state(self.root)
        t = next(t for t in state["tasks"].values() if t["kind"] == "read")
        path = self.root / t["output"]
        data = read_json(path)
        data["result"]["findings"] = "Changed"
        atomic_json(path, data)
        self.assertEqual(p.status(self.root)["tasks"]["build"]["status"], "stale")

    def test_workflow_version_change_keeps_cache(self):
        self.finish()
        saved = p.VERSION
        try:
            p.VERSION = "9.9.9"
            state = p.status(self.root)
        finally:
            p.VERSION = saved
        self.assertTrue(all(t["status"] == "done" for t in state["tasks"].values()))

    def test_module_change_invalidates_only_its_stage_and_downstream(self):
        self.finish()
        modules = read_json(stages.MODULES)
        modules["modules"]["synthesize"]["instruction"] += " Explicit change."
        modules["modules"]["synthesize"]["version"] = "synthesize/2+test"
        path = self.ws / "modules.json"
        atomic_json(path, modules)
        state = p.read_state(self.root)
        state["prompts"] = str(path)
        p.save(self.root, state)
        state = p.status(self.root)
        self.assertTrue(all(t["status"] == "done" for t in state["tasks"].values() if t["kind"] in {"read", "merge", "audit-part"}))
        self.assertEqual(state["tasks"]["synthesize"]["status"], "stale")
        self.assertEqual(state["tasks"]["build"]["status"], "stale")

    def test_corrupt_package_quarantined_and_rebuilt(self):
        built = self.finish()
        entry = self.root / built["package"] / "SKILL.md"
        entry.write_text("corrupt")
        self.assertEqual(self.finish()["status"], "built-pending-runtime")
        self.assertTrue(list((self.root / "quarantine").iterdir()))
        ds.verify(self.root / p.status(self.root)["package"])

    def test_source_review_requires_other_session(self):
        while (a := p.claim(self.root, "test")):
            if a["stage"] == "review":
                break
            name = "auditor" if a["stage"] == "audit-part" else "generator"
            p.collect(self.root, a["task_id"], a["claim_token"], result(a), executor(name))
        out = p.collect(self.root, a["task_id"], a["claim_token"], result(a), executor("generator"))
        self.assertIn("independent", out["error"])

    def test_audit_requires_session_independent_of_readers(self):
        while (a := p.claim(self.root, "test")):
            if a["stage"] == "audit-part":
                break
            p.collect(self.root, a["task_id"], a["claim_token"], result(a), executor("reader"))
        out = p.collect(self.root, a["task_id"], a["claim_token"], result(a), executor("reader"))
        self.assertIn("independent", out["error"])

    def test_budget_stops_without_false_completion(self):
        state = p.read_state(self.root)
        state["policy"]["max_calls"] = 1
        p.save(self.root, state)
        a = p.claim(self.root, "a")
        p.collect(self.root, a["task_id"], a["claim_token"], result(a), executor("a"))
        self.assertIsNone(p.claim(self.root, "b"))
        status = p.status(self.root)
        self.assertIn("budget", status["stop_reason"])
        self.assertTrue(status["forecast"]["shortfall"])

    def test_oversized_review_is_split_and_aggregated_by_script(self):
        state = p.read_state(self.root)
        state["policy"]["part_input_chars"] = 3000
        state["policy"]["max_input_chars"] = 5000
        p.save(self.root, state)
        seen = drive(p, self.root)
        state = p.read_state(self.root)
        parts = [tid for tid, t in state["tasks"].items() if t["kind"] == "review-part"]
        self.assertGreaterEqual(len(parts), 2)
        self.assertNotIn("review", seen)
        self.assertEqual(state["tasks"]["review"]["mode"], "python")
        covered = sorted(u for tid in parts for u in state["tasks"][tid]["items"])
        self.assertEqual(covered, sorted(state["units"]))
        self.assertEqual(p.status(self.root)["status"], "built-pending-runtime")

    def test_host_size_rejection_reshards_review(self):
        while (a := p.claim(self.root, "test")):
            if a["stage"] == "review":
                break
            p.collect(self.root, a["task_id"], a["claim_token"], result(a), executor(a["claim_token"]))
        size = len(json.dumps({k: v for k, v in a.items() if k not in {"claim_token", "input_hash", "attempt"}}, ensure_ascii=False))
        p.collect(self.root, a["task_id"], a["claim_token"], {}, executor("r"), error="worker exited 1",
                  detail='{"error": {"code": "input_too_large"}}')
        state = p.read_state(self.root)
        self.assertLess(state["host_limits"]["max_input_chars"], size)
        self.assertTrue(any(e.get("type") == "repair" and e["origin"] == "orchestration" for e in state["events"]))
        self.assertEqual(state["tasks"]["review"]["mode"], "python")
        self.assertEqual(self.finish()["status"], "built-pending-runtime")

    def test_review_repairs_route_to_read_units(self):
        target = None
        def respond(packet):
            nonlocal target
            if packet["stage"] == "review" and target is None:
                target = sorted(p.read_state(self.root)["units"])[1]
                body = result(packet)
                body["verdict"] = "fail"
                body["decisions"]["conditional"] = {"verdict": "fail", "reason": "qualifier missing in unit"}
                body["repairs"] = [{"stage": "read", "targets": [target], "problem": "keep the reversibility qualifier"}]
                return body
            return result(packet)
        while (a := p.claim(self.root, "test")):
            p.collect(self.root, a["task_id"], a["claim_token"], respond(a), executor(a["claim_token"]))
            if target:
                break
        state = p.read_state(self.root)
        self.assertEqual(state["tasks"][target]["status"], "stale")
        self.assertEqual(state["tasks"][target]["feedback"]["origin"], "review")
        self.assertEqual(state["tasks"]["synthesize"]["status"], "stale")
        others = [u for u in state["units"] if u != target]
        self.assertTrue(all(state["tasks"][u]["status"] == "done" for u in others))
        repair = [e for e in state["events"] if e.get("type") == "repair"][-1]
        self.assertEqual(repair["routes"][0], {"stage": "read", "targets": [target], "problem": "keep the reversibility qualifier"})
        self.assertEqual(self.finish()["status"], "built-pending-runtime")

    def test_repair_rounds_are_bounded_then_isolated(self):
        def failing(packet):
            body = result(packet)
            if packet["stage"] == "review":
                body["verdict"] = "fail"
                body["issues"] = ["synthetic persistent issue"]
                body["repairs"] = [{"stage": "synthesize", "targets": ["conditional"], "problem": "persistent"}]
            return body
        status = self.finish(failing)
        self.assertEqual(status["status"], "blocked")
        blocked = status["lifecycle"]["blocked"][0]
        self.assertEqual((blocked["task_id"], blocked["class"]), ("review", "repair-budget"))
        self.assertEqual(p.read_state(self.root)["repairs"]["review"], 2)
        p.policy_set(self.root, {"max_repair_rounds": 3}, "allow one more targeted round")
        self.assertEqual(p.read_state(self.root)["tasks"]["synthesize"]["status"], "stale")
        self.assertEqual(self.finish()["status"], "built-pending-runtime")
        kinds = [e["kind"] for e in p.read_state(self.root)["events"] if e.get("type") == "intervention"]
        self.assertEqual(kinds, ["policy"])

    def test_policy_changes_are_recorded_and_never_reset_usage(self):
        a = p.claim(self.root, "a")
        p.collect(self.root, a["task_id"], a["claim_token"], result(a), executor("a"))
        before = p.read_state(self.root)["usage"]
        p.policy_set(self.root, {"max_calls": 50}, "bigger book than default")
        state = p.read_state(self.root)
        self.assertEqual(state["usage"], before)
        self.assertEqual(state["events"][-1]["changes"], {"max_calls": [100, 50]})
        for bad in ({"chunk_chars": 300}, {"bogus": 1}, {"lease_seconds": 10}):
            with self.assertRaises(ContractError):
                p.policy_set(self.root, bad, "should fail")

    def test_future_turn_and_rubric_hidden(self):
        candidate, run, suite = self.evaluated()
        packet = ev.answer_packet(run, "correction", 0)
        self.assertEqual(len(packet["conversation"]), 1)
        self.assertNotIn("rubric", packet)
        self.assertNotIn("irreversible", json.dumps(packet))

    def test_reviewer_independence_needs_generation_sessions(self):
        built = self.finish()
        atomic_json(self.ws / "suite.json", suite_for())
        with self.assertRaises(ContractError):
            ev.prepare(self.root / built["package"], self.ws / "suite.json", self.ws / "e1", {"text": SOURCE})
        config = ev.prepare(self.root / built["package"], self.ws / "suite.json", self.ws / "e2", {"text": SOURCE}, production=self.root)
        state = p.read_state(self.root)
        synth = read_json(self.root / state["tasks"]["synthesize"]["output"])["executor"]["session_id"]
        self.assertIn(synth, config["generation_sessions"])

    def test_knowledge_purpose_does_not_test_author_dimensions(self):
        candidate, run, _ = self.evaluated()
        config = read_json(run / "config.json")
        self.assertEqual(config["dimensions"], ["application", "fidelity", "utility"])
        self.assertEqual(set(config["not_applicable"]), {"cognition", "expression"})

    def test_failed_case_requires_stage_attribution(self):
        built = self.finish()
        atomic_json(self.ws / "suite.json", suite_for())
        run = self.ws / "e"
        config = ev.prepare(self.root / built["package"], self.ws / "suite.json", run, {"text": SOURCE}, production=self.root)
        ev.collect_answer(run, "direct", 0, {"result": {"answer": "Specify the conditions first."}, "executor": executor("ans")})
        with self.assertRaises(ContractError):
            ev.collect_review(run, "direct", {**review(config, score=1), "executor": executor("rev")})
        bad = review(config, score=1, attribution=[{"stage": "read", "capabilities": ["invented"], "problem": "x", "evidence": "y"}])
        with self.assertRaises(ContractError):
            ev.collect_review(run, "direct", {**bad, "executor": executor("rev")})
        good = review(config, score=1, attribution=[{"stage": "read", "capabilities": ["conditional"], "problem": "qualifier lost", "evidence": "Specify the conditions"}])
        ev.collect_review(run, "direct", {**good, "executor": executor("rev")})
        self.assertEqual(ev.report(run)["attributions"]["direct"][0]["stage"], "read")

    def test_host_loading_records_discovery(self):
        candidate, run, suite = self.evaluated(loading="host")
        packet = ev.answer_packet(run, "direct", 0)
        self.assertNotIn("skill", packet)
        self.assertEqual(packet["skill_dir"], "relocated/skill")
        accepted = ev.report(run)
        self.assertEqual(accepted["host_load"]["entry_loaded"], accepted["host_load"]["answers"])
        run2 = self.ws / "evaluation-unloaded"
        config = ev.prepare(candidate, self.ws / "suite.json", run2, {"text": SOURCE}, loading="host", production=self.root)
        ev.collect_answer(run2, "direct", 0, {"result": {"answer": "Specify the conditions first."},
                                              "executor": {**executor("a"), "observed_reads": []}})
        ev.collect_review(run2, "direct", {**review(config), "executor": executor("r")})
        accepted = ev.report(run2)
        self.assertEqual(accepted["status"], "failed")
        self.assertEqual(accepted["attributions"]["direct"][0]["stage"], "build")

    def test_valid_score_edit_cannot_promote(self):
        candidate, run, _ = self.evaluated()
        path = run / "reviews/direct.json"
        data = read_json(path)
        data["result"]["dimensions"]["utility"]["score"] = 3
        atomic_json(path, data)
        with self.assertRaises(ContractError):
            ev.report(run)
        with self.assertRaises(ContractError):
            port.register(self.ws, candidate, run)

    def test_target_and_host_tamper_rejected(self):
        candidate, run, _ = self.evaluated()
        config = read_json(run / "config.json")
        for field, value in (("targets", []), ("dimensions", ["fidelity"])):
            edited = copy.deepcopy(config)
            edited[field] = value
            atomic_json(run / "config.json", edited)
            with self.assertRaises(ContractError):
                ev.report(run)
        atomic_json(run / "config.json", config)
        atomic_json(run / "answers/unknown/0.json", {"executor": executor("fake")})
        with self.assertRaises(ContractError):
            ev.report(run)

    def test_portable_export_and_metadata_tamper(self):
        candidate, run, _ = self.evaluated()
        port.register(self.ws, candidate, run)
        port.plan(self.ws, "some-person", "person", "Synthetic person", "materials not yet gathered")
        out = self.ws / "export"
        port.export(self.ws, out)
        shutil.move(self.root, self.ws / "unavailable")
        shutil.move(run, self.ws / "eval-unavailable")
        manifest = port.verify_portfolio(out)
        self.assertEqual(manifest["counts"], {"usable_skills": 1, "pending": 1})
        entry = manifest["entries"][0]
        self.assertEqual(entry["trigger"], "Use for reversible choices with uncertain evidence.")
        self.assertEqual(entry["inputs"], ["The user's facts and the decision at hand"])
        self.assertEqual(entry["package"]["schema_version"], "distilled-skill/2")
        self.assertEqual(entry["verified"]["loading"], "inline")
        for field, value in (("outputs", ["invented"]), ("trigger", "invented"), ("capabilities", [])):
            data = read_json(out / "PORTFOLIO.json")
            data["entries"][0][field] = value
            atomic_json(out / "PORTFOLIO.json", data)
            with self.assertRaises(ContractError):
                port.verify_portfolio(out)
            atomic_json(out / "PORTFOLIO.json", manifest)
        data = read_json(out / "PORTFOLIO.json")
        data["pending"][0]["path"] = "skills/some-person"
        atomic_json(out / "PORTFOLIO.json", data)
        with self.assertRaises(ContractError):
            port.verify_portfolio(out)

    def test_empty_sources_and_identity_leak(self):
        self.finish()
        with self.assertRaises(ContractError):
            ev.clean_sources({})
        self.assertEqual(ev.clean_sources({"text": "source", "executor": {"session": "secret"}}),
                         {"documents": [{"text": "source"}]})

    def test_optimizer_binds_evaluation_to_production_build(self):
        import workflow_optimizer as opt
        candidate, run, _ = self.evaluated()
        self.assertTrue(opt.compare(self.root, self.root, run, run, "development")["quality_nonregression"])
        config = read_json(run / "config.json")
        config["variant"] = "none"
        atomic_json(run / "config.json", config)
        with self.assertRaises(ContractError):
            opt.compare(self.root, self.root, run, run, "development")

    def test_worker_schema_requires_example_origin(self):
        import worker_schema as ws
        schema = ws.for_packet({"stage": "synthesize"})
        example = schema["properties"]["examples"]["items"]
        self.assertIn("origin", example["required"])
        self.assertFalse(example["additionalProperties"])
        schema = ws.for_packet({"stage": "review",
                                "inputs": {"synthesize": {"capabilities": [{"id": "one"}], "examples": [{"id": "two"}]}}})
        self.assertEqual(set(schema["properties"]["decisions"]["required"]), {"one", "two"})

    def test_worker_schema_follows_stage_contracts(self):
        import worker_schema as ws
        packets = {}
        while (a := p.claim(self.root, "test")):
            packets.setdefault(a["stage"], a)
            p.collect(self.root, a["task_id"], a["claim_token"], result(a), executor(a["claim_token"]))
        read = ws.for_packet(packets["read"])
        self.assertIn("principle", read["properties"]["entries"]["items"]["properties"]["type"]["enum"])
        self.assertIn("risk_flags", read["required"])
        synth = ws.for_packet(packets["synthesize"])
        self.assertEqual(synth["properties"]["schema_version"]["enum"], ["distilled-capability/2"])
        self.assertIn("voice", synth["properties"]["capabilities"]["items"]["required"])
        self.assertNotIn("profile", synth["properties"])
        self.assertIn("repairs", ws.for_packet(packets["review"])["required"])
        audit = ws.for_packet(packets["audit-part"])
        self.assertEqual(set(audit["properties"]["decisions"]["required"]), set(packets["audit-part"]["items"]))

    def test_packets_carry_stage_contract_and_selected_templates(self):
        packet = p.claim(self.root, "test")
        self.assertEqual(packet["module"]["version"], "read/2")
        self.assertEqual(set(packet["module"]["contract"]), {"inputs", "outputs", "source_range", "depends_on", "executor",
                                                             "tools", "budget", "failure_return"})
        self.assertTrue(packet["module"]["examples"] and packet["module"]["failure_handling"])
        self.assertEqual(set(packet["templates"]["genres"]), {"science"})
        self.assertEqual(set(packet["templates"]["profiles"]), {"knowledge"})


class PurposeAssets(unittest.TestCase):
    units = ["s001-u0001", "s001-u0002"]

    def test_thought_requires_episodes_and_habits(self):
        data = model(self.units, ("thought",))
        ds.validate_model(data, self.units, ["thought"])
        for field in ("episodes", "habits"):
            broken = copy.deepcopy(data)
            broken[field] = []
            with self.assertRaises(ContractError):
                ds.validate_model(broken, self.units, ["thought"])

    def test_expression_requires_profile_and_knowledge_rejects_it(self):
        data = model(self.units, ("expression",))
        ds.validate_model(data, self.units, ["expression"])
        broken = copy.deepcopy(data)
        del broken["profile"]
        with self.assertRaises(ContractError):
            ds.validate_model(broken, self.units, ["expression"])
        with self.assertRaises(ContractError):
            ds.validate_model(data, self.units, ["knowledge"])

    def test_voice_and_reality_boundaries_required(self):
        data = model(self.units)
        for field, value in (("voice", None), ("reality", "verified-fact")):
            broken = copy.deepcopy(data)
            broken["capabilities"][0][field] = value
            with self.assertRaises(ContractError):
                ds.validate_model(broken, self.units, ["knowledge"])

    def test_legacy_model_keeps_original_contract(self):
        ds.validate_model(model(self.units, v2=False), self.units)

    def test_nonportable_paths_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for value in ("C:\\Users\\me\\x", "/tmp/run/x", "/Volumes/disk/x", "/opt/tool", "file:///etc"):
                (root / "SKILL.md").write_text(f"see {value}\n")
                with self.assertRaises(ContractError, msg=value):
                    ds.check_links(root, ["SKILL.md"])
            (root / "SKILL.md").write_text("see https://example.com/a and ratio 1:2\n")
            ds.check_links(root, ["SKILL.md"])


class ThoughtPackage(ProductionBase):
    profiles = ["thought"]

    def test_thought_package_ships_episodes_and_habits(self):
        built = self.finish()
        package = self.root / built["package"]
        manifest = ds.verify(package)
        self.assertEqual(manifest["assets"], ["references/abilities.md", "references/episodes.md",
                                              "references/examples.md", "references/habits.md"])
        self.assertIn("references/episodes.md", (package / "SKILL.md").read_text())

    def test_thought_purpose_scores_author_cognition(self):
        candidate, run, _ = self.evaluated()
        config = read_json(run / "config.json")
        self.assertIn("cognition", config["dimensions"])
        self.assertNotIn("cognition", config["not_applicable"])


class LegacyRunCompatibility(unittest.TestCase):
    """A run started under 0.5.0 keeps its verified cache, packets and instructions."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="production-legacy-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.root = self.ws / "pipeline"
        (self.ws / "source.txt").write_text(SOURCE)
        product = {"id": "legacy", "object": "book", "title": "Legacy", "period": "v1", "purpose": "Compat", "profiles": ["knowledge"]}
        p.init(self.root, [{"path": str(self.ws / "source.txt"), "role": "synthetic", "period": "v1"}],
               product, {"chunk_chars": 200, "merge_fanout": 2}, prompts=p.PROMPTS)
        seen = drive(p, self.root, legacy_result)
        self.assertNotIn("audit-part", seen)
        state = p.read_state(self.root)
        for tid in p.dependency_order(state["tasks"]):  # rewrite as the 0.5.0 scheduler recorded them
            if state["tasks"][tid].get("input_hash"):
                state["tasks"][tid]["input_hash"] = p.legacy_fingerprint(self.root, state, tid)
        del state["fingerprint_scheme"]
        del state["intake"]
        atomic_json(self.root / "state.json", state)

    def test_verified_cache_survives_migration(self):
        status = p.status(self.root)
        self.assertEqual(status["status"], "built-pending-runtime")
        self.assertTrue(all(t["status"] == "done" for t in status["tasks"].values()))
        migration = [e for e in p.read_state(self.root)["events"] if e.get("type") == "migration"]
        self.assertEqual(migration[0]["unverified"], 0)
        self.assertGreater(migration[0]["verified"], 0)

    def test_unverifiable_cache_entry_is_recomputed(self):
        state = read_json(self.root / "state.json")
        uid = sorted(state["units"])[0]
        state["tasks"][uid]["input_hash"] = "0" * 64
        atomic_json(self.root / "state.json", state)
        status = p.status(self.root)
        self.assertEqual(status["tasks"][uid]["status"], "stale")
        self.assertEqual(status["tasks"]["build"]["status"], "stale")

    def test_legacy_packets_keep_flat_instructions(self):
        state = p.read_state(self.root)
        uid = sorted(state["units"])[0]
        self.assertEqual(stages.packet(self.root, state, uid)["instruction"], read_json(p.PROMPTS)["read"])
        self.assertNotIn("output_contract", stages.packet(self.root, state, uid))

    def test_engine_hash_excludes_new_line_modules(self):
        from book_skill_common import LEGACY_ENGINE
        self.assertFalse({n for n in LEGACY_ENGINE if n.startswith(("production", "distill", "skill_portfolio", "workflow", "host_worker"))})
        self.assertTrue(all((ROOT / "bridge" / n).is_file() for n in LEGACY_ENGINE))


if __name__ == "__main__":
    unittest.main()
