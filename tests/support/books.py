# -*- coding: utf-8 -*-
"""合成原文与定位条目构造（自 pipeline/production 合同测试提取）。"""
from __future__ import annotations

from pathlib import Path

from book_skill_common import digest


def synthetic_source(path, sections=30, repeat=12):
    """生成带节号的合成方法论文本；非真实书籍素材。"""
    parts = [f"第{i}节　" + f"这一节讨论领域{i}的方法论，主张{i}号命题，给出论证{i}与反例{i}的处理。" * repeat
             for i in range(1, sections + 1)]
    Path(path).write_text("\n".join(parts), encoding="utf-8")


def bucket_entry(index, src, kind="claim"):
    """构造覆盖第 index/10 十分位的合成定位条目；span 哈希来自传入原文。"""
    start = index * len(src) // 10 + 3
    end = start + 30
    return {"id": f"E{index:02d}", "kind": kind,
            "statement": f"合成命题{index}：来自桶{index}的重述，不复制原文。",
            "locator": f"合成第{index}节", "start": start, "end": end,
            "span_sha256": digest(src[start:end].encode()), "epistemic_status": "explicit"}


def dump_yaml(path, data):
    """按合同测试惯例写 YAML（保持键序、允许中文）。"""
    import yaml
    Path(path).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
