# 仓颉 Skill 2.5.0 — book-workflow 随包快照

快照日期：2026-11-01；上游版本号仍为 2.5.0。
源码固定提交：https://github.com/kangarooking/cangjie-skill/commit/a28de55ba881b9928956a55048f743f7a9e3b23e

本次同步上游两项修复：`also_read` 同时支持 capability_id 和 slug，生成补读链接与影响分析保持一致；缺少 PyYAML 时 CLI 和 doctor 仍可运行并给出安装指引。

保留 methodology、extractors、templates、scripts、schemas、docs、benchmarks 和 tests 等运行配套文件，不能只复制 SKILL.md。本目录不携带上游网站、示范书籍或用户配置。上游源码和 LICENSE 原样保留；本 README 与 BUILD_INFO.json 为 book-workflow 的快照说明，不是上游新发布版本。

Python 工具需要 Python 3.10+，PyYAML 为基础依赖。可运行：

```sh
python3 scripts/cangjie.py doctor
python3 -m unittest discover -s tests -v
```

完整 2.5.0 能力说明见 docs/releases/v2.5.0.md；源码提交、文件清单及哈希见 BUILD_INFO.json。
