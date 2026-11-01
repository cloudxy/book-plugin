---
description: "按用途蒸馏书籍/人物 Skill，编排全文阅读、综合、复核与实测，交付可迁移原包和组合清单；支持批量、续跑及正式分身。"
argument-hint: "[拆 <书名/路径> | 蒸馏 <路径> | 继续 | status | <任意蒸馏意图>]"
skills: book-workflow
---

先完整读取本命令真实路径（解析软链后）相邻的 `../skills/book-workflow/SKILL.md`，按其中的路径约定定位插件根并自举工作区。

Follow the `book-workflow` skill in **mode: auto**（新书籍/人物任务按用途进入0.5生产线，交付实际可用试用Skill及组合清单；正式作者分身与已有任务保留book-skill/2等原合同；v1不自动升格，程序single/pack选择沿用；只审计走/book-audit）。status/继续先识别pipeline/state.json或旧状态，不要求旧书补写档位。Preserve this mode while interpreting the arguments. 若宿主未替换下方占位符，以用户本次输入作为参数。

$ARGUMENTS
