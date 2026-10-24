# 从原作重建作者

0.4.0新蒸馏使用`book-skill/2`。以下字段由`bridge/thinking_audit.py`和`author_persona.py`实际读取。v1保持[原合同](legacy-v1.md)，升级必须补读、重建并重新审阅，不能改版本号或把旧概念重命名即完成。

## 阅读与四类覆盖

固定原文、版本、译者与正文/附录边界。先独立建立`BOOK_OVERVIEW.md`、`coverage-audit.md`，记录重要问题、论证、叙事、声音与语体各自去向和缺口；不能用最终模型反推覆盖。分别报告：

- reading：实际读到哪里，哪些段落、场景或时期未读。
- reconstruction：重建了什么，哪些重要思想或表达仍未建模。
- runtime：哪些已审机制实际进入核心，能够支持哪些任务。
- acceptance：哪些范围在何种宿主实际验过，哪些还在待验。

全文切片用于阅读安排，不能以窗口数量证明语义覆盖。完整论证或场景可跨阅读窗口，须接上上下文；标题、网页污染、OCR、编者、译者、人物、引用者分别登记。只排除一个局部时不连带删除整个窗口。

输入中的runtime与acceptance声明目标及验收范围，不填写会随运行变化的通过状态。实际进度放PIPELINE_STATE，实际验收由包外的绑定报告判定；不在答题通过后反写核心或scope，使原被测包发生变化。

## 公开文本的推演片段

`reading/episodes.yaml`顶层：`schema_version: book-skill/2`、`source`、非空`episodes`。source用`book_skill_common.source_hashes(实际原文)`生成，格式沿用v1：raw_sha256、text_sha256、normalization=qnorm-v1。

每个episode的实际字段：

| 字段 | 要求 |
|---|---|
| id | 唯一文本id |
| start / end | 原文去全部空白后的字符范围`[start,end)`；整数且不越界 |
| span_sha256 | `digest(qnorm原文[start:end].encode())`；不是原文件字节切片 |
| locator | 可回读的篇章、页码或时间范围 |
| voice | `level`为author/narrator/character/quoted/editor/translator/mixed之一；`speaker`具体说明分层 |
| task | 文本在处理什么问题或读者预期 |
| progression | 可以回查的材料选择、关系展开、视角或信息转换与收束 |
| reading_effect | 这些写法怎样改变读者认识，不能只填“生动” |
| completeness | 此逻辑单元读到的前后边界、尚未闭合的部分和排除内容 |
| anchors | 本范围内的短证据id列表；反证片段可无短引文 |

记录文本公开可见的动作，不索取模型内部思维，不声称还原作者真实心理或落笔顺序。范围哈希只证明定位；逻辑完整性、声音归属及构思解释由独立读原文的人复核。

## 模型与作者画像

`thinking/model.yaml`：

| 字段 | 合同 |
|---|---|
| schema_version / authored_by | `book-skill/2`；本次规格编写者标识，不能兼任独立来源评审 |
| book | id小写slug；title、author、edition、kind、description均非空，未知如实写明 |
| scope | coverage、includes、excludes及上面reading/reconstruction/runtime/acceptance，均为具体非空文本；局部不能写整书 |
| author | portrait整体说明、scope范围、voice_policy声音纪律、limits局限，均为非空文本 |
| concerns / operators / habits / paths | 非空列表 |
| concepts / claims / relations / conflicts | 列表，可空；有实际关系才登记，不为小说制造哲学体系 |
| core | include思想/习惯/路径id列表；text已审联合运行文本 |
| procedures | 有Bundle写status=bundle；无程序写status=not_applicable及reason，须独立复核 |

全部模型节点共有`id`、`statement`、`epistemic_status`、`anchors`、`conditions`、`speaker`。认识地位explicit/reconstructed/unresolved；depends_on和limits可选，为节点id列表。重建并非作者明说，未解决假设不能进入核心依赖闭包。

关系另有from、to、type。类型保留causal/conditional/value/analogy/narrative/supports/constrains/contradicts/depends_on。方向和机制须实际成立，相邻句子不证明因果，局部习惯不自动支持整个复合路径。

思想动作另有非空intent、inputs、move、warrant、alternatives、blocked_by、revise_when，以及uses节点列表、examples范例列表。交代凭什么形成判断，而非只写“分析、比较、反思”。核心动作仍须有application与condition_variant。

## 隐藏习惯与可变路径

习惯从完整构思过程提出具体假设：作者首先注意什么，怎样重新命名问题，从谁的位置看，接受什么依据，如何取舍、排除解释或修正；行文如何参与这些认识。找不同对象、时期、语体中的支持和反证，排查题材、人物、译法或局部修辞等竞争解释。

habit除共有字段外，实际需要：

- episodes：支持片段id列表；anchors须落在这些片段内。
- trigger、move、effect：触发情境、具体动作、对认识与成文的影响。
- alternatives、counterevidence、revise_when：竞争解释、反证或未找到反证的具体边界、修正信号，非空文本。
- stability：local或cross_context。是否足以称跨情境由语义评审判断，不按出现次数自动晋级。
- counterepisodes：可选反证片段id列表。

