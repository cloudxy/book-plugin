# 蒸馏与编排调度（0.5）

适用新书籍/人物的可用试用 Skill、批量生产与续跑。正式作者分身、已有 book-skill/1、book-skill/2 及程序产物继续按原合同处理，不改标签迁移。

## 蒸馏

先按用户用途选择 knowledge / thought / narrative / expression，可组合；再按材料选体裁模板 argument（论说/思想）/ narrative（文学/叙事）/ serial（网文/连载）/ poetry（诗词/韵文）/ science（科学/专业及其他领域知识），可多选，未指定时按用途取默认。模板决定阅读阶段提取的对象类型和必守边界，混合材料可按来源分别登记体裁。不要把文学强改为操作指南，也不要把知识书强改为作者口吻。

全文处理所有已声明正文：正文边界用 `--body-start/--body-end` 声明，边界外内容记入排除范围；OCR、缺页、附录、译注等问题用 `--issue` 登记，替换字符等可检出问题自动记录。每个单元自动生成回到行号、章节标题、页码或时间码的定位，逐字摘引可选。分窗口读并接续未闭合论证；源文缺章/噪声要报告，不凭记忆填空。

人物材料先明确时期与范围，优先取得完整一手作品/信件/演讲。用 `--sources <清单.json>` 逐份登记 path、role、period 及可选 url、access、retrieved_at；人物来源的 role 必须是 self-account（自述）、work（作品）、others-account（他人评价）或 later-interpretation（后世解释）。没有材料时通过可用搜索工具调研并保存实际正文，不能把搜索摘要或人物姓名当成已蒸馏 Skill。读入所登记材料的全文，来源有限就声明局部人物视角；保留时期差异、矛盾及他人评价与本人作品的区别。

### 阶段模块

阶段模块定义在 [production-modules.json](production-modules.json)。每个模块声明输入、输出合同、来源范围、前置依赖、执行者能力、工具、预算和失败退回目标，并带原创合成范例和失败处理规则。任务包只装载本阶段的模块、所选模板和依赖闭包。一次运行在 init 时固定所用模块集，之后修改仓内文件不会静默改变它；改用新模块集要显式指定。

| 模块 | 输出 | 说明 |
|---|---|---|
| read | read/2 | 按模板产出类型条目（type/voice/status/reality）、发现、风险标记、限制和待接读关系 |
| merge | merge/2 | 汇合下级发现，保留冲突与声音差异 |
| audit-part → audit | audit/1 | 由独立会话分层抽查阅读结果，脚本汇总；失败的单元定向重读，并扩大到相邻单元 |
| ledger | L1 材料 | 由脚本生成 overview、阅读底账、类型条目和抽样回执；它们是中间材料，不算 Skill |
| synthesize | distilled-capability/2 | 每项能力写明声音与材料边界；按用途补资产：思想用途补 episodes 与 habits，表达用途补 PROFILE |
| review / review-part | review/2 | 独立来源复核；超出预算时自动分批，由脚本汇总；问题按 repairs 退回对应阶段 |
| build | distilled-skill/2 | 由脚本构建单入口包，用途资产随包附带 |

用 `--prompts <0.5.0 扁平指令文件>` 启动或已在 0.5.0 开跑的任务继续使用旧指令与旧结果合同，缺少的分批复核模块取自当前模块集。

## 初始化与执行

使用主技能的 `$PY/$PLUGIN/$WS` 路径。`$RUN` 通常为 `$WS/books/<slug>/pipeline`；状态存于 `state.json`，`STATUS.md` 只是投影，不覆盖旧 `PIPELINE_STATE.md`。

```bash
$PY "$PLUGIN/bridge/production.py" init --root "$RUN" \
  --source "$SRC" --id <slug> --title <标题> --object book \
  --period <版本或时期> --purpose <用途> --profile thought \
  [--genre argument] [--edition <版本>] [--translator <译者>] \
  [--body-start <正文首句>] [--body-end <正文后首句>] [--target-tier L2] [--host command]
```

