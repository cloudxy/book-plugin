# 蒸馏与编排调度（0.5）

适用新书籍/人物的可用试用 Skill、批量生产与续跑。正式作者分身、已有 book-skill/1、book-skill/2 及程序产物继续按原合同处理，不改标签迁移。

## 蒸馏

先按用户用途选择 knowledge / thought / narrative / expression，可组合。知识重原理、定义、条件和关系；思想重问题视角、依据、取舍与修正；叙事重视角、人物选择、因果及伏笔兑现；表达重材料组织、情绪和节奏。不要把文学强改为操作指南，也不要把知识书强改为作者口吻。全文处理所有已声明正文，分窗口读并接续未闭合论证；源文缺章/噪声要报告，不凭记忆填空。引用可选，来源单元由脚本定位。

人物材料先明确时期与范围，优先取得完整一手作品/信件/演讲。没有材料时通过可用搜索工具调研并保存实际正文、URL/版本、获取时间及来源角色，不能把搜索摘要或人物姓名当成已蒸馏 Skill。读入所登记材料的全文，来源有限就声明局部人物视角；保留时期差异、矛盾及他人评价与本人作品的区别。综合方法吸收 nuwa 的框架提取、适用条件、反模式及跨情境应用；不强造独特性或假装知道私人心理。

阶段指令见 [production-prompts.json](production-prompts.json)，由执行器按任务加载。阅读结果必须记录完整单元、发现、限制及未闭合关系；综合后，每个运行能力有适用条件、变化信号、来源单元和完整正例/变化例。知识和思想也可以服务写作，但实际写作编排留给下游项目。

## 初始化与执行

使用主技能的 `$PY/$PLUGIN/$WS` 路径。`$RUN` 通常为 `$WS/books/<slug>/pipeline`；状态存于 `state.json`，`STATUS.md` 只是投影，不覆盖旧 `PIPELINE_STATE.md`。

```bash
$PY "$PLUGIN/bridge/production.py" init --root "$RUN" \
  --source "$SRC" --id <slug> --title <标题> --object book \
  --period <版本或时期> --purpose <用途> --profile thought
```

人物用 `--object person`，`--source` 可多次传入；也可通过 Python `init` 给每个来源分别登记 role、period、URL 等元数据。先读现有状态，不重复 init。目标为正式分身时直接走旧合同，不以试用包替代。

有非交互执行器时，把明确的命令 argv 数组保存为私有 `worker.json`，例如 `["/工作区/.venv/bin/python", "/插件/bridge/host_worker.py"]`。附带的 worker 使用当前配置的 Codex CLI，每次为独立临时会话；无需新增模型 API 配置。其他宿主可实现同一 JSON 协议。

```bash
$PY "$PLUGIN/bridge/production.py" run --root "$RUN" --worker "$WORKER" --parallel 2
$PY "$PLUGIN/bridge/production.py" status --root "$RUN"
```

`run` 可重复传多个 `--root`，同一命令用于恢复。没有命令执行器时，当前宿主通过 claim/collect 完成语义任务，明确标为宿主协助模式，不称无人值守。

```bash
$PY "$PLUGIN/bridge/production.py" claim --root "$RUN" --owner <当前执行者>
$PY "$PLUGIN/bridge/production.py" collect --root "$RUN" --response <结果JSON>
```

claim 返回实际任务包及完整输入；响应含 task_id、claim_token、result、executor:{session_id,host,model}，usage 可记录实际用量，未知值不编造。按 instruction 返回 result，不能把任务包抄成结果。review 由未参与生成的独立会话执行。build 是确定性步骤，由 `run` 自动完成；宿主协助模式可调用 `distill_skill.build` 后 collect，不让模型虚构构建结果。

## 编排、预算与恢复

阅读单元 → 有界分组合并 → 用途综合 → 独立来源复核 → 单入口包。领取加锁和限额，租约过期可恢复；旧领取令牌不能覆盖新结果。各阶段的输入、指令版本和依赖输出决定复用条件。完整源文保存为不可变快照，审计回执仅证明实际输入/输出，不证明模型已理解。

