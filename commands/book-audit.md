---
description: "独立审计已有 cangjie 蒸馏产物：桥接逐字回源 → 四闸判态（池覆盖/锚一致/证据闭包/图件）→ 放行 compile 或按映射表回炉。不重新蒸馏。"
argument-hint: "[--task <slug> | <书目录路径> | <原文路径>]"
skills: book-workflow
---

先完整读取本命令真实路径（解析软链后）相邻的 `../skills/book-workflow/SKILL.md`，按其中的路径约定定位插件根并自举工作区。

Follow the `book-workflow` skill, **只执行阶段二、三、四**（桥接 → 四闸审计 → 判态）：跳过蒸馏与出图，对已存在的 `books/<slug>/` 产物做回源核验与判态收口。Preserve this scope while interpreting the arguments. 若宿主未替换下方占位符，以用户本次输入作为参数。

$ARGUMENTS
