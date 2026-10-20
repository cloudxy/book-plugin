---
name: book-workflow
description: 知识蒸馏闭环工作流：把一本书/长视频/播客蒸馏成可执行 Skill（生成），画出房规 SVG 图（出图），再做逐字回源审计与四闸判态（验证），全绿才编译交付。Use when the user says "拆书"/"蒸馏一本书"/"把这本书做成 skill"/"蒸馏后审计"/"distill this book into skills"/"audit the distilled skills"，或要对已有 cangjie 产物跑回源审计/配图。NOT for 单纯书摘要、读后感、作者人设扮演。
metadata:
  book-workflow.version: "0.2.1"
  vendors: cangjie-skill v2.5.0-refresh ｜ dsh-distillation-director v4.9.26 ｜ svg-diagram @ c30c9e3 ｜ html-css-to-image v0.3.0
---

# book-workflow — 蒸馏 → 出图 → 审计 → 放行/回炉

## 路径约定（先读这个）

- **插件根（= 仓库根）**：先对本 SKILL.md 的实际加载路径解析软链（Python `Path(skill_path).resolve()`），再取 `parents[2]`，记作 `$PLUGIN`。项目入口可能位于 `.agents/skills/`、`.claude/skills/` 或 `.grok/skills/`，不能直接从这些挂载路径向上取两级。解析后须能找到 `$PLUGIN/scripts/bootstrap.py` 和 `$PLUGIN/vendor/`。
- **工作区** = 用户当前打开的项目根（cwd），记作 `$WS`。蒸馏产物（`books/`、`.work/`、`tools/`、`.dsh/`）全部落在 `$WS`。
- **桥接/审计脚本不在工作区内**，调用时**必须带 `--ws $WS`**，否则找不到工作区根。
- 原则：先审计后编译——阶段 5 的 compile 只对判态全绿的 Bundle 做。

```
cangjie 蒸馏（阶段0-4） → svg 出图（按需） → 桥接（逐字回源） → 四闸审计 → 全绿 compile 交付
        ▲                                                        │
        └────────────────── 回炉（按判态映射） ◀── 红 ────────────┘
```

## 第 0 步 — 工作区自举（每个工作区一次，幂等）

```bash
python3 $PLUGIN/scripts/bootstrap.py $WS
```

它建 `$WS/.venv`（Python ≥3.10 + PyYAML + PyMuPDF + html-css-to-image 0.3.0）、装入 dsh 闸门套装（`$WS/tools/` 与 `$WS/.dsh/`），并体检 node（图件闸的 svg-lint 依赖，缺失时该闸判"不适用"）。之后的命令统一用 `$WS/.venv/bin/python`（下文记作 `$PY`）。html-css-to-image 只是可选出图客户端；没有 `HCTI_API_ID` 与 `HCTI_API_KEY` 时不访问网络。

## 阶段一 — cangjie 蒸馏（生成侧）

先确认输入：**原书文本**（PDF/EPUB/TXT/转写稿路径，没有文本就停下来向用户要，不凭记忆拆书）、书名+作者+出版年、使用目的（学习查阅→single；接入日常/跨书组合→pack）。

然后**完整阅读 `$PLUGIN/vendor/cangjie-skill/SKILL.md` 并严格按它执行**（RIA-TV++ 五阶段：Adler 整书理解 → 5 路并行提取 → 三重验证 → 晋级门 → RIA++ 能力卡 → Zettelkasten → 压力测试）。本工作流要求：

- 产物落在 `$WS/books/<slug>/`（含 `verified.md`、`candidates/`、`rejected/`、`.cangjie/capabilities/`）；
- **跑到阶段 4（压力测试）之后、阶段 5（编译交付）之前停下**，先进入本工作流的出图与审计；
- 保留全部审计轨迹，断点续跑状态（PIPELINE_STATE.md）每阶段更新。

## 阶段 1.5 — 出图（svg-diagram，按需）

框架/流程/计算类能力卡或 DIGEST 需要配图时，**先读 `$PLUGIN/vendor/svg-diagram/SKILL.md` 的房规**再手绘 SVG（CJK 字体栈、五组语义配色、盒高=字号×3、盒间距≥25px、C/Q 曲线连线、一次画对）。落位：

| 场景 | 位置 | 引用方式 |
|---|---|---|
| 能力卡配图 | `$WS/books/<slug>/.cangjie/capabilities/resources/<cap-slug>.svg` | 卡片正文写资源名 + Bundle 该能力 `resources:` 声明 |
| DIGEST/OVERVIEW 配图 | `$WS/books/<slug>/assets/<名>.svg` | `![标题](assets/<名>.svg)` 相对路径 |

