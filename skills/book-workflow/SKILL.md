---
name: book-workflow
description: 把书、长视频或播客蒸馏成能运用原作思想推演、保留叙事与口吻的 Skill，并核查来源、实际回答和交付包。用于拆书、蒸馏为 skill、继续任务、补蒸馏思想与文风，或审计和配图；不用于单纯摘要。
metadata:
  book-workflow.version: "0.3.0"
  vendors: cangjie-skill v2.5.0-refresh ｜ dsh-distillation-director v4.9.26 ｜ svg-diagram @ c30c9e3 ｜ html-css-to-image v0.3.0
---

# book-workflow

让原作思想影响怎样理解问题、形成新判断与接受修正，让叙事和口吻影响认识怎样展开。思想与表达由 book-workflow 联合重建；仓颉负责其中的程序能力。检索用于查证，程序用于具体执行。

## 路径与工作区

解析本文件加载路径的软链，用 `Path(skill_path).resolve().parents[2]` 定位插件根 `$PLUGIN`，确认存在 `scripts/bootstrap.py` 和 `vendor/`。不要从 `.agents`、`.claude`、`.grok` 挂载路径推算。当前用户项目根为 `$WS`，私有材料全部写入其 `books/`、`.work/`。

```bash
python3 "$PLUGIN/scripts/bootstrap.py" "$WS"
```

后续用 `$WS/.venv/bin/python`，记作 `$PY`；跨工作区的桥接、自有审计与构建均显式传 `--ws "$WS"`。自举幂等；html-css-to-image 无密钥不访问网络。

## 选择范围并续跑

读取原文、书名/作者/版本/译者及用户目的；未知元信息如实登记，没有原文不凭记忆拆书。先读 `books/<slug>/PIPELINE_STATE.md`，保留已验工作与旧安装，按缺失阶段续跑。

- 新蒸馏默认交付一个整书入口，包含思想、叙事与口吻、完整范例，以及适用的程序。
- 用户明确只要原有程序 single/pack 时，使用下述程序路径；已有程序产物不静默迁移或改变原输出选择。
- 旧书补升级时回读原文，新增思想、表达和范例，重建新候选；不能把全文切片或程序卡自动改名成思想模型。
- 只审计按 `/book-audit` 范围核查现有材料；只配图按 `/book-diagram` 范围执行。

本地书稿、模型、完整回答和评审是使用数据，不进入远端仓库。

## 一 整书阅读与联合重建

读取 [重建思想与叙事](references/distill-thinking.md)，按实际全文建立 overview 与独立覆盖底账，记录核心问题、概念区别、关系、分歧、论证或叙事结构及表达样态。重要思想即使只出现一次，也按其作用核查。

产物：

```text
books/<slug>/
  BOOK_OVERVIEW.md
  coverage-audit.md
  thinking/model.yaml       # book-skill/1；连贯 core.text + 命题、关系、思想动作
  thinking/EXAMPLES.md      # 原书重建、书外应用与条件变体
  expression/PROFILE.md    # 有来源的叙事与口吻；唯一“运行摘要”
  evidence/anchors.yaml    # 短引文、版本哈希、定位、上下文与声音层次
  eval/                    # 题目、真实输出、独立评审；不进入运行包
```

思想动作写明：看哪些事实、凭什么形成解释、哪些其他解释仍可能成立、什么会阻断或改变判断。小说允许多视角，人物台词不直接充当作者立场，情节后果不自动当作现实规律。

思想与叙事同时影响生成。采集观察视角、材料揭示次序、叙述距离、与读者的关系和语言节奏；每项说明其认识作用与语境。完整范例示范从事实形成认识，原书重建与书外合成分别标明。简答、解释、探索、决策不强制同一格式。

来源足够但不能独立执行的思想或审美不因此淘汰；来源或解释不充分的内容标 unresolved，不进入可断言的核心。

## 二 程序能力与出图

原文包含需要交付的计算、流程、排障或可执行框架时，完整读 `$PLUGIN/vendor/cangjie-skill/SKILL.md`，沿其阶段0–4生成 `.cangjie/capabilities/` Bundle、能力卡与压力测试记录。程序能力的 V1/V2/V3、RIA++ 和晋级纪律沿用上游；思想与叙事仍由本技能定义。

没有程序时，在 model 中登记 `procedures.status: not_applicable` 和范围原因，交由来源复核，不制造空 Bundle。已有 Bundle 不能宣称不适用；原有程序 single/pack 模式继续按其 Bundle 工作。

### SVG 出图

