---
description: "审计已有思想、叙事或程序产物：逐字与语义来源核查、适用程序四闸、候选完整性及已有回答验收记录。缺失项标待完成，不重新蒸馏。"
argument-hint: "[--task <slug> | <书目录路径> | <原文路径>]"
skills: book-workflow
---

先完整读取本命令真实路径（解析软链后）相邻的 `../skills/book-workflow/SKILL.md`，按其中的路径约定定位插件根并自举工作区。

Follow the `book-workflow` skill, **只核查已有材料与记录，并按所属合同检查适用项**：有 thinking/model.yaml 则检查思想、叙事和范例来源及独立复核；有 Bundle 则桥接与四闸；已有候选/回答记录则校验完整性并重新 report。正式作者分身缺少思想、语义评审、实际回答或用户口吻审阅时如实记缺口；0.5知识试用包按用途核查，不强加作者口吻条件。不生成内容、不代答、不安装。只有程序的旧任务按程序版判态，不能写成整书思想已通过。Preserve this scope while interpreting the arguments. 若宿主未替换下方占位符，以用户本次输入作为参数。

$ARGUMENTS

有 `pipeline/state.json` 的0.5任务：用 `production.py status` 核查输入/依赖状态、生命周期与阻塞缺口（status 只刷新不执行），`production.py metrics/failures` 查看产能与按阶段归类的失败，`distill_skill.py <包路径>` 核查包，已有评测用 `production_eval.py report --run <评测目录>`；组合包用 `skill_portfolio.py verify <目录>`。只检查已有结果，不调用run、claim或自动修复。待阅读、待语义复核、待实测分别列出，机器字段通过不改称语义通过。
