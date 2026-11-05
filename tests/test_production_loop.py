"""Synthetic contracts for the single-book loop, intake, sampling, tiers and productivity records.

A fake command worker stands in for the host; nothing here measures book quality.
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
sys.path.insert(0, str(ROOT / "tests"))
import production as p
import production_eval as ev
import production_loop as loop
import production_metrics as metrics
import production_stages as stages
import skill_portfolio as port
from production_common import atomic_json
from book_skill_common import ContractError, read_json
from support.production import drive, executor, result

SOURCE = "Synthetic source: conditions before conclusions. Reversible trials can inform action.\n" * 12

FAKE_WORKER = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from support.production import result
control = Path(sys.argv[2])
packet = json.load(sys.stdin)
key = packet.get("task_id")
if key == "s001-u0001" and not (control / ("seen-" + key)).exists():
    (control / ("seen-" + key)).write_text("1")
    sys.stderr.write("ERROR: Selected model is at capacity. Please try again.")
    raise SystemExit(1)
if "stage" in packet:
    body = result(packet)
elif "conversation" in packet:
    body = {"answer": "Specify the conditions before drawing a conclusion."}
else:
    fail = (control / "fail-correction").exists() and any("irreversible" in t for t in packet["turns"])
    if fail:
        (control / "fail-correction").unlink()
    body = {"dimensions": {d: {"score": 1 if fail else 2, "reason": "synthetic", "excerpt": "Specify the conditions"}
                           for d in packet["dimensions"]},
            "hard_failures": [], "attribution": [{"stage": "read", "capabilities": ["conditional"],
                                                  "problem": "reversibility qualifier lost", "evidence": "Specify the conditions"}] if fail else []}
calls = control / "calls"
calls.write_text(str(int(calls.read_text()) + 1 if calls.exists() else 1))
print(json.dumps({"result": body, "executor": {"host": "fake-cli", "model": "none", "session_id": __import__("uuid").uuid4().hex},
                  "usage": {"input_tokens": 10, "output_tokens": 5}}))
'''


def suite():
    return {"schema_version": "production-eval/1",
            "cases": [{"id": g, "group": g,
                       "turns": ["Explain this uncertain choice."] + (["The choice is now irreversible."] if g == "correction" else []),
                       "rubric": "Synthetic review only.", "targets": ["conditional"],
                       "condition": "changed" if g == "changed" else "normal", "held_out": g == "changed"}
                      for g in sorted(ev.GROUPS)]}


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="production-loop-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.src = self.ws / "source.txt"
        self.src.write_text(SOURCE)
        self.product = {"id": "synthetic", "object": "book", "title": "Synthetic", "period": "v1",
                        "purpose": "Loop tests", "profiles": ["knowledge"]}

    def init(self, name="pipeline", tier="L2", policy=None, text=None, sources=None):
        root = self.ws / name
        if text is not None:
            self.src.write_text(text)
        p.init(root, sources or [{"path": str(self.src), "role": "synthetic", "period": "v1"}], dict(self.product),
               {"chunk_chars": 200, "merge_fanout": 2, "backoff_seconds": 1, "backoff_max_seconds": 2, **(policy or {})},
               target_tier=tier)
        return root

    def worker(self):
        control = self.ws / "control"
        control.mkdir(exist_ok=True)
        script = self.ws / "fake_worker.py"
        script.write_text(FAKE_WORKER)
        return [sys.executable, "-B", str(script), str(ROOT / "tests"), str(control)], control


class SingleBookLoop(Workspace):
    def test_cycle_attributes_repairs_confirms_and_delivers(self):
        root = self.init()
        command, control = self.worker()
        (control / "fail-correction").write_text("1")
        atomic_json(self.ws / "suite.json", suite())
        outcome = loop.cycle(root, self.ws / "suite.json", {"text": SOURCE}, command, max_rounds=2, parallel=2)
        self.assertEqual(outcome["status"], "passed")
        self.assertEqual([r["evaluation"] for r in outcome["rounds"]], ["failed", "passed"])
        self.assertEqual(outcome["rounds"][0]["repair"], "repair-scheduled")
        state = p.read_state(root)
        attribution = state["attributions"][0]
        self.assertEqual((attribution["routed_to"], attribution["status"]), ("read", "confirmed-by-rerun"))
        self.assertEqual(len({e["run"] for e in state["evaluations"]}), 2)
        reread = [e for e in state["events"] if e.get("type") == "attempt" and e.get("cause") == "repair"]
        self.assertTrue(reread and all(e["kind"] in {"read", "synthesize"} for e in reread))
        self.assertEqual(p.status(root)["status"], "tested-trial")
        delivered = loop.deliver(root, self.ws, self.ws / "portfolio")
        self.assertEqual(delivered["entries"], 1)
        self.assertEqual(p.status(root)["lifecycle"]["stage"], "delivered")
        log = self.ws / "e2e.log"
        log.write_text("Ran 5 tests in 0.1s\n\nOK\n")
        record = loop.record(root, log, self.ws / "portfolio")
        self.assertEqual(set(record["items"]), {"code_implemented", "contract_regression", "skill_usable_in_scope", "portfolio_usable",
                                                "relocated_run_passed", "productivity_observed", "l3_accepted"})
        self.assertEqual(record["items"]["skill_usable_in_scope"]["status"], "passed")
        self.assertEqual(record["items"]["portfolio_usable"]["status"], "passed")
        self.assertEqual(record["items"]["contract_regression"]["status"], "passed")
        self.assertEqual(record["items"]["productivity_observed"]["status"], "not-observed")
        self.assertEqual(record["items"]["l3_accepted"]["status"], "not-applicable")
        m = metrics.metrics(root)
        self.assertEqual(m["interventions"]["count"], 0)
        self.assertEqual(m["automatic_repairs"]["by_origin"], {"evaluation": 1})
        self.assertIsNotNone(m["first_usable_skill_seconds"])
        self.assertIsNotNone(m["wall_seconds_recorded"])
        self.assertGreater(m["tokens"]["input_tokens"], 0)
        self.assertGreater(m["evaluation"]["calls"], 0)
        self.assertEqual(m["failure_classes"].get("transient"), 1)
        self.assertIn("retry-after-transient", m["repeated_calls"])

    def test_held_out_failures_are_not_fed_back_silently(self):
        root = self.init()
        built = drive(p, root) and p.status(root)
        atomic_json(self.ws / "suite.json", suite())
        run = self.ws / "e1"
        config = ev.prepare(self.ws / "pipeline" / built["package"], self.ws / "suite.json", run, {"text": SOURCE}, production=root)
        for case in suite()["cases"]:
            for i in range(len(case["turns"])):
                ev.collect_answer(run, case["id"], i, {"result": {"answer": "Specify the conditions first."}, "executor": executor(f"a{case['id']}{i}")})
            fail = case["held_out"]
            dims = {d: {"score": 1 if fail else 2, "reason": "r", "excerpt": "Specify the conditions"} for d in config["dimensions"]}
            attribution = [{"stage": "synthesize", "capabilities": ["conditional"], "problem": "p", "evidence": "e"}] if fail else []
            ev.collect_review(run, case["id"], {"result": {"dimensions": dims, "hard_failures": [], "attribution": attribution},
                                                "executor": executor("r" + case["id"])})
        loop.attach(root, run)
        self.assertEqual(loop.repair_from_evaluation(root, run)["status"], "held-out-only-failures")
        self.assertEqual(loop.repair_from_evaluation(root, run, use_held_out=True)["status"], "repair-scheduled")
        state = p.read_state(root)
        self.assertIn("changed", state["consumed_held_out"])
        self.assertEqual([e["kind"] for e in state["events"] if e.get("type") == "intervention"], ["held-out-feedback"])
        drive(p, root)
        with self.assertRaises(ContractError):
            loop.evaluate(root, self.ws / "suite.json", {"text": SOURCE})

    def test_evaluation_must_bind_current_build(self):
        root = self.init()
        built = drive(p, root) and p.status(root)
        atomic_json(self.ws / "suite.json", suite())
        run = self.ws / "e"
        ev.prepare(root / built["package"], self.ws / "suite.json", run, {"text": SOURCE}, production=root)
        self.product["id"] = "other"
        other = self.init("other")
        drive(p, other)
        with self.assertRaises(ContractError):
            loop.attach(other, run)


class IntakeAndTiers(Workspace):
    def test_body_boundary_excludes_front_matter_and_maps_positions(self):
        text = ("Front matter, publisher notes.\n" * 3 + "第一章 起点\n" + "Body line about conditions.\n" * 8 + "[p. 7]\n"
                + "第二章 转折\n" + "More body text on reversible trials �.\n" * 8 + "附录 notes\n" + "Appendix.\n" * 3)
        self.src.write_text(text)
        root = self.ws / "pipeline"
        p.init(root, [{"path": str(self.src), "role": "primary-text", "period": "v1", "declared_issues": ["translator notes inline"],
                       "body": {"start_marker": "第一章", "end_marker": "附录"}}], dict(self.product), {"chunk_chars": 200, "merge_fanout": 2})
        state = p.read_state(root)
        source = state["sources"][0]
        start, end = text.index("第一章"), text.index("附录")
        self.assertEqual([r[:2] for r in source["excluded"]], [[0, start], [end, len(text)]])
        self.assertEqual(min(u["start"] for u in state["units"].values()), start)
        self.assertEqual(max(u["end"] for u in state["units"].values()), end)
        self.assertIn("translator notes inline", source["issues"])
        self.assertTrue(any("replacement" in i for i in source["issues"]))
        last = state["units"][sorted(state["units"])[-1]]["locator"]
        self.assertIn("第二章 转折", last["headings"])
        self.assertEqual(last["page"], 7)
        first = state["units"][sorted(state["units"])[0]]["locator"]
        self.assertEqual(first["lines"][0], 4)

    def test_person_sources_keep_provenance_roles(self):
        self.product.update(object="person", id="person-x", title="Person X")
        other = self.ws / "letters.txt"
        other.write_text("A later biographer interprets the letters.\n" * 4)
        with self.assertRaises(ContractError):
            p.init(self.ws / "bad", [{"path": str(self.src), "role": "primary-text", "period": "1900s"}], dict(self.product))
        manifest = self.ws / "sources.json"
        atomic_json(manifest, [{"path": "source.txt", "role": "self-account", "period": "1901-1905", "access": "full text"},
                               {"path": "letters.txt", "role": "later-interpretation", "period": "1950", "url": "https://example.org/b"}])
        import subprocess
        out = subprocess.run([sys.executable, "-B", str(ROOT / "bridge/production.py"), "init", "--root", str(self.ws / "person"),
                              "--sources", str(manifest), "--id", "person-x", "--title", "Person X", "--object", "person",
                              "--period", "1901-1950", "--purpose", "method", "--profile", "thought"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        state = p.read_state(self.ws / "person")
        self.assertEqual([s["role"] for s in state["sources"]], ["self-account", "later-interpretation"])
        packet = p.claim(self.ws / "person", "t")
        self.assertIn("person_voices", packet["templates"])

    def test_l1_target_stops_at_material_and_l3_is_refused(self):
        root = self.init(tier="L1")
        seen = drive(p, root)
        self.assertFalse({"synthesize", "review"} & set(seen))
        status = p.status(root)
        self.assertEqual(status["status"], "material-ready")
        ledger = read_json(root / "l1/ledger.json")
        self.assertEqual(len(ledger["units"]), len(p.read_state(root)["units"]))
        self.assertTrue((root / "l1/entries.jsonl").read_text().strip())
        self.assertEqual(ledger["audit"]["verdict"], "pass")
        self.assertEqual(loop.record(root)["items"]["skill_usable_in_scope"]["status"], "not-applicable")
        with self.assertRaises(ContractError):
            p.init(self.ws / "l3", [{"path": str(self.src), "role": "x", "period": "v1"}], dict(self.product), target_tier="L3")


class SampledAudit(Workspace):
    def test_sample_is_stratified_seeded_and_adds_risk_flags(self):
        root = self.init(text="Unit text about conditions and reversible trials, line.\n" * 160,
                         policy={"merge_fanout": 6, "max_calls": 400, "max_total_input_chars": 10 ** 8})
        flagged = set()
        def respond(packet):
            body = result(packet)
            if packet["stage"] == "read" and packet["task_id"] in {"s001-u0003", "s001-u0004"}:
                body["risk_flags"] = ["numbers-units"]
                flagged.add(packet["task_id"])
            return body
        drive(p, root, respond)
        state = p.read_state(root)
        n = len(state["units"])
        sample = state["audit"]["sample"]
        self.assertEqual(sample["k"], min(n, max(10, -(-n // 10))))
        units = list(state["units"])
        deciles = {int(10 * units.index(u) / n) for u in sample["base"]}
        self.assertEqual(len(deciles), min(10, sample["k"]))
        self.assertTrue(flagged - set(sample["base"]) <= set(sample["flagged"]))
        self.assertEqual(stages.select_sample(root, state)["base"], sample["base"])
        audited = sorted(u for t in state["tasks"].values() if t["kind"] == "audit-part" for u in t["items"])
        self.assertEqual(audited, sorted(sample["base"] + sample["flagged"]))

    def test_audit_failure_rereads_unit_and_expands_neighbours(self):
        root = self.init()
        target = "s001-u0003"
        failed = []
        def respond(packet):
            body = result(packet)
            if packet["stage"] == "audit-part" and target in packet["items"] and not failed:
                failed.append(target)
                body["decisions"][target] = {"verdict": "fail", "problems": ["qualifier"], "reason": "reversibility limit dropped"}
            return body
        drive(p, root, respond)
        state = p.read_state(root)
        self.assertEqual(state["repairs"]["audit"], 1)
        self.assertEqual(state["audit"]["expanded"], ["s001-u0002", "s001-u0003", "s001-u0004"])
        rereads = [e for e in state["events"] if e.get("type") == "attempt" and e["task_id"] == target]
        self.assertEqual([e.get("cause", "initial") for e in rereads][-1], "repair")
        self.assertEqual(p.status(root)["status"], "built-pending-runtime")

    def test_persistent_audit_gap_is_isolated_until_accepted(self):
        root = self.init()
        target = "s001-u0002"
        def respond(packet):
            body = result(packet)
            if packet["stage"] == "audit-part" and target in packet["items"]:
                body["decisions"][target] = {"verdict": "fail", "problems": ["voice"], "reason": "quoted view kept as author claim"}
            return body
        drive(p, root, respond)
        status = p.status(root)
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(status["lifecycle"]["blocked"][0]["gaps"], [target])
        self.assertNotEqual(status["tasks"]["synthesize"]["status"], "done")
        p.unblock(root, "audit", "declare the unit as a known gap in limits", accept_gaps=True)
        seen = []
        def capture(packet):
            seen.append(packet)
            return respond(packet)
        drive(p, root, capture)
        synth = next(x for x in seen if x["stage"] == "synthesize")
        self.assertEqual(synth["audit"]["gaps"], [target])
        self.assertEqual(synth["audit"]["verdict"], "pass-with-gaps")
        self.assertEqual(p.status(root)["status"], "built-pending-runtime")
        self.assertEqual(metrics.metrics(root)["interventions"]["by_kind"], {"accept-gaps": 1})


class Scheduling(Workspace):
    def test_runner_waits_out_backoff_and_counts_runs(self):
        root = self.init()
        command, control = self.worker()
        outcome = p.run([root], command, parallel=2)
        self.assertEqual(outcome["runs"][0]["status"], "built-pending-runtime")
        state = p.read_state(root)
        self.assertTrue(all(t["status"] == "done" for t in state["tasks"].values()))
        self.assertEqual([e["type"] for e in state["events"] if e.get("type") == "run"], ["run"])
        failures = metrics.failures(root)
        self.assertTrue(any(i["class"] == "transient" and i["stage"] == "read" for i in failures["items"]))

    def test_productivity_comparison_requires_same_scope(self):
        a = self.init("a")
        drive(p, a)
        b = self.init("b")
        drive(p, b)
        compared = metrics.compare(a, b)
        self.assertEqual(compared["status"], "observation-only")
        self.product["profiles"] = ["thought"]
        c = self.init("c")
        with self.assertRaises(ContractError):
            metrics.compare(a, c)


if __name__ == "__main__":
    unittest.main()