自查（error 必须清零）：
```bash
node $PLUGIN/vendor/svg-diagram/tools/svg-lint/bin/svg-lint.mjs <图.svg>
```

栅格图是另一条可选路径，不进入图件闸，也不写进能力卡的 `resources:`。只在操作者明确要求、且本机已有 `HCTI_API_ID` 与 `HCTI_API_KEY` 时，把**书树以外**的 HTML/CSS 交给：

```bash
$PY $PLUGIN/bridge/render_html_image.py --html <卡.html> --css <卡.css> --out <图.png> --ws $WS
```

先读 `$PLUGIN/vendor/html-css-to-image/SKILL.md`。密钥不写进仓库。`--check` 只确认客户端版本，不发起请求。输入若在 `books/` 或 `.work/`，脚本拒绝送出。没有密钥就停在说明，不要改用别的截图库顶替。

## 阶段二 — 桥接（逐字回源核验）

```bash
$PY $PLUGIN/bridge/cangjie_to_dsh.py --book-dir $WS/books/<slug> --source <原书.txt|.md|.pdf> --task <slug> --ws $WS
```

它把原文落成 `$WS/.work/<task>/book_text.md`（PDF 自动抽取——**审计锚定对象永远是原始书文**），解析每张能力卡 R 段引文并**去空白逐字比对**，铸稳定池 id（`CJ-NNN`）生成 dsh 格式池与技能审计副本。任何引文对不上 ⇒ rc=1 红牌，回阶段一修 R 层。

## 阶段三 — 四闸审计（判态）

```bash
$PY $PLUGIN/bridge/run_audit.py --task <slug> --ws $WS
```

依次跑：证据包构建件 → G-66 池覆盖 → G-67 锚一致 → G-68 证据闭包 → 图件闸（svg 引用完整 + svg-lint 合规）。判态追加到 `$WS/.work/<task>/audit-verdict.md`（审计时间线）。

## 阶段四 — 放行或回炉

| 判态 | 去向 |
|---|---|
| 全绿 | 放行 → `$PY $PLUGIN/vendor/cangjie-skill/scripts/cangjie.py compile --bundle $WS/books/<slug>/.cangjie/capabilities --out <用户确认的安装目标> --output auto` |
| 桥接回源红 / G-67 红 | 回 cangjie **阶段 2**（R 层引文/日期锚修正），重跑桥接 |
| G-66 红（精选未落 R 层） | 回 cangjie **阶段 1/1.5**（补采候选/复核淘汰），重跑桥接 |
| G-68 红（闭包/漂移） | 先重跑审计入口；仍红查阶段 3/4 的 id 映射 |
| 图件闸红 | 按房规**修图或补引用**，重跑审计入口 |

回炉是常态不是失败——带着闸门给出的具体失败项（哪条引文、哪个 id、哪张图）定向修，不要整册重做。

## 判据口径（谁在查什么）

- **回源**：引文去空白后必须是原文逐字子串——防"引了但原文没有"。
- **G-66**：critical/high 能力（桥接打"总纲"标记）的引文必须落在某卡 R 层——防重要单元被静默漏掉。
- **G-67**：同行"日期×引文"必须在原文 400 字窗口共现——防张冠李戴的时间锚。
- **G-68**：技能引用的每个池 id 有 sha256 闭包且池不漂移——防"引了找不到原文/池改包未重建"。
- **图件闸**：引用的 svg 必须存在、所有 svg 过 lint error=0——防断链与烂图。

## 质量红线

1. 没有原文不蒸馏；引文 ≤150 字/段（英文 ≤100 词）。
2. 合成演练不得冒充书中案例；A1 无原书案例时如实标注。
3. 审计全绿前不 compile、不安装。
4. 淘汰项（`rejected/`）保留理由；重要缺口如实登记，不虚报零遗漏。
5. 图与正文一致——数据变了图必须跟着变；与正文矛盾的图比没图更糟。
6. 版权合规由使用者按原书授权判断；本工作流只保证"准则可执行、引文可核验"。

## 生态位

- **cangjie-skill**（随包于 `$PLUGIN/vendor/`）：蒸馏方法论与流程的权威定义。
- **dsh-distillation-director**（同上）：三闸判态的权威实现，本地脚本零 API 成本。
- **svg-diagram**（同上）：出图房规与 lint。图件闸只认它。
- **html-css-to-image**（同上，v0.3.0）：可选栅格出图。审计仍全本地、零 API 成本；这个客户端只有显式出图且密钥齐全时才访问网络。
- 本技能只做编排与判态收口；上游规范以各 vendor 的 SKILL.md/README 为准，冲突时以 vendor 原文为准并在此登记偏差。svg 与栅格冲突时，以 svg 为审计对象。