需要图时先读 `$PLUGIN/vendor/svg-diagram/SKILL.md`。能力图放 `.cangjie/capabilities/resources/` 并在卡片正文与 Bundle resources 声明；overview/digest 图放书树 `assets/`，正文相对引用。图文一致，lint error 清零：

```bash
node "$PLUGIN/vendor/svg-diagram/tools/svg-lint/bin/svg-lint.mjs" <图.svg>
```

仅用户明确要求栅格图，且已有 `HCTI_API_ID`、`HCTI_API_KEY` 时，先读 html-css-to-image 的 SKILL，再用 `bridge/render_html_image.py` 处理书树以外的 HTML/CSS。它不进四闸，也不替代 SVG 闸；无密钥不调用。

## 三 来源核查与适用程序四闸

思想、表达及范例按 [来源合同](references/distill-thinking.md) 运行 `thinking_audit.py`，生成逐项语义复核模板并由独立读原文的评审填写。引文与上下文逐字存在，只证明来源定位，不能自动证明解释成立。退出3为待复核，不能宣称通过。

有程序 Bundle 时，先逐字桥接，再运行原有四闸：

```bash
$PY "$PLUGIN/bridge/cangjie_to_dsh.py" --book-dir "$BOOK" --source "$SRC" --task "$TASK" --ws "$WS"
$PY "$PLUGIN/bridge/run_audit.py" --task "$TASK" --ws "$WS"
```

四闸仍查池覆盖、日期锚、证据闭包、SVG。新增机器回执绑定原文、Bundle 和审计副本；改材料必须重新桥接核查。没有程序时报告“经核实不适用”，不能写“四闸全绿”。

| 失败位置 | 回炉 |
|---|---|
| 思想、核心、叙事、范例语义 | 修对应条目与来源，再作独立复核 |
| 桥接回源 / G-67 | 修程序 R 层引文与日期锚，重跑桥接 |
| G-66 | 回仓颉阶段1/1.5补采或复核淘汰 |
| G-68 | 重建证据包；仍红查 id 映射 |
| 图件 | 修图或补引用，重跑审计 |

## 四 构建候选并实测回答

来源及适用程序审计通过后，读取 [实际回答评测与发布](references/evaluate-and-publish.md)：

```bash
$PY "$PLUGIN/bridge/build_book_skill.py" candidate --book-dir "$BOOK" --source "$SRC" --ws "$WS" --review "$REVIEW"
```

候选只写 `.work/`，不等于已验收。构建器逐字内嵌已审思想核心与口吻摘要，携带范例及必要短证据；调用上游编译程序依赖，再只选取程序卡、资源和支撑材料，生成自有程序索引。上游“一张卡、未命中即停”的总入口不装入新包。

按目标宿主在干净会话实际答题。复杂 Skill 优先用独立 sub-agent 压力测试：只给本题输入、候选路径与所需原始事实，不给评分依据；多轮题逐轮递交。保存真实回答及可得的加载记录，再由独立、隐藏变体标签的评审核查。

核心任务包括陌生迁移、跨章综合、条件变化与不变、多轮修正、解释探索，以及短答/长答的叙事口吻。比较无该书 Skill、实际旧版、原文检索基线与新版；缺少旧版就记缺席。移除思想、表达或范例作诊断，保留题不参与调优。

## 五 验收与交付

评测入口的 prepare、collect、score-structural、report 分开；准备题目或字段通过不等于回答通过。思想忠实、推演、实际效用和叙事口吻分别核查，用户根据完整回答审阅目标口吻。

实际输出缺失、语义未评、保留题不足或用户口吻审阅未完成时，提交明确标为试验的候选与当前缺口，保留断点，不能宣称整书正式放行。

正式整书交付：使用 `build_book_skill.py publish`，只发布与验收记录绑定的原候选字节；指定安装目标沿用用户已明确的选择。替换已有目标时先保留可恢复快照，内容改动须重建并重验受影响项目。

用户明确选择原有程序 single/pack 的交付：适用程序审计全绿后调用上游 `cangjie.py compile --output <原选择>`，其结果只标程序版，不能冒充已完成思想与文风升级。

## 权威与边界

本技能和 references 定义思想、叙事、候选构建与行为验收；仓颉定义程序能力，dsh 定义程序三闸，svg-diagram 定义图件房规。四件 vendor 源码不改；通过进程级调用组合。文件合同由 `bridge/` 实现，设计背景见 `docs/designs/judgment/`。

普通 Skill 文件不改变模型权重。以原文语义和实际回答验证思想是否发挥作用；不能以引用数、文件数、字段齐全或模型自述“已理解”证明思考能力。