`--target-tier` 取 L1 或 L2：L1 停在内部材料，L2 一直推进到可迁移的试用 Skill。L3 一律拒绝，正式验收继续走旧路线。init 之前先读取现有状态，不重复初始化。

有非交互执行器时，把明确的命令 argv 数组保存为私有 `worker.json`，例如 `["/工作区/.venv/bin/python", "/插件/bridge/host_worker.py"]`。附带的 worker 使用当前配置的 Codex CLI，每次调用都开独立的临时会话，不需要另配模型 API。其他宿主可实现同一 JSON 协议。

```bash
$PY "$PLUGIN/bridge/production.py" run --root "$RUN" --worker "$WORKER" --parallel 2
$PY "$PLUGIN/bridge/production.py" status --root "$RUN"
```

`run` 可重复传多个 `--root`，同一命令也用于恢复。没有命令执行器时，当前宿主通过 claim/collect 完成语义任务，明确标为宿主协助模式，不称无人值守。确定性步骤（抽查汇总、底账、分批复核汇总、构建）在 claim 或 collect 时由脚本自动完成，不会交给宿主，也不要求宿主手动调用；status 只刷新状态，不执行任务。

```bash
$PY "$PLUGIN/bridge/production.py" claim --root "$RUN" --owner <当前执行者>
$PY "$PLUGIN/bridge/production.py" collect --root "$RUN" --response <结果JSON>
```

claim 返回实际任务包及完整输入。响应须含 task_id、claim_token、result、executor:{session_id,host,model}；usage 记录实际用量，未知值不编造。按 instruction 和 output_contract 返回 result，不能把任务包抄成结果。抽查与复核必须由未参与生成的独立会话执行。

## 编排、预算与恢复

缓存键由任务输入、依赖输出、该阶段模块和所选模板决定，不包含调度器源码或全局版本号。只修改代码不会让已完成的阅读失效。0.5.0 留下的缓存键先用旧算法逐项核对，核对一致才换成新键；核对不上的重新计算，迁移结果写入事件。

失败按类别处理：
- **暂时性错误**（容量不足、限流、5xx、连接问题、租约过期）：按指数退避重试，不消耗语义尝试次数，`run` 会等退避期结束再继续。
- **超时**：消耗尝试次数。
- **超出宿主输入上限**：复核或抽查类任务会自动降低已知上限并重新分批；阅读、综合类任务则阻塞并说明原因。
- **合同不符**：消耗尝试次数。

调用跨过机器休眠时，按墙钟截止时间结束；结果回来时，只要租约没被别人重新领取就照常收下，被重新领取的迟到结果私存，不覆盖新结果，运行器也不会因此退出。

默认并发 2，每个输入版本最多 2 次语义尝试，暂时性错误最多重试 6 次，100 次语义调用。各阶段有各自的超时（`stage_timeout_seconds`），单包上限 `max_input_chars`，分批大小 `part_input_chars`，宿主上限 `host_max_input_chars`。`status` 的 `forecast` 字段估计剩余调用和输入，列出预算缺口，便于开跑前确定预算。达到限额时保存断点并报告，不缩小用户范围，也不无限重试。

调整策略只用命令，不手改状态文件；已耗用的预算不会被重置：

```bash
$PY "$PLUGIN/bridge/production.py" policy --root "$RUN" --set max_calls=400 --reason "<依据>"
$PY "$PLUGIN/bridge/production.py" unblock --root "$RUN" --task <id> --reason "<依据>" [--accept-gaps]
$PY "$PLUGIN/bridge/production.py" retry --root "$RUN" --task <id> --feedback "<具体缺口>"
```

这三条命令都记为人工干预。不能用它们改变分块方式；分块变了要新建产线。`--accept-gaps` 只用于抽查后仍不通过的单元：它们作为声明缺口写进综合的 limits，不会被当作通过。

