# 文档

`docs/` 解释这个仓库。它不加载为技能，也不代替 `skills/book-workflow/SKILL.md` 的运行合同。现行流程以技能、`commands/`、`bridge/` 和 `vendor/` 为准。

目录按用途分。设计方案放 `designs/<模块>/`，不按日期或工具名分。

| 要找什么 | 入口 |
|---|---|
| 已批准并执行中的作者分身：隐藏习惯、视角、路径与文风 | [作者分身升级方案](designs/author-persona/upgrade.md) |
| 0.3.0 第三轮方案：现有问题、思想推演、叙事口吻与实施顺序 | [升级方案](designs/judgment/upgrade.md) |
| 具体预期：新问题、条件变化、叙事解释、简答与入口正文 | [完整问答示例](designs/judgment/examples.md) |
| 验证增益：陌生任务、检索基线、反事实、盲评与消融 | [验收方法](designs/judgment/methodology.md) |
| 运行核心、完整范例、表达规格与程序调用的构建边界 | [运行及产物规格](designs/judgment/runtime.md) |

0.3.0 已接入思想与叙事编排、自有来源核查、候选构建、实际回答记录及发布限制。运行时以 [主技能](../skills/book-workflow/SKILL.md) 及其 references 为准；本目录保留设计理由与方法。先看升级方案和完整问答示例，再看验收与实现细节。真实书籍的完成状态按各自私有记录判定，不能由插件版本推定。

| 实现与验证记录 | 入口 |
|---|---|
| 0.4.0 新合同、兼容与验证范围 | [作者分身合同记录](releases/0.4.0.md) |
| 0.3.0 代码、回归与试点范围 | [升级交付记录](releases/0.3.0.md) |
