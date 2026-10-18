# 仓颉 Skill 2.5.0

补包日期：2026-09-13；版本号不变。
源码提交：https://github.com/kangarooking/cangjie-skill/commit/3adf9e61eec96edf34055432942f2952cfd7cfd9

解压后把完整的 `cangjie-skill/` 目录安装到宿主的 skills 目录，不能只复制 SKILL.md。
保留 methodology、extractors、templates、scripts、schemas 和 docs 等配套文件。
本包不包含私有书籍、原始材料、用户配置、缓存或网站工程。

## 主要优化

- 三关按来源充分性、可执行性和任务增益判断，单处完整机制可入选。
- 流程、公式、单位、表格字段、排障和案例类型提取更完整。
- 输出缺失不再从分母消失，新增数值/单位/容差检查。
- 生成的 Skill 可声明并携带 UTF-8 脚本和文本模板。

Python 工具需要 Python 3.10+；PyYAML 为基础依赖，jsonschema 用于 schema/回归检查。
在你自己的 Python 环境中准备依赖后，可运行：

```sh
python3 scripts/cangjie.py doctor
python3 -m unittest discover -s tests -v
```

完整更新说明见 docs/releases/v2.5.0.md。请核对 BUILD_INFO.json 的提交、补包日期和文件哈希。
这是同一版本的更新安装附件；GitHub 自动 Source code 归档仍对应首次发布标签。