原文变更后运行 `sync`，失效受影响的阅读单元及其下游，未变单元继续复用，复用情况写入缓存事件。包损坏时先把旧包隔离，再从有效材料重新构建，不覆写损坏证据。

## 失败归因与定向返修

每个失败都追到能修复它的最小阶段，只重跑这个阶段及其下游：

| 来源 | 退回位置 |
|---|---|
| 抽查判单元不忠实、丢限定、声音错或漏关键机制 | 该单元重读，同时把相邻单元加入下一轮抽查 |
| 复核 repairs 指明原文限定、反例或后果没进入阅读结果 | 对应阅读单元 |
| 复核指出跨段汇合错误 | 对应合并任务 |
| 复核指出关系方向、声音、条件或范例问题 | 综合 |
| 评测归因 read | 相关能力的证据单元重读，再重新综合 |
| 评测归因 synthesize / examples | 综合（核心、触发、条件与完整范例） |
| 评测归因 build（包内有内容却没被加载使用） | 记为工作流问题（入口、索引、资源或加载方式），不改单本书 |
| 评测归因 evaluation | 记为评审器校准问题 |
| 评测归因 unknown | 先退回综合；同一用例再次失败时改退回阅读 |

返修轮次由 `max_repair_rounds` 限定，默认 2。超过后对应任务阻塞并列出缺口，不报完成。每次自动返修都写入运行记录。后续另一次评测的同一用例通过，该归因记为 confirmed-by-rerun；仍不通过则记为 not-confirmed。

## 实际运用、迁移和组合清单

构建结果为 `distilled-skill/2`，默认 `trial-unverified`。运行包只有入口、能力、范例、用途资产及必要元数据；不包含试题、评分依据、完整书稿、会话或本机绝对路径（包括 `/tmp`、`/Volumes`、`C:\` 等）。试用验收记录在包外，与内容哈希绑定；不能手改标签升级为 L3。

独立出题，保存 `production-eval/1` 的 cases：每例含 id、group、turns、rubric、targets（能力ID）、condition（normal/changed）、held_out，可选 deliverable（explanation/calculation/plan/judgment/narrative/expression）。初始覆盖 direct/combine/changed/correction/deliver/boundary 六类；每项能力覆盖正常和变化，至少一个 changed 保留题。知识包不出 expression 交付题。试题不得进入生成提示或运行包。

```bash
$PY "$PLUGIN/bridge/production.py" cycle --root "$RUN" --suite "$SUITE" \
  --source-context "$SOURCE_CONTEXT" --worker "$WORKER" [--loading host] [--max-rounds 2]
