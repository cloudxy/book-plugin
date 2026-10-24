# 实际回答评测与发布

来源与适用程序审计通过后，由构建器生成 `.work/<book-id>/builds/<signature>/package/<book-id>/`。记录它为 `$CANDIDATE`。这是实际可加载的试验包，包内不带保留题、用户会话或评分。

```bash
$PY "$PLUGIN/bridge/build_book_skill.py" verify --candidate "$CANDIDATE"
```

最终包只含一个 `SKILL.md`。思想核心与口吻摘要内嵌入口，完整模型、表达规格、开发范例、短证据位于 references。程序有独立调用索引，没有旧 single 总入口。篡改或缺文件会使完整性检查失败。

## 固定题目与运行环境

先固定评测范围、关键任务、合理答案范围及失败标准；由能读原文的独立出题者设计保留题，不只从最终模型字段出题。核心动作既要有正常场景，也要有改变或阻断判断的场景。

`eval/cases.yaml` 包含 `cases` 列表，每例字段：

v2包要求顶层`schema_version: book-eval/2`；v1包仍用book-eval/1（可沿用未声明版本的旧suite）。包与题库版本必须相符，不能把旧成绩升格为作者分身验收。

| 字段 | 合同 |
|---|---|
| id / group | id 用字母数字、连字符或下划线；group 为 C01–C15 |
| prompt 或 turns | 单轮文本，或依次递交的用户消息列表；也支持 `role: user`、`content` 对象 |
| required | 布尔值，默认 true；事前固定核心失败是否阻止放行 |
| held_out | 布尔值，保留题不参与内容或提示调优 |
| expected_dimensions | v2从 fidelity / modeling / inference / updating / utility / expression / author_cognition / author_expression 选择；开放、解释、对话和写作必须有后两项。默认单轮不测updating，多轮加入；精确查询默认fidelity/utility，程序默认fidelity/modeling/inference/utility，可按事前任务显式细化 |
| rubric | 非空文本或文本列表，说明合理答案范围、来源与关键条件，不能只要求原句和术语 |
| task_type | v2默认open，也可writing/explanation/dialogue；精确原文lookup只适用C01、procedure只适用C12，并提供applicability_reason；不能以此豁免开放问题 |
| author_targets | v2指向候选manifest.author_targets中的习惯/路径/表达id；适用作者任务非空 |
| author_condition | 有作者目标时必填normal或changed；事先固定是什么条件或任务变化及合理预期 |

C01书内解释、C02陌生迁移、C03跨章综合、C04关键词诱饵、C05关键前提变化、C06无关变化、C07信息不足、C08迎合诱导、C09分歧与归属、C10多轮更新、C11表达对照、C12边界与程序、C13解释探索、C14叙事口吻与篇幅、C15持续会话。正式验收覆盖15组，C02/C03/C05/C13/C14具有保留实例。不存在的程序、多声部等子项由独立评审说明适用性，不能删掉迁移、更新、综合或表达核心要求。

陌生迁移与解释探索必须包含直接求解的普通问题，观察回答能否用书中特有关系解释当前事实、作出判断并给出有用结果。引文数量、报出篇名、逐句回源和只列不能推断的事项都不算完成；因原书没有现成答案而拒绝正常推演，属于运用失败。同时安排明确要原话或出处的查证题，确认来源纪律仍有效。记录实际读取路径以辨认检索是否由任务需要触发，不给日常分析设置强制检索次数。

```bash
$PY "$PLUGIN/bridge/eval_book_skill.py" prepare --candidate "$CANDIDATE" --suite "$BOOK/eval/cases.yaml" --run-dir "$RUN"
```

prepare 只准备，不调用模型。初步排错可用 `--mode diagnostic`，这类运行不能正式放行。对照使用 `--variant none`、`--variant legacy --baseline <实际旧包>`、`--variant retrieval --source "$SRC"`；检索基线允许充分阅读和推理。缺少旧包就记缺席。

摘要加通用模仿对照使用`--variant summary --baseline <明确编写的对照Skill> --mode diagnostic`。材料移除或交换使用`--variant ablation --baseline <明确编写的对照Skill> --control-kind <without_habits|without_expression|swapped_expression|without_examples> --mode diagnostic`。控制材料须真实存在、固定并记录差异；联合核心不能靠隐蔽删词假称只移除一个机制。summary/ablation只能诊断，不能发布。prepare绑定实际控制材料哈希；共享一次相同无Skill回答如实注明，不能增加独立样本数。

为每个变体使用相同宿主、模型、事实、工具权限与预算，并隔离工作目录和会话。记录实际版本或观测限制；在只测一个宿主时，不宣称其他宿主通过。关键任务至少复跑一次，成功和失败均保留。

## 干净会话试答

复杂包优先由独立 sub-agent 试答。只给一个 `packets/<id>.json`、它指定的 Skill/原文及必要任务事实，不给 suite、rubric、其他题和其他变体。基线同样不看评分材料。

多轮题的索引只给第一轮路径，各用户消息在 `packets/<id>/turn-01.json` 等独立文件。主持人收到该轮完整回答后，才将下一轮交给同一答题会话；不能让首答预先看见纠正事实。一次读取全部轮次的演练仅作 diagnostic，不能算正式多轮验收。

