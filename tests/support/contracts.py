# -*- coding: utf-8 -*-
"""合成来源评审记录：模拟独立评审员通过全部核查项。

仅用于合同测试的结构性放行，不是任何真实书籍或人物的语义验收。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bridge"))

from book_skill_common import write_json  # noqa: E402
from thinking_audit import validate  # noqa: E402


def approve_source(book, source, reviewer="synthetic-test-reviewer",
                   rationale="synthetic structural test oracle, not a real semantic review"):
    """写入合成 source-review.json（结构放行记录，断言留给调用方）。"""
    result = validate(Path(book), Path(source))
    record = {"input_sha256": result["input_sha256"], "reviewer": reviewer,
              "independent": True,
              "checks": {key: {"status": "passed", "rationale": rationale} for key in result["checks"]}}
    write_json(Path(book) / "eval/source-review.json", record)
    return record
