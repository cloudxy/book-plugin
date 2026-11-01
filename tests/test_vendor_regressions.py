"""Behavioral regressions for pinned vendor updates; no external requests."""
from pathlib import Path
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "vendor/cangjie-skill/scripts"
sys.path.insert(0, str(SCRIPTS))
from compile_single import build_tree
from impact_analysis import build_graph, analyze


class VendorRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-vendor-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bundle(self):
        bundle = {
            "schema_version": 1, "bundle_id": "synthetic", "promotion_budget": 8,
            "book": {"title": "Synthetic", "source_pack": "synthetic"},
            "entry": {"name": "synthetic", "description": "Compare a reversible plan with its conditions.",
                      "core_principles": ["Check the conditions"], "out_of_scope": [], "stop_conditions": []},
            "router_entry": {"name": "synthetic", "description": "Route a conditional plan."},
            "capabilities": [],
        }
        for slug, cid, neighbor in [("plan", "cap.synthetic.plan", "cap.synthetic.conditions"),
                                    ("conditions", "cap.synthetic.conditions", "plan")]:
            cap = {"capability_id": cid, "slug": slug, "title": slug, "revision": 1,
                   "importance": "high", "importance_rationale": "Synthetic conditional decision",
                   "status": "active", "intents": [slug], "one_liner": slug, "keywords": [slug],
                   "card": f"cards/{slug}.md", "also_read": [neighbor],
                   "promotion": {"destination": "reference"},
                   "source_evidence": [{"chunk_ids": ["changed-chunk"]}] if slug == "plan" else []}
            bundle["capabilities"].append(cap)
            path = self.root / cap["card"]
            path.parent.mkdir(exist_ok=True)
            path.write_text(f"# {slug}\nSynthetic condition check.\n")
        (self.root / "verified.yaml").write_text(yaml.safe_dump(bundle))
        return bundle

    def test_id_and_slug_supplementary_links_resolve(self):
        self.bundle()
        files = build_tree(self.root, "single")
        for slug in ("plan", "conditions"):
            target = f"references/capabilities/{slug}.md"
            self.assertIn(target, files)
            self.assertIn(target, files["SKILL.md"])
        self.assertNotIn("references/capabilities/cap.synthetic.", files["SKILL.md"])

    def test_id_and_slug_neighbors_reach_impact_analysis(self):
        self.bundle()
        graph = build_graph(self.root, None)
        edges = {(e["from"], e["to"]) for e in graph["edges"] if e["edge_type"] == "composes_with"}
        self.assertEqual(edges, {("cap.synthetic.plan", "cap.synthetic.conditions"),
                                 ("cap.synthetic.conditions", "cap.synthetic.plan")})
        report = analyze(graph, {"change_id": "change", "summary": {"added": 0, "removed": 0, "modified": 1},
                                 "changes": [{"chunk_id": "changed-chunk", "change_type": "modified"}]})
        self.assertIn("cap.synthetic.conditions", report.split("需一并回归的邻居能力", 1)[1])

    def test_missing_yaml_keeps_cli_and_doctor_reachable(self):
        command = [sys.executable, "-S", str(SCRIPTS / "cangjie.py")]
        help_result = subprocess.run(command + ["--help"], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        result = subprocess.run(command + ["doctor"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("pip install pyyaml", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_bootstrap_detects_importable_but_old_client(self):
        spec = importlib.util.spec_from_file_location("vendor_bootstrap", ROOT / "scripts/bootstrap.py")
        bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        module = self.root / "html_css_to_image.py"
        with patch.dict(os.environ, {"PYTHONPATH": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"}):
            module.write_text('__version__ = "0.3.0"\n')
            self.assertFalse(bootstrap.hci_matches(sys.executable))
            module.write_text(f'__version__ = {bootstrap.HCI_VERSION!r}\n')
            self.assertTrue(bootstrap.hci_matches(sys.executable))


if __name__ == "__main__":
    unittest.main()