实际执行者保存一份 JSON：

```json
{
  "case_id": "C02-01",
  "answers": ["真实完整回答，不是预期答案"],
  "executor": "本次答题者标识",
  "host": "实际宿主",
  "model": "实际版本，无法观测时注明限制",
  "session_id": "本题独立会话标识",
  "isolated": true,
  "loading_evidence": {"paths": ["实际读取路径"], "limits": ["无法取得完整加载日志时如实说明"]}
}
```

多轮 `answers` 每轮一项，并记录 `turn_delivery: sequential`。各题不得复用答题历史。会话标识和隔离字段是执行者的记录，不是工具对底层隔离的密码学证明。

```bash
$PY "$PLUGIN/bridge/eval_book_skill.py" collect --run-dir "$RUN" --case C02-01 --answer <真实输出.json>
$PY "$PLUGIN/bridge/eval_book_skill.py" score-structural --run-dir "$RUN"
```

collect 保留原输出；重试另开 run，不覆盖。结构检查可以返回 structural_passed，只表示输出和记录齐全，不能用作发布许可。

## 独立语义与表达评审

把完整回答去掉变体名称后交给未参与答题的评审，提供对应原文、题目和 rubric，隐藏方案作者解释与优劣标签。使用新会话；评审者不能与该题 executor 相同。

在 `$RUN/reviews/<id>.json` 保存：`answer_sha256`（规范 JSON 输出的 digest）、`rubric_sha256`（该 case 的 digest）、`reviewer`、`independent: true`、`blind: true`、`dimensions`、`expression`、`hard_failures`。可用 `book_skill_common.digest` 计算 digest；评分与理由必须来自实际阅读。

可用以下命令制作匿名评审包，只隐藏执行者/变体等记录，不删正文、引文或论证内容：

```bash
$PY "$PLUGIN/bridge/eval_book_skill.py" blind --run-dir "$RUN" --out-dir "$BLIND"
```

只给评审`$BLIND/packets/`、必要原文与固定评分依据，不给host-map。每包的answer_sha256绑定完整采集JSON，answers_sha256绑定原样answers数组；两者用途不同。来源评分保留未经删改的完整回答，不靠事后删重要内容遮作者线索。

`dimensions` 每个适用维度有 `score` 0–3 与 `rationale`：0错误或缺失，1提及未发挥作用，2完成，3有额外辨别与整合。核心项低于2不能被别题高分平均掉。`hard_failures` 必须明确为空列表或列出来源失真、编事实、无依据外推等严重失败。

v2的author_cognition与author_expression分别检查作者的注意对象/问题框架/依据/取舍是否实际改变本题，以及视角/材料安排/认识转折/读者关系/节奏是否参与成文。通用正确、词句像、引用少、猜出作者姓名均不能替代。每项另需`answer_excerpt`，必须逐字出现在真实某轮回答中；rationale把它与来源机制连起来。只说“符合作者”不构成语义依据。

v2评审还需`author_evidence`：键精确覆盖本题author_targets，每个值有`answer_excerpt`和具体`rationale`，解释该目标如何发挥作用。正式验收只累计已通过实际评审的题，每个运行习惯、路径、表达均有normal及changed覆盖；高分但缺目标或变化情境仍待完成。机器只查证据确实来自答文，语义是否成立仍由独立人或模型实际核查。

表达适用时，`expression` 逐项评审 `viewpoint`、`organization`、`tone`、`rhythm`、`naturalness`、`preservation`，每项分数和理由；确不适用的特征可用 `status: not_applicable` 并解释，但自然程度和内容保持不能跳过。区分风格辨识与结论正确，不能靠加名言过关。

用户实际审阅完整回答后，依据用户反馈记录 `$RUN/user-expression.json`：`build_id`、`suite_sha256`、每题 `output_sha256`、`reviewer_role: user`、`approved` 和具体 `rationale`。没有反馈就保持待用户审阅，不能由代理代填批准。明确要求修改时先修并重验，不把旧反馈套给新回答。

```bash
$PY "$PLUGIN/bridge/eval_book_skill.py" report --run-dir "$RUN"
```

退出0且 status passed 才是当前范围的正式验收；退出3为待运行/待复核/待用户审阅；退出1为失败。报告始终保留计划、实际、缺失和失败数量。完整方法和对照消融见 [验收方法](../../../docs/designs/judgment/methodology.md)。

## 发布原候选

```bash
$PY "$PLUGIN/bridge/build_book_skill.py" publish --candidate "$CANDIDATE" --acceptance "$RUN/acceptance.json" --out <已明确的安装目标>
```

publish 重新计算报告并校验题目、实际输出、独立评审、用户表达反馈和候选字节。无 Skill 或检索基线的通过不能授权发布新包。待测、手工改过的 acceptance、旧评审和改过的候选均不能放行。

替换已存在目标时显式 `--replace`，保存同级 `.名称-previous-<hash>` 快照再原子切换。检测到目标或候选不符合合同则保留现场，回到构建及具体失败项修正。更新通过重建完成，不手改 dist，也不向组合包运行上游 update/repair。
