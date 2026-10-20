---
description: "按 svg-diagram 房规为能力卡/DIGEST 手绘 SVG 图：CJK 字体栈、语义配色、盒距与曲线连线纪律，画完过 svg-lint（error 清零）。"
argument-hint: "[<能力卡/能力名> | <图类型: 流程|架构|时序|数据流|生命周期> | <描述>]"
skills: book-workflow
---

先完整读取本命令真实路径（解析软链后）相邻的 `../skills/book-workflow/SKILL.md`，按其中的路径约定定位插件根并自举工作区。

Follow the `book-workflow` skill, **只执行阶段 1.5（出图）**：先读 `$PLUGIN/vendor/svg-diagram/SKILL.md` 房规再画，落位与 lint 纪律照技能定义。本命令只产 SVG。栅格 HTML 出图不是本命令，见 book-workflow 里可选的 html-css-to-image；没有密钥就不调用，也不拿它替代图件闸。Preserve this scope while interpreting the arguments. 若宿主未替换下方占位符，以用户本次输入作为参数。

$ARGUMENTS