一处明确材料能支持局部特征，不能自动支持整个人格。没有提到某因素不等于作者永远忽略它。保留有来源的偏好、锋芒、张力和局限，不只挑最讨好的道理。

path另需：episodes；task、selection、composition、revise_when非空文本；habits、operators、expression、examples分别引用习惯、动作、表达和范例。说明面对什么任务，为什么组合这些动作，何时换路径，怎样成文；不能把通用固定步骤套给所有书。路径有application和condition_variant，范例须真正调用该路径及至少一个相关动作，并联结该路径的表达。

核心闭包至少含一条习惯、一条路径和一个思想动作，沿uses/depends_on/limits、关系端点、路径习惯与动作展开；任何unresolved依赖都会阻止构建。联合核心自然写明作者定向、关键区分、路径选择和行文机制。构建器逐字内嵌，不从格言自动拼人设；生成CORE和AUTHOR_PROFILE都不是第二份可手改的输入。

联合核心须写明书外运用的事实边界：纠偏面向题内已知事实和用户已表达的主张。未知的动机、心理、立场、进度或组织关系如需参与解释，标为假设并说明它怎样影响判断；反问、反转和归因也不能把假设写成既成事实。虚构写作的创造权限按任务单列；原作已有的强断言和偏见按来源留存，区分历史文本的呈现与对新处境的断言。允许形成明确、鲜明、有用的新判断。

## 证据与表达

`evidence/anchors.yaml`与v1相同，schema_version改为book-skill/2，每条增加episodes列表，与episode.anchors双向相符。id、locator、quote、start、context必需；context含start、text、speaker、audience、period、level。引文及覆盖它的上下文均须在声明位置逐字存在；中文短引文≤150字，英文≤100词。全文不默认进入运行包。

`expression/PROFILE.md`有唯一`## 运行摘要`，下一处二级标题结束摘要。摘要逐字进入入口，只放运行定向，不能夹YAML来源记录。YAML表达条目仍用id、instruction、context、function、limits、anchors、uses。uses须联结至少一条习惯或路径，function解释写法的认识作用。

从连续段落看材料次序、叙述距离、读者关系、信息揭示、语气与节奏。反问可能重置问题，延迟揭示可能修正初判，短句可能压实判断；各按实际功能重建。人物台词不直接变作者立场，小说结果不成为现实因果，译本语言不全部归原作者。认知与表达联合生成，不固定先写通用回答再加口头禅。

## 联合应用范例

`thinking/EXAMPLES.md`的每个YAML块：id、kind（source_reconstruction/application/condition_variant）；prompt、answer完整；rationale说明可公开检查的事实、关系和判断；assumptions、change_if；anchors、uses、expression分别引用证据、模型和表达。

至少重建一个原书过程。主要路径及核心动作有表面不同的书外应用和改变关键事实的变体，可以共用完整范例。解释、探索、取舍、对话和适用写作应真正处理题内处境。范例不是逐句找原文、换人物复演旧故事或只列禁止外推。教学合成如实标明，真实用户处境不称虚构。范例进包，评分与保留题不进包。

书外成文范例须展示可直接使用的完整正文，rationale与假设记录放在正文之外。非虚构材料较少时，按本书确有依据的成文方法选择、集中、重排、照应或作有限评议，让准确叙述和适当判断强度体现事实边界。逐项复述材料、反复说明依据够不够或证明自己未曾虚构，不能替代作品本身的组织与表达。

格式可看[原创合成v2夹具](../../../tests/fixtures/persona-book/thinking/model.yaml)及其[片段](../../../tests/fixtures/persona-book/reading/episodes.yaml)。只借文件格式，不把合成渡口观点或写法移植给其他书；夹具分数不是作者行为验证。

## 独立来源复核

```bash
$PY "$PLUGIN/bridge/thinking_audit.py" --book-dir "$BOOK" --source "$SRC" --ws "$WS" --prepare-review "$BOOK/eval/source-review.json"
```

退出3表示待复核。逐项目标包括author、episode、anchor、node、core、style、example、coverage、procedure_applicability和适用程序合同。独立复核者读原文填写reviewer、independent=true、每项status=passed/failed/pending及具体rationale。真实存在的原句不能自动证明画像、稳定习惯、路径或语体成立；逐项反证与竞争解释同样审。

```bash
$PY "$PLUGIN/bridge/thinking_audit.py" --book-dir "$BOOK" --source "$SRC" --ws "$WS" --review "$BOOK/eval/source-review.json"
```

原文、模型、表达、范例、覆盖或episodes任一改动都会使旧来源评审失效。保留旧记录，为新输入生成新模板；失败定向修相应来源，不改闸门把pending变passed。来源通过才构建私有候选，实际能力还须[独立答题验收](evaluate-and-publish.md)。
