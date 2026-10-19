# book-workflow — cangjie × dsh × svg-diagram 知识蒸馏工作流

**cangjie-skill 把书"炼"成 Skill（生成侧），dsh-distillation-director 对炼出来的每一件做"回源验真"（审计侧），svg-diagram 把书里的框架与流程画成符合房规的 SVG 图（出图侧）。**
本工作区把三者拼成 **蒸馏 → 桥接 → 审计（含图件闸）→ 回炉或放行** 的闭环，全部本地脚本执行，审计侧零 API 成本。

> **五端插件**：本仓库既是蒸馏工作区，也是插件本体（ncc-workflow 同款模式）——单一事实源 `skills/`+`commands/`+`bridge/`+`vendor/`，
> Claude/Codex/Kimi/Grok/ZCode 经项目级挂载点接入，改文件即更新，无副本同步。接入表与维护纪律见 [AGENTS.md](AGENTS.md)。
> 共同源 [cloudxy/book-plugin](https://github.com/cloudxy/book-plugin)；vendor 许可证（含 dsh 的 AGPL-3.0 再分发边界）见 AGENTS.md 维护纪律一节。

```
┌─────────────────┐   ┌──────────────┐   ┌────────────────────────────┐
│ cangjie-skill    │   │ bridge/      │   │ tools/ + bridge/（审计闸）  │
│ RIA-TV++ 阶段0-4 │──▶│ cangjie_to_dsh│──▶│ G-66 池覆盖                │
│ books/<slug>/    │   │ 逐字回源核验 │   │ G-67 锚一致                │
│        │         │   │ .work/<task>/│   │ G-68 证据闭包              │
│ svg-diagram 出图 │   └──────────────┘   │ 图件闸（svg-lint+引用完整）│
└─────────────────┘                      └─────────────┬──────────────┘
        ▲                                               │
        └────────── 回炉（按判态映射表） ◀── 红 ──┤── 绿 → 阶段5 compile 交付
```

## 目录结构

```
book-workflow/
├── vendor/
│   ├── cangjie-skill/                # 生成侧：cangjie v2.5.0（2026-09-13 refresh 版，sha256 已核验）
│   │   ├── SKILL.md                  #   蒸馏元技能（给 Agent 读的流程定义）
│   │   └── scripts/cangjie.py        #   确定性 CLI（doctor/compile/eval/…）
│   ├── dsh-distillation-director/    # 审计侧：dsh v4.9.26 发行包（原包存档）
│   └── svg-diagram/                  # 出图侧：bybit-exchange/svg-diagram @ c30c9e3（MIT）
│       ├── SKILL.md                  #   SVG 出图房规（给 Agent 读的绘图规范）
│       └── tools/svg-lint/           #   零依赖 Node 版 SVG 风格检查器（12 项检查）
├── skills/book-workflow/SKILL.md     # 工作流权威定义（五阶段编排；五端共用）
├── skills/book*/SKILL.md            # 三个快捷技能 → commands/，供 Codex/Kimi/Grok 发现
├── commands/                         # 斜杠命令：book / book-audit / book-diagram
├── AGENTS.md CLAUDE.md               # 五端工作区入口（codex/kimi 读 AGENTS.md）
├── .claude/ .agents/ .grok/           # 各 CLI 项目级软链 → 仓内 skills/commands
├── .zcode-plugin/ .claude-plugin/ plugin.json .agents/plugins/marketplace.json
│                                     # 四种宿主清单（zcode / claude+grok / 通用 / codex 市场）
├── tools/                            # dsh 闸门套装（init_workspace 装入，100 件）
├── bridge/
│   ├── cangjie_to_dsh.py             # 桥接器：cangjie 产物 → dsh 审计结构 + 逐字回源
│   ├── check_diagrams.py             # 图件闸：svg 引用完整 + svg-lint 风格合规
│   └── run_audit.py                  # 审计入口：证据包构建 + 三闸 + 图件闸 + 判态
├── scripts/bootstrap.py              # 按工作区自举（.venv + 闸门套装，幂等）
├── tests/
│   ├── fixtures/                     # 合成样例（演示之书 + 能力卡 + 过闸配图）
│   └── e2e_test.py                   # 端到端自证（正向绿 + 六组篡改必红）
├── books/                            # cangjie 蒸馏工作目录（make new-book 脚手架起手）
├── .work/<task>/                     # dsh 审计任务结构（桥接器生成；含判态留痕 audit-verdict.md）
├── .dsh/gate-kit/workspace.json      # 闸门工作区配置
└── .venv/                            # Python 3.14 + PyYAML + PyMuPDF（另需 node 供 svg-lint）
```

## 在 Codex / Grok / Kimi / Claude 中直接使用

在仓库根目录启动 `codex`、`grok`、`kimi` 或 `claude` 的新会话，完成宿主首次要求的项目信任。项目入口已随仓库配置，无需再安装插件副本。

| 平台 | 全流程 | 只审计 | 只出图 | 项目技能目录 |
|---|---|---|---|---|
| Codex | `$book <原文路径>` | `$book-audit --task <slug>` | `$book-diagram <描述>` | `.agents/skills/` |
| Grok | `/book <原文路径>` | `/book-audit --task <slug>` | `/book-diagram <描述>` | `.grok/skills/` |
| Kimi | `/skill:book <原文路径>` | `/skill:book-audit --task <slug>` | `/skill:book-diagram <描述>` | `.agents/skills/` |
| Claude | `/book <原文路径>` | `/book-audit --task <slug>` | `/book-diagram <描述>` | `.claude/skills/` + `.claude/commands/` |

也可以直接说“拆这本书并审计：<原文路径>”。主技能名为 `book-workflow`；三个快捷技能只转发到同名 `commands/*.md`，保持流程单一来源。上表是 **CLI 对话中的输入**，不要直接粘到 shell 执行。

Codex 若以插件命名空间展示技能，使用 `/skills` 中的完整名称；本机加载结果为 `$book-workflow:book`、`$book-workflow:book-audit`、`$book-workflow:book-diagram` 和 `$book-workflow:book-workflow`，均指向本仓库。

入口缺失时先重开会话：Codex 用 `/skills`，Grok 用 `/skills` 或终端中的 `grok inspect`，Kimi 输入 `/skill:`，Claude 输入 `/` 查看发现结果。Grok 未信任项目时会跳过项目技能与规则，需在交互界面完成项目信任。账号登录沿用各 CLI 已有设置。

发现与调用约定：[OpenAI Docs](https://learn.chatgpt.com/docs/build-skills)、[Grok 官方文档](https://docs.x.ai/build/features/skills-plugins-marketplaces)、[Kimi Code 官方文档](https://moonshotai.github.io/kimi-code/en/customization/skills)、[Claude Code 官方文档](https://code.claude.com/docs/en/skills)。

## 环境与自检

- Python ≥3.10（本工作区用 `.venv`，3.14.4）；`pip install PyYAML PyMuPDF`
- Node（任意现代版，本机 v25）——图件闸的 svg-lint 依赖；缺失时该闸判"不适用"
- 一键体检：

```bash
make doctor          # cangjie doctor + dsh 三闸 selftest + node/svg-lint 冒烟
make e2e             # 端到端：合成样例全链路（12 项断言，含负向防假绿）
```

## 五阶段用法

### 阶段一 — cangjie 蒸馏（生成侧）

```bash
make new-book BOOK=<slug> TITLE=<书名>     # 脚手架：books/<slug>/ + PIPELINE_STATE.md
```

在支持 Skill 的 Agent 宿主里加载 `vendor/cangjie-skill/SKILL.md`，按 RIA-TV++ 跑到**阶段 4（压力测试）之后、阶段 5（编译交付）之前**停下。此时 `books/<slug>/` 已有完整中间产物：`verified.md`、`candidates/`、`rejected/`、`.cangjie/capabilities/`（Bundle + 能力卡）。

> 原则：**先审计后编译**——阶段 5 的 compile 只对过闸的 Bundle 做。

### 阶段 1.5 — 出图（svg-diagram，按需）

能力卡或 DIGEST 需要配图时，加载 `vendor/svg-diagram/SKILL.md` 按房规手绘 SVG（详见下文"出图规范"）。图的落位：

| 场景 | 位置 | 引用方式 |
|---|---|---|
| 能力卡配图（框架/流程/计算类） | `books/<slug>/.cangjie/capabilities/resources/<cap-slug>.svg` | 卡片正文写资源名，并在 Bundle 该能力的 `resources:` 列表声明（随编译进产物） |
| DIGEST.md / BOOK_OVERVIEW.md 配图 | `books/<slug>/assets/<名>.svg` | `![标题](assets/<名>.svg)` 相对路径 |

画完自查：`make lint-svg FILE=books/<slug>/.cangjie/capabilities/resources/<cap-slug>.svg`

### 阶段二 — 桥接（回源核验）

```bash
make bridge BOOK=books/<slug> SRC=<原书.txt|.md|.pdf>
```

桥接器做五件事：
1. 原文全文落 `.work/<task>/book_text.md`（PDF 自动用 PyMuPDF 抽取）——审计的回源锚定对象始终是**原始书文**，不是 cangjie 的中间产物；
2. 解析每张能力卡的 R 段引文，逐条与原文**去空白逐字比对**（与闸门同一把 qnorm 尺子）——任何一条对不上即 rc=1 红牌；
3. 给每条引文铸稳定池 id（`CJ-NNN`，`id-map.json` 保证重跑不换号），生成 dsh 格式候选池 `verified.md`；
4. 产出技能审计副本（`skills/<卡slug>/SKILL.md` = 卡片原文 + 尾部"审计索引"）与 `bridge-report.md`（逐条回源结果表）；
5. 写 `bridge-manifest.json`（书目录/原文路径/时刻）——图件闸据此定位书树。

### 阶段三 — 四闸审计（判态）

```bash
make audit TASK=<slug>
```

依次跑官方证据包构建件、dsh 三闸、图件闸，收口判态并追加到 `.work/<task>/audit-verdict.md`（审计时间线）。

### 阶段四 — 放行或回炉

| 判态 | 去向 |
|---|---|
| 全绿 | 放行 → cangjie 阶段 5：`make compile BOOK=books/<slug> OUT=<目标>` |
| 桥接回源红 / G-67 红 | 回炉 cangjie **阶段 2**（修正 R 层引文与日期锚），重跑桥接 |
| G-66 红（精选未落 R 层） | 回炉 cangjie **阶段 1/1.5**（补采候选、复核淘汰），重跑桥接 |
| G-68 红（闭包/漂移） | 先重跑审计入口（重建证据包）；仍红查**阶段 3/4** 的 id 引用映射 |
| 图件闸红 | 按 `vendor/svg-diagram/SKILL.md` **修图或补引用**，重跑审计入口 |

## 判据口径（谁在检查什么）

- **桥接回源**：引文去空白后必须是原文的逐字子串——防"引了但原文没有"。
- **G-66 池覆盖**：`importance=critical/high` 的能力（桥接打"总纲"精选标记）其引文必须落在某张卡的 R 层引用里——防"重要单元被漏掉/淘汰后无人知晓"。
- **G-67 锚一致**：同一行内"日期 × 引文"必须在原文 400 字窗口内共现——防"张冠李戴的时间锚"。
- **G-68 证据闭包**：技能引用的每个池 id 都有 sha256 闭包且池未漂移——防"引了但找不到原文/池被改包未重建"。
- **图件闸**：书树 .md 引用的 svg 必须存在（防断链）、书树所有 svg 过 svg-lint error=0（防烂图）；warning 黄牌、孤儿图黄牌；`--strict` 可升红。

## 出图规范（svg-diagram 房规摘要）

完整规范见 `vendor/svg-diagram/SKILL.md`（586 行），关键纪律：

- **SVG，不用 ASCII art**；图放文档旁 `assets/`（能力图放 Bundle `resources/`），markdown 用相对路径引用，不内联 XML。
- **一次画对**：CJK 字体栈（PingFang SC → Microsoft YaHei → Noto Sans CJK SC 顺序固定）、浅底色兜底、五组语义配色、盒高 = 字号×3（每加一行 +1.5×字号）、盒间距 ≥25px、连线用 C/Q 曲线不留直角、箭头两端各留 5px。
- **文字不压线、线不穿盒**（箭头止于盒处除外）；标题居中于**内容中心**而非画布中心；viewBox 边距 20–25px 对称。
- **文档数据变了图必须跟着变**——与正文矛盾的图比没图更糟（图件闸的引用完整检查兜住断链，风格检查兜住烂图）。
- 每行文字用独立 `<text>` 元素（tspan 多行会被按单行估宽误报）；尺寸属性写裸数字不带单位。
- 画完跑 `make lint-svg FILE=…`；error 必须清零，warning 尽量清零（审计 `--strict` 模式下 warning 也拦）。

## 设计说明与已知边界

- **非原生集成**：三个工具互不知晓；桥接层承担格式契约（cangjie YAML 单元/卡片 R 段 → dsh `### CJ-NNN` 池 + `（`CJ-NNN`：出处）` 引用语法，id 语法由 `_bandid.py` 唯一真源约束）。
- **图件闸遍历用 os.walk**：Python `glob` 的 `**` 按壳规则跳过 `.cangjie` 等点开头目录，会漏掉整棵侧车层（e2e 抓出过这个假绿）。
- **dsh 宿主层闸门不在射程**：`gate_start.py`（开工自证）、`preflight/postflight` 等面向 DSH 宿主自家蒸馏纪律，在无 DSH 宿主的机器上判"不适用"；本流水线只启用其**内容事实性**三闸。
- **G-66 的语义局限**："漏没漏重要单元"本质是语义判断；本流水线把它落地为可机器判定的形式（critical/high 必须落 R 层），"什么算 critical"仍由 cangjie 阶段 1.5/1.6 的判定与人工轻确认承担。
- **图不进引文审计**：SVG 是派生物不是原书引文，回源三闸不管图；图件闸只管"图本身合规 + 引用不断链"，图的**内容正确性**（与正文一致）由出图纪律与人工复核承担。
- **版权口径**：dsh 侧不含任何书籍原文；桥接产物（`.work/`）含去空白逐字引文仅用于本地审计，cangjie 红线（中文引文 ≤150 字/段）由桥接报告超限警示辅助盯守。最终交付物的版权合规由使用者按原书授权自行判断。
- **升级**：`vendor/` 下三个包是固定版本存档（cangjie v2.5.0-refresh / dsh v4.9.26 / svg-diagram @ c30c9e3）；升级时替换 vendor 目录后重跑 `init_workspace.py` 与 `make e2e` 回归。

## 快捷入口

```bash
make doctor                          # 全环境体检（含 node/svg-lint 冒烟）
make e2e                             # 端到端自证（12 项断言）
make new-book BOOK=<slug> TITLE=<书名>  # 新书脚手架
make bridge BOOK=books/<slug> SRC=<原文> [TASK=<slug>]
make audit TASK=<slug>               # 四闸判态（留痕 audit-verdict.md）
make lint-svg FILE=<图.svg>          # 单图风格检查
make compile BOOK=books/<slug> OUT=<安装目标>   # 判态全绿后的阶段5
```
