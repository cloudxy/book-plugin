"""多书产线状态汇总与下一步派单。

并行由多个会话/子代理各领一本书执行；本脚本只读状态、不写作业：
每本书报告档位、L1/L2 产物与闸门状态，并给出下一步动作卡。
档位从 PIPELINE_STATE.md 的「档位: L1|L2|L3」行读取；未登记者提示先登记。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from book_skill_common import read_json, slug, write_json


def read_tier(state_path):
    import re
    if not state_path.is_file():
        return None
    match = re.search(r"^档位:\s*(L[123])\s*$", state_path.read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else None


def book_state(ws, book):
    if (book / "pipeline/state.json").is_file():
        from production import status as production_status
        current = production_status(book / "pipeline")
        return {"slug": book.name, "tier": current.get("lifecycle", {}).get("target_tier", "L2"), "l1_started": True,
                "l1_gates": "not-used", "l2_started": "package" in current, "source_gates": current["status"],
                "lifecycle": current.get("lifecycle", {}).get("stage"), "production": current}
    task = slug(book.name)
    check_path = Path(ws) / ".work" / task / "l1-check.json"
    audit_path = Path(ws) / ".work" / task / "thinking-audit.json"
    return {"slug": task, "tier": read_tier(book / "PIPELINE_STATE.md"),
            "l1_started": (book / "l1/material.yaml").is_file(),
            "l1_gates": read_json(check_path).get("status") if check_path.is_file() else None,
            "l2_started": (book / "thinking/model.yaml").is_file(),
            "source_gates": read_json(audit_path).get("status") if audit_path.is_file() else None}


def next_action(state):
    if "production" in state:
        current = state["production"]
        if current["status"] == "stale-source":
            return "production.py sync 后续跑，旧包保留"
        if current["status"] == "built-pending-runtime":
            return "production.py evaluate/cycle：实际运行并独立评审；失败按归因定向返修"
        if current["status"] == "tested-trial":
            return "production.py deliver：登记并导出被测原包及组合清单"
        if current["status"] == "delivered":
            return "已交付试用 Skill；production.py record 生成分项交付记录"
        if current["status"] == "material-ready":
            return "L1 材料就绪（不是 Skill）；需要 Skill 时以 L2 目标新建产线"
        if current["status"] == "blocked":
            return "已隔离缺口：" + "; ".join(b["reason"] for b in current["lifecycle"]["blocked"])[:200]
        waiting = [b["task_id"] for b in current.get("backoff", [])]
        return "production.py run/resume：" + ", ".join(current.get("ready", []) + [f"{t}(退避中)" for t in waiting])
    if state["tier"] is None:
        return "保留原任务合同；新产线用 production.py init 登记档位/对象，不修改旧状态"
    if not state["l1_started"]:
        return "L1 init：bridge/l1_extract.py init --title --author --kind"
    if state["l1_gates"] != "passed":
        return "L1 抽取并过闸：登记定位条目后 bridge/l1_extract.py check"
    if state["tier"] == "L1":
        return "L1 仅完成原型结构检查；新线须产出实际 Skill，再用 skill_portfolio.py register"
    if not state["l2_started"]:
        return "L2 重建：按 SKILL.md 整书流程；L1 素材与覆盖底账直接复用"
    if state["source_gates"] != "passed":
        return "L2/L3 来源闸：bridge/thinking_audit.py ＋ 独立语义复核"
    return "验收/发布：按 references/evaluate-and-publish.md（L3 含用户口吻审阅）"


def status(ws, tier=None, slugs=None):
    books = []
    root = Path(ws) / "books"
    if root.is_dir():
        for book in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "portfolio"):
            state = book_state(ws, book)
            if slugs and state["slug"] not in slugs:
                continue
            if tier and state["tier"] != tier:
                continue
            state["next"] = next_action(state)
            books.append(state)
    return books


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ws", required=True, type=Path)
    ap.add_argument("--tier", choices=("L1", "L2", "L3"))
    ap.add_argument("--slug", action="append", help="只看指定书，可多次")
    args = ap.parse_args()
    books = status(args.ws, args.tier, args.slug)
    for state in books:
        print(f"{state['slug']:<24} 档位={state['tier'] or '?'}  L1闸={state['l1_gates'] or '-'}  "
              f"来源闸={state['source_gates'] or '-'}  下一步: {state['next']}")
    if not books:
        print("（无匹配的书目录）")
    path = Path(args.ws) / ".work" / "batch-status.json"
    write_json(path, books)
    print(f"— {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
