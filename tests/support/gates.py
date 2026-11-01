# -*- coding: utf-8 -*-
"""闸门集成测试的临时工作区装配（不改 dsh 源码的进程级隔离模式）。

依据 tools/_paths.py 的解析优先级：DSH_DISTILL_ROOT / DSH_WORKSPACE_ROOT
环境变量最优先。bridge/run_audit.py 对 --ws 的实现即此模式。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def prepare_gate_ws(ws, repo_root):
    """把闸门运行件装配进临时工作区：tools/（dsh 判闸件）+ .dsh/ 占位。"""
    ws = Path(ws)
    ws.mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path(repo_root) / "tools", ws / "tools")
    (ws / ".dsh").mkdir(exist_ok=True)
    return ws


def gate_env(ws, base=None):
    """直调 tools/ 判闸件所需环境：根定向到临时 ws + 压上游 SyntaxWarning 噪音。"""
    env = dict(base if base is not None else os.environ,
               DSH_DISTILL_ROOT=str(ws), DSH_WORKSPACE_ROOT=str(ws),
               PYTHONWARNINGS="ignore::SyntaxWarning")
    return env
