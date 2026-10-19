---
description: "知识蒸馏主入口：拆书生成 Skill → 出图 → 四闸回源审计 → 判态放行/回炉的完整闭环。没文本会先要原文，审计全绿前不编译交付。"
argument-hint: "[拆 <书名/路径> | 蒸馏 <路径> | 继续 | status | <任意蒸馏意图>]"
skills: book-workflow
---

先完整读取本命令真实路径（解析软链后）相邻的 `../skills/book-workflow/SKILL.md`，按其中的路径约定定位插件根并自举工作区。

Follow the `book-workflow` skill in **mode: auto**（按用户意图路由到对应阶段：新书从阶段一起步，已有产物则从断点续跑，只审计走 /book-audit）。Preserve this mode while interpreting the arguments. 若宿主未替换下方占位符，以用户本次输入作为参数。

$ARGUMENTS
