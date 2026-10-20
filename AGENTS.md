# AGENTS.md — book-workflow 工作区

book-workflow：知识蒸馏闭环工作流插件，v0.2.1。**cangjie-skill 把书炼成 Skill（生成）→ svg-diagram 画房规 SVG（出图）→ dsh 三闸+图件闸逐字回源（审计）→ 判态放行或回炉。** html-css-to-image 0.3.0 是可选栅格出图，无密钥不调用、不进四闸。 本目录既是蒸馏工作区，也是插件的**开发与编辑现场**——skills/commands/bridge/vendor 就在这里更新；zcode 经 `~/.zcode/cli/config.json` 的 `plugins.dirs` 直接注册本目录加载（改源文件后开新会话即生效，无副本同步）。上游 https://github.com/cloudxy/book-plugin 是唯一共同源；其他机器按需克隆到 `~/.zcode/local-plugins/book-workflow` 并注册该克隆，`git pull` 后开新会话加载更新。

## 目录

```
book-workflow/
├── skills/book-workflow/   工作流权威定义（五阶段编排：自举→蒸馏→出图→桥接→审计判态）
├── skills/book*/          book / book-audit / book-diagram 快捷技能，转到 commands/
├── commands/               三个斜杠命令：book（全流程）、book-audit（只审计）、book-diagram（只出图）
├── bridge/                 桥接器与审计入口：cangjie_to_dsh.py / run_audit.py / check_diagrams.py / render_html_image.py
├── scripts/bootstrap.py    按工作区自举（.venv + dsh 闸门套装，幂等）
├── vendor/                 四件随包依赖（自包含）：cangjie-skill v2.5.0-refresh ｜ dsh v4.9.26 ｜ svg-diagram c30c9e3 ｜ html-css-to-image v0.3.0
├── tests/                  e2e 自证（12 项断言：正向绿 + 六组篡改必红）与合成样例 fixtures
├── tools/ .dsh/            闸门套装（bootstrap 装入本工作区的运行件，可重建）
├── books/ .work/           蒸馏产物与审计任务（私有，不进远端）
├── .claude/ .agents/ .grok/ 各 CLI 项目级软链 → 仓内 skills/commands
├── .zcode-plugin/ .claude-plugin/ plugin.json .agents/plugins/marketplace.json
│                           打包清单：zcode / claude+grok / 通用 / codex 市场四种宿主格式
└── Makefile README.md      开发入口（doctor/e2e/bridge/audit/compile）与工作流文档
```

## 五端接入（全部项目级，共用仓内源文件）

| CLI | 挂载点 | 入口 |
|---|---|---|
| claude | `.claude/skills`、`.claude/commands`（软链） | `/book`、`/book-audit`、`/book-diagram` |
| codex | `AGENTS.md` + `.agents/skills` | `$book`、`$book-audit`、`$book-diagram`、`$book-workflow`；`/skills` 查看 |
| kimi | `AGENTS.md` + `.agents/skills` | `/skill:book`、`/skill:book-audit`、`/skill:book-diagram`、`/skill:book-workflow` |
| grok | `AGENTS.md` + `.grok/skills`（原生入口） | `/book`、`/book-audit`、`/book-diagram`、`/book-workflow` |
| zcode | 本目录（`plugins.dirs` 直注册；其他机器可克隆到 `~/.zcode/local-plugins/book-workflow` 再注册该克隆） | `/book`、`/book-audit`、`/book-diagram` |

项目级入口随仓库存在；在本目录启动相应 CLI 的新会话，完成宿主首次要求的项目信任后即可使用。四端均可直接描述“拆书/蒸馏并审计”，按 `skills/book-workflow/SKILL.md` 执行。Claude 通过 `CLAUDE.md` 引入本文件。更改入口后开新会话刷新发现结果。

Codex 若显示插件命名空间，按 `/skills` 中的完整名称调用，例如 `$book-workflow:book`（本机当前发现名），仍是仓内同一份技能。

快捷技能仅转到 `commands/`；全部命令先读取主技能，再按全流程／只审计／只出图限定范围。解析软链后定位仓库根，不从 `.agents`、`.claude`、`.grok` 挂载路径推算脚本位置。跨工作区使用时，技能会先跑 `scripts/bootstrap.py` 自举目标工作区（幂等）。

## 常用意图

```text
/book 拆《某书》：~/Books/某书.txt
/book 蒸馏这个播客转写稿并审计
/book 继续                    ← 断点续跑（读 books/<slug>/PIPELINE_STATE.md）
/book-audit --task <slug>     ← 只审计已有产物
/book-diagram 给复利能力卡画流程图
```

判态口径：四闸全绿 → 放行 `compile` 编译交付；红项按映射表回炉（回源/G-67→阶段2，G-66→阶段1/1.5，G-68→重建证据包，图件→修图补引用）。完整流程、判据与红线见 [README.md](README.md) 与 `skills/book-workflow/SKILL.md`。

## 维护纪律

- **单一事实源**：skills/commands/bridge/vendor 只在本目录改；五端挂载点全是软链或清单，改完即更新，无副本同步。
- **同步走 GitHub**：上游 `cloudxy/book-plugin`；改动 `git pull → commit → push`（pre-commit 钩子兜底拦截私有内容）。其他机器是否克隆、克隆到哪里，由各机器自定。
- **vendor 升级**：替换 `vendor/<名>/` → 递增 `.zcode-plugin/plugin.json` 等四份清单版本与 SKILL.md 的 `vendors:` 登记 → `make doctor && make e2e` 回归。
- **回归**：`make e2e`（12 项断言，含负向防假绿）+ `make doctor`。

### vendor 许可证（再分发边界）

| vendor | 许可证 | 边界 |
|---|---|---|
| cangjie-skill | MIT | 宽松；保留其 LICENSE 与署名即可 |
| svg-diagram | MIT | 同上 |
| dsh-distillation-director | **AGPL-3.0** | 允许随仓库整体再分发（完整保留其 LICENSE 与源码）；**不得改动其源码**，除非接受改动部分以 AGPL 开源。本仓库与其边界是**进程级调用**（bridge 调 tools/ 脚本），属聚合而非衍生 |
| html-css-to-image | MIT | 上游 Python 客户端 0.3.0 快照不改源码；`SKILL.md` 只是本仓库的调用说明。进程级调用 `bridge/render_html_image.py`。无密钥不访问网络，不进四闸 |

## 私有内容（硬约束）

书稿原文、蒸馏产物与审计任务是使用数据，**不进远端仓库**：`books/`、`.work/`、`.venv/`、`tools/`、`.dsh/` 已在 `.gitignore`/`.zcodeignore` 忽略（tools/.dsh 可由 bootstrap 重建）。
