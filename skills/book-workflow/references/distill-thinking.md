# 重建思想与叙事

适用于 0.3.0 默认的整书 Skill。源文本与产物均放工作区私有 `books/<slug>/`。以下字段是 `bridge/thinking_audit.py` 实际读取的 `book-skill/1` 合同；结构通过之后仍须独立语义复核。

## 从全文到可使用的思想

先确认版本、译者和实际覆盖范围。按全文阅读建立 `BOOK_OVERVIEW.md` 和 `coverage-audit.md`，把核心问题、概念区别、论证或叙事关系、分歧、表达样态映射到去向或缺口。原文污染、OCR、人物声音和补传分别说明，不能用最后生成的卡片反推覆盖。

先写出本书怎样看问题、什么关系能支持判断、怎样认识自己的错误，再登记概念与关系。不要把“分析、比较、反思”单独当成书中特有的能力。对小说可重建视角、选择和代价，保留多种解释；叙事后果不直接变成普遍因果。

`thinking/model.yaml` 顶层字段：

| 字段 | 实际合同 |
|---|---|
| schema_version | `book-skill/1` |
| authored_by | 本次思想及表达规格编写者标识；不能兼作独立复核者 |
| book | `id`（小写 slug）、`title`、`author`、`edition`、`kind`、`description`，均为非空文本；未知版本信息如实注明 |
| scope | `coverage`、`includes`、`excludes`，均为具体范围说明；选篇不能标整书 |
| concerns / concepts / claims / relations / operators | 各为非空列表；只保留有来源及用途的条目 |
| conflicts | 列表，可空；有实质分歧则保留 |
| core | `include` 为核心条目 id，`text` 为审阅过的连贯运行文本 |
| procedures | 有 Bundle 写 `status: bundle`；无程序写 `status: not_applicable` 与具体 `reason`，并经复核 |

所有思想条目共同字段：`id`、`statement`、`epistemic_status`、`anchors`、`conditions`、`speaker`。认识地位使用 `explicit` / `reconstructed` / `unresolved`；没有来源的条目不能因为常识合理而入核心。`depends_on` 和 `limits` 可选，为思想 id 列表。

关系另有 `from`、`to`、`type`。类型为 `causal`、`conditional`、`value`、`analogy`、`narrative`、`supports`、`constrains`、`contradicts`、`depends_on` 之一。方向必须符合原文，不能把相邻出现当作因果。

思想动作另有非空文本 `intent`、`inputs`、`move`、`warrant`、`alternatives`、`blocked_by`、`revise_when`，以及思想 id 列表 `uses`、范例 id 列表 `examples`。写明事实凭什么支持解释、哪些不同解释仍可能成立、什么条件会改变判断。

`core.text` 把这些内容写成可以指导理解的连贯文本，保留必要限制与实质冲突。构建器逐字嵌入入口与生成 CORE，不另作自由摘要；核心全部依赖不能包含 unresolved 条目。结构检查不证明这段说明在语义上忠实。

原作不足以支持可用的思想关系与动作时，登记产品条件未满足，可交有依据的程序或参考材料；不能为填满字段替它发明一套思想体系。

## 证据与上下文

`evidence/anchors.yaml` 顶层为 `schema_version: book-skill/1`、`source`、`anchors`。先读取实际源文件，用下面的函数取得 `source`，不手填或猜测哈希：

```bash
$PY -c 'import sys; sys.path.insert(0, sys.argv[1]); from book_skill_common import source_hashes; import yaml; print(yaml.safe_dump(source_hashes(sys.argv[2])))' "$PLUGIN/bridge" "<原文路径>"
```

每条 anchor 包含 `id`、`locator`（人工可读的章/页/时间）、`quote`、`start`、`context`。`start` 是源文本去全部空白后的字符偏移。短引文中文不超过150字、英文不超过100词。

`context` 包含 `start`、`text`、`speaker`、`audience`、`period`、`level`。上下文文本也必须在声明偏移逐字存在，并覆盖对应引文实例；这能防止把同一句话的另一处出现当作当前出处。上下文允许比引文长，完整原文仍不默认放进交付包。说话者、时代未知时明确记录，不能从文件标题推断每句话是谁说的。

## 让叙事参与理解

`expression/PROFILE.md` 先有唯一的 `## 运行摘要`。下一处二级标题前的文本会逐字嵌入最终入口，必须同时包含适用语体、具体写法与内容限制。

其后用 YAML 代码块登记表达条目。每块字段是：`id`、`instruction`、`context`、`function`、`limits`、`anchors`、`uses`。后两项分别是证据 id 和思想 id 列表，其余为非空文本。

从连续段落观察叙述视角、信息揭示次序、叙述距离、与读者的关系、语气和句群节奏。`function` 说明这种写法怎样帮助认识，例如视角转换保留另一种解释、条件对举显出界限。按实际文体采样，不能凭一段论战让全书永远激烈。

思想与表达同时参与生成。中性版与表达版用来检查内容保持，不能把生产流程固定为先写通用答案再改口吻。真实问答不添加未知经历与感官细节；小说第一人称不自动授权冒充作者经历。

## 完整范例

`thinking/EXAMPLES.md` 使用 YAML 代码块，每块包含：

- `id`、`kind`：类型只能为 `source_reconstruction`、`application`、`condition_variant`。
- `prompt`、`answer`：完整输入与自然回答；书外应用明确标为合成。
- `rationale`：简短的事实、关系与判断对照，供审核使用，不记录完整内部思维。
- `assumptions`、`change_if`：迁移假设、可能改变判断的新事实。
- `anchors`、`uses`、`expression`：证据、思想和表达条目的 id 列表。

至少重建一处原书的论证或叙事；核心思想动作至少关联一个 application 和一个 condition_variant，多个动作可共用完整范例。示范怎样从事实形成认识，不只给正确答案或照搬原书故事。范例进入包，属于已见教学内容；保留题与评分依据不得进入包。

可读的完整格式参照仓内原创合成夹具 [thinking-book](../../../tests/fixtures/thinking-book/thinking/model.yaml)、[表达条目](../../../tests/fixtures/thinking-book/expression/PROFILE.md)、[范例](../../../tests/fixtures/thinking-book/thinking/EXAMPLES.md) 与 [合成来源](../../../tests/fixtures/thinking-source.md)。只借格式，不能把其渡口思想或短句风格移植给其他书。

## 独立复核与回炉

```bash
$PY "$PLUGIN/bridge/thinking_audit.py" --book-dir "$BOOK" --source "$SRC" --ws "$WS" --prepare-review "$BOOK/eval/source-review.json"
```

退出3表示结构通过、语义待复核。模板逐条列出 anchor、思想、core、表达、范例、覆盖和程序适用性的目标。由独立阅读原文的复核者写 `reviewer`、`independent: true`，每个目标的 `status`（passed/failed/pending）及具体 `rationale`。编写者不能替自己作独立核查；模板不会自动填通过。

```bash
$PY "$PLUGIN/bridge/thinking_audit.py" --book-dir "$BOOK" --source "$SRC" --ws "$WS" --review "$BOOK/eval/source-review.json"
```

结构和语义通过后才构建候选。内容改动会使旧评审失效；保留旧记录，为新输入生成新模板，并在后续命令中显式传入新的 `--review` 路径。原文确实存在但不支持解释时，修思想或表达，不能只改引用位置。
