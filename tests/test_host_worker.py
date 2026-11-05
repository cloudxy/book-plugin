# -*- coding: utf-8 -*-
"""host_worker 信封合同：用假 codex 可执行件注入 PATH，全程无真实 CLI/网络。

被测不变量：packet 经 stdin 进、结果/executor/usage JSON 经 stdout 出；
schema 只在有结构化合同时附带；CLI 失败必须非零退出。
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_WORKER = ROOT / "bridge" / "host_worker.py"

FAKE_CODEX = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 假 codex CLI：按 mode 控制文件回放事件，并记录收到的参数。
import json, os, sys
argv = sys.argv[1:]
here = os.path.dirname(os.path.abspath(__file__))
record = {"argv": argv, "schema_attached": "--output-schema" in argv, "schema": None}
if record["schema_attached"]:
    i = argv.index("--output-schema")
    record["schema"] = json.loads(open(argv[i + 1], encoding="utf-8").read())
json.dump(record, open(os.path.join(here, "argv-record.json"), "w", encoding="utf-8"))
mode = open(os.path.join(here, "mode"), encoding="utf-8").read().strip()
if mode == "fail":
    sys.stderr.write("synthetic CLI failure")
    raise SystemExit(3)
target = argv[argv.index("--output-last-message") + 1]
project = argv[argv.index("--cd") + 1]
record["project_files"] = sorted(os.path.relpath(os.path.join(r, f), project) for r, _, fs in os.walk(project) for f in fs)
record["prompt"] = sys.stdin.read()
json.dump(record, open(os.path.join(here, "argv-record.json"), "w", encoding="utf-8"))
open(target, "w", encoding="utf-8").write(json.dumps(
    {"covered_units": ["u1"], "findings": "synthetic observation",
     "limitations": [], "open_connections": []}))
print("not-json-noise")
print(json.dumps({"type": "thread.started", "thread_id": "th-syn-1"}))
if mode == "host":
    print(json.dumps({"type": "item.completed", "item": {"type": "command_execution",
          "command": "bash -lc 'cat .agents/skills/demo/SKILL.md && cat .agents/skills/demo/references/abilities.md'"}}))
else:
    print(json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}))
print(json.dumps({"type": "turn.completed", "usage": {"total_tokens": 42}}))
'''


class HostWorkerEnvelope(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="book-host-worker-test-")
        self.addCleanup(self.temp.cleanup)
        self.ws = Path(self.temp.name)
        self.bin = self.ws / "bin"
        self.bin.mkdir()
        fake = self.bin / "codex"
        fake.write_text(FAKE_CODEX, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}")

    def set_mode(self, mode):
        (self.bin / "mode").write_text(mode, encoding="utf-8")

    def run_worker(self, packet):
        return subprocess.run([sys.executable, "-B", str(HOST_WORKER)],
                              input=json.dumps(packet, ensure_ascii=False), text=True,
                              capture_output=True, env=self.env)

    def record(self):
        return json.loads((self.bin / "argv-record.json").read_text(encoding="utf-8"))

    def test_synthesize_packet_attaches_schema_and_parses_events(self):
        self.set_mode("ok")
        result = self.run_worker({"stage": "synthesize", "source_units": ["u1"]})
        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["result"]["findings"], "synthetic observation")
        self.assertEqual(envelope["executor"]["host"], "codex-cli")
        self.assertEqual(envelope["executor"]["session_id"], "th-syn-1")
        self.assertEqual(envelope["executor"]["observed_tool_events"], ["command_execution"])
        self.assertEqual(envelope["usage"], {"total_tokens": 42})
        self.assertTrue(envelope["executor"]["structured_output"])
        record = self.record()
        self.assertTrue(record["schema_attached"])
        self.assertIn("examples", record["schema"]["properties"])   # synthesize 合同含 examples

    def test_host_loading_installs_skill_without_inlining_it(self):
        self.set_mode("host")
        skill = self.ws / "run" / "relocated" / "skill"
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: demo\n---\nSECRET-INLINE-MARKER", encoding="utf-8")
        (skill / "references" / "abilities.md").write_text("abilities", encoding="utf-8")
        packet = {"loading": "host", "skill_dir": "relocated/skill", "skill_name": "demo", "instruction": "answer",
                  "conversation": [{"role": "user", "content": "question"}]}
        result = subprocess.run([sys.executable, "-B", str(HOST_WORKER)], input=json.dumps(packet), text=True,
                                capture_output=True, env=self.env, cwd=self.ws / "run")
        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["executor"]["observed_reads"], ["SKILL.md", "references/abilities.md"])
        record = self.record()
        self.assertIn(".agents/skills/demo/SKILL.md", record["project_files"])
        self.assertNotIn("SECRET-INLINE-MARKER", record["prompt"])
        self.assertNotIn("relocated/skill", record["prompt"])

    def test_unknown_stage_sends_no_schema(self):
        self.set_mode("ok")
        result = self.run_worker({"stage": "unstructured"})
        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertFalse(envelope["executor"]["structured_output"])
        self.assertFalse(self.record()["schema_attached"])

    def test_cli_failure_exits_nonzero_without_envelope(self):
        self.set_mode("fail")
        result = self.run_worker({"stage": "read"})
        self.assertEqual(result.returncode, 3)          # 透传 CLI 退出码
        self.assertNotIn('"result"', result.stdout)


if __name__ == "__main__":
    unittest.main()
