# -*- coding: utf-8 -*-
"""覆盖映射合同：tests/COVERAGE.md 必须与 bridge/ 目录逐模块对齐。

正向：bridge 里每个模块都被登记（有属主或显式不测理由）。
反向：表里不得登记 bridge 中不存在的模块（防改名后留尸）。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "tests" / "COVERAGE.md"


class CoverageMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = MAP.read_text(encoding="utf-8")
        cls.registered = set(re.findall(r"^\| `([A-Za-z0-9_]+\.py)`", cls.text, re.M))
        cls.bridge = {p.name for p in (ROOT / "bridge").glob("*.py")}

    def test_every_bridge_module_is_registered(self):
        self.assertEqual(sorted(self.bridge - self.registered), [],
                         "bridge/ 存在未登记模块：请在 tests/COVERAGE.md 给出属主测试或不测理由")

    def test_map_only_names_real_bridge_modules(self):
        self.assertEqual(sorted(self.registered - self.bridge), [],
                         "COVERAGE.md 登记了 bridge/ 中不存在的模块（改名后未同步？）")

    def test_registered_owners_exist(self):
        owners = set(re.findall(r"^\| `[A-Za-z0-9_]+\.py` \| ([^|]+)\|", self.text, re.M))
        missing = []
        for cell in owners:
            for name in re.findall(r"test_[a-z_0-9]+", cell):
                if not (ROOT / "tests" / f"{name}.py").is_file():
                    missing.append(name)
        self.assertEqual(sorted(set(missing)), [], "COVERAGE.md 引用了不存在的属主测试文件")


if __name__ == "__main__":
    unittest.main()