```

`cycle` 依次执行产线运行、评测、归因、定向返修、再评测，直到通过或返修轮次用完；它不会把没通过的评测报成通过。单独执行时用 `evaluate`（可不带 `--worker`，只准备评测目录）、`attach`（登记另行完成的评测）和 `repair`。评测只绑定当前构建；生成与复核过本包的会话都不能参与答题评审。

评分维度按用途选择：基础维度是 fidelity、application、utility；思想用途加 cognition（作者认知），表达用途加 expression（表达）。不适用的维度在配置里写明理由。任何维度低于 2 或出现严重失败时，评审必须给出阶段归因。保留题失败默认不反馈给产线；如果用 `repair --use-held-out` 反馈了，这些题记为已消费，后续评测要换新的保留题。

`--loading host` 把被测包放进一个新项目的 `.agents/skills/` 下，不把内容内联进提示，由宿主自己发现并加载。加载情况以宿主工具事件里观察到的读取路径为准，入口没被加载的用例判失败，并归因到 build。默认的 inline 模式由脚本把包内容附进提示，只能证明搬目录后内容可用，不能证明宿主能发现。只验证过某一个宿主，就只报告该宿主。

```bash
$PY "$PLUGIN/bridge/production.py" deliver --root "$RUN" --ws "$WS" --out "$OUT"
$PY "$PLUGIN/bridge/skill_portfolio.py" plan --ws "$WS" --id <slug> --object person --title <名称> --note <缺什么>
$PY "$PLUGIN/bridge/skill_portfolio.py" verify "$OUT"
```

必交原被测包和 `PORTFOLIO.json`（skill-portfolio/2）。清单每项包含：对象、标题、时期/版本、用途、触发条件、输入、输出、能力（含声音）、限制、依赖、来源范围、包版本与 build_id、内容哈希，以及已测的用例、宿主和加载方式。尚未构建的书籍或人物用 `plan` 登记为 pending，不计入可用 Skill 数。整体复制目录即可迁移，book 不写入 ncc 的特定目录。替换已有导出时用 `--replace`，旧版本会留快照。

## 记录与交付

```bash
$PY "$PLUGIN/bridge/production.py" metrics --root "$RUN"
$PY "$PLUGIN/bridge/production.py" failures --root "$RUN"
$PY "$PLUGIN/bridge/production.py" record --root "$RUN" --regression <make e2e 输出> --portfolio "$OUT" [--baseline <同范围基线产线>]
```

`metrics` 分项报告：首个可用 Skill 的耗时、记录到的墙钟时间、累计任务时间、调用次数、输入字符、token、评测成本、人工干预（按种类）、自动返修（按来源）、各阶段一次通过率、重复调用原因、失败类别、缓存复用及并发设置。费用不明时保持未知，0.5.0 的旧记录只报告当时实际记下的内容。

要比较产能，先跑同一来源、同一用途、同一档位的串行基线（`--parallel 1`），再与自动线比较；墙钟时间与费用分开报告。`record` 写出七项分开取证的交付记录：代码已实现、合同回归、Skill 在声明范围内可用、组合清单可用、原包迁移后运行通过、产能收益已观察、L3 已验收。任何一项都不能由另一项推定。

## 工作流改进

单书问题只修该书的材料或候选。跨书重复出现的问题，才改工作流本身的阶段模块或调度策略。

```bash
$PY "$PLUGIN/bridge/workflow_optimizer.py" failures --root <书A> --root <书B>
$PY "$PLUGIN/bridge/workflow_optimizer.py" propose --base "$PLUGIN/skills/book-workflow/references/production-modules.json" \
  --feedback <汇总.json> --worker "$WORKER" --out <私有实验目录>
$PY "$PLUGIN/bridge/production.py" init ... --prompts <实验目录>/modules.json
$PY "$PLUGIN/bridge/workflow_optimizer.py" compare ... --split held-out-source --out <对照.json>
$PY "$PLUGIN/bridge/workflow_optimizer.py" experience add|promote|reject --ledger <私有账本.json> ...
```

`failures` 汇总多书中已归因到阶段的失败，只有在两本及以上书中出现的问题才成为工作流候选。`propose` 每次只改一个模块的一处：一条指令、一个合成范例或一条失败处理规则；候选版本号带标记，不自动采纳。经验账本按 ACE 方式增量记录规则、适用条件、反例、用于调优的书和用于验证的书。规则只有在未参与调优的书上用相同候选模块做 held-out 对照、且质量不退步之后，才能升为全局规则；否则保留为书级或类型级建议。通过验证的规则走正常版本更新进入 production-modules.json，并提升 version。账本、对照和实验都留在私有目录。

这是小规模反馈搜索加经验账本，不声称完整实现 MIPRO 或 GEPA。质量、墙钟时间、累计任务时间、实际 token 与人工干预分别报告，包含失败和优化器自身的调用，不承诺固定提速倍数。

方法依据：[nuwa](https://github.com/alchaincyf/nuwa-skill/blob/7c7edfeb9d90a28b1f79e7847e1ba27a698cdc24/SKILL.md) 的人物框架与跨情境验证；[GEPA](https://arxiv.org/abs/2507.19457) 的反馈驱动文本优化；[ACE](https://arxiv.org/abs/2510.04618) 的增量上下文策略。以上都是本仓的适配实现，不代表上游效果认证。cangjie 及四闸继续负责适用的程序产物，没有修改 vendor 源码。