原文变更后运行 `sync`，失效受影响的阅读单元及其下游；未变单元复用。复核失败最多在预算内定向重建综合结果。需要补某个阅读单元时使用 `retry --task <id> --feedback <具体缺口>`；修复后下游依赖重跑。所有尝试保留。包损坏隔离旧包并从有效材料重新构建，不覆写损坏证据。

默认并发2、每版本任务最多2次、100次语义调用；单次/总输入字符、超时及累计执行时间亦有限额。用 `init --policy <JSON>` 配置。达到限额保存断点并报告，不无限重试。字符预算不是 token/费用估算；各回执保存真实宿主用量，费用不明就保持未知。调整已有策略时明确记录状态文件 policy 的变化及理由，不能偷偷重置已耗预算。

## 实际运用、迁移和组合清单

构建结果为 `distilled-skill/1`，默认 `trial-unverified`。运行包只有入口、能力、范例及必要元数据；不包含试题、评分依据、完整书稿、会话或本机绝对路径。试用验收记录在包外，与内容哈希绑定；不能手改标签升级为 L3。

独立出题，保存 `production-eval/1` 的 cases：每例含 id、group、turns、rubric、targets（能力ID）、condition（normal/changed）、held_out。初始覆盖 direct/combine/changed/correction/deliver/boundary 六类；每项能力覆盖正常和变化，至少一个 changed 保留题。成文按用途可为解释/方案/作品，不一律评作者口吻。试题不得进入生成提示或运行包；看过的题只作开发与回归。

```bash
$PY "$PLUGIN/bridge/production_eval.py" prepare --candidate "$CANDIDATE" \
  --suite "$SUITE" --source-context "$SOURCE_CONTEXT" --run "$EVAL"
$PY "$PLUGIN/bridge/production_eval.py" run --run "$EVAL" --worker "$WORKER"
$PY "$PLUGIN/bridge/production_eval.py" report --run "$EVAL"
```

SOURCE_CONTEXT 为独立评审需要的原文及来源范围 JSON；答题者看不到。prepare 复制包到独立目录，执行器仅取得复制包内容与逐轮问题，保留完整答文及实际加载记录。多轮逐次交付，未来问题不提前透露。独立评审逐项核查来源、运用、交付，以真实答文片段说明理由。文件系统是否禁止访问原目录须按宿主实际能力说明；输入隔离不伪称操作系统隔离。需要无Skill对照时另开 `--variant none`，同题同配置；它不能授权发布候选。

```bash
$PY "$PLUGIN/bridge/skill_portfolio.py" register --ws "$WS" --package "$CANDIDATE" --evaluation "$EVAL"
$PY "$PLUGIN/bridge/skill_portfolio.py" export --ws "$WS" --out "$OUT"
$PY "$PLUGIN/bridge/skill_portfolio.py" verify "$OUT"
```

必交原被测包和 PORTFOLIO.json，含对象、用途、输入输出、版本/时期、依赖、已测条件及相对路径。整体复制即可迁移，book 不写 ncc 特定目录。替换用 `--replace` 保留快照；过期评测、缺文件或改变内容拒绝交付。

## 工作流改进

单次失败先定位阅读、综合、范例、入口或评审；只重做受影响节点。跨书出现的共同失误才成为通用指令候选。`workflow_optimizer.py propose` 用实际反馈提出至多一个阶段指令修改，输出私有 prompts.json；`production.py init --prompts` 可运行独立候选，`workflow_optimizer.py compare` 对比同来源/用途/题集/宿主条件的记录。优化器只提出候选，不自动改源文件或已发布包。

这是小规模反馈搜索工具，不声称完整实现 MIPRO/GEPA。开发来源与保留来源分开；候选在其他书未经验证时只保留局部结论。质量、墙钟、累计任务时间、实际 token 与人工干预分别报告，包含失败和优化调用，不承诺固定提速倍数。

方法依据：[nuwa](https://github.com/alchaincyf/nuwa-skill/blob/7c7edfeb9d90a28b1f79e7847e1ba27a698cdc24/SKILL.md) 的人物框架与跨情境验证；[GEPA](https://arxiv.org/abs/2507.19457) 的反馈驱动文本优化；实现为本仓适配，非上游效果认证。cangjie 及四闸继续负责适用程序，没有修改 vendor 源码。
