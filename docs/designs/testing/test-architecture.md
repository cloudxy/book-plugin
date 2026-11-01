# 测试体系架构（book-workflow v0.5.1 →）

本文是 tests/ 的架构基线：分层、所有权、不变量、决策记录与演进规则。
实施于 2026-11（提交 5c13004 / 7aaf2ad / 6fd0f81），配合同表 `tests/COVERAGE.md`。

## 1. 质量场景（这套测试要保证什么）

| 场景 | 判据 |
|---|---|
| 防假绿 | 每个闸门至少有一个负向用例证明它"会红"：篡改引文、删 R 层引用、错配日期、漂移 sha、坏图、缺引用图 |
| 隔离 | 任何测试不写仓库 `.work/`、不改 `tests/fixtures/`；整套可并发双跑 |
| 速度 | `make e2e` < 30s（2026-11 实测 97 项约 13s） |
| 缺口可见 | bridge 新增模块不登记测试 ⇒ `make e2e` 红（覆盖映射闸） |
| 多机零手工 | git pull 后仅靠 `scripts/bootstrap.py` 即可跑全量；无测试框架依赖 |
| 不冒充验收 | 全部用合成素材；结构绿 ≠ 真书/真人 Skill 验收通过（AGENTS.md 判态口径不变） |

## 2. 分层与运行

```
tests/
├── test_*_contracts.py   单元合同层：进程内直调 bridge 模块，变异驱动（thinking/persona/pipeline/production）
├── test_gates_e2e.py     集成闸门层：桥接→判态→6 组负向→恢复全绿，一条共享状态的连环用例
├── test_vendor_regressions.py  vendor 层：固定提交的行为回归（不改其源码）
├── test_*（模块级）      缺口补测层：host_worker/batch_runner/workflow_optimizer/worker_schema/render_html_image
├── test_coverage_map.py  映射合同：强制 COVERAGE.md 与 bridge/ 对齐（双向）
├── support/              共享脚手架：合成原文/条目/评审记录/闸门工作区装配
└── fixtures/             只读素材；测试一律拷贝副本后篡改
```

运行器：`python -m unittest discover -s tests -p 'test_*.py'`（Makefile `e2e`）；
分项用 `-k` 过滤（thinking-test 含 persona，与旧口径一致）。零非标准库依赖。

### 闸门隔离模式（关键决策的落地）

dsh 判闸件装于 tools/（bootstrap 从 vendor 重建，AGPL 不改源码），根定位第一优先级是
`DSH_DISTILL_ROOT`/`DSH_WORKSPACE_ROOT`（tools/_paths.py）。因此集成层在临时 ws 里
`copytree(tools) + mkdir .dsh`，桥接/判态带 `--ws`，闸门直调带 env+cwd
（`support/gates.py`）。与 `bridge/run_audit.py` 对 `--ws` 的实现同构。

## 3. 不变量（写新测试必须遵守）

1. **合成素材 only**：fixtures 与运行期生成的原文/回答/评审全部合成；不进真实书稿与人物素材。
2. **期望值独立**：断言值来自字面量/手算/合同文档，不得用被测实现自己的公式回算。
3. **oracle 不随实现漂移**：重构测试只做机械变换；改断言语义须单独提交并说明合同依据。
4. **fixtures 只读**：篡改一律在临时副本上进行（`shutil.copytree` 后再写）。
5. **无网络**：唯一联网件 render_html_image 只测守卫分支；host_worker 用假 CLI。
6. **顺序性要显式**：跨状态依赖的用例合并为单一 test 方法并注明（gates e2e 即此例），
   不依赖 unittest 的字母序。

## 4. 决策记录（ADR-lite）

| # | 决策 | 备选 | 理由 | 重访触发 |
|---|---|---|---|---|
| D1 | stdlib unittest，不引 pytest | pytest | 自包含自举纪律（AGENTS.md）；git pull 零手工 | 参数化/fixture 需求大到脚手架无法覆盖时 |
| D2 | discover 运行器 + `-k` 过滤 | Makefile 逐文件列举 | 新增文件零 Makefile 改动；列举会漏 | 无 |
| D3 | e2e 全临时 ws 隔离（env 定向） | 共享仓库 `.work/`；或改 tools 支持 `--ws` | 不改 dsh 源码（AGPL 边界）；并发安全；fixtures 永不被写 | 无 |
| D4 | COVERAGE.md 映射 + 合同测试 | coverage 工具；人工盘点 | 零依赖；缺口在 `make e2e` 强制可见；反向防登记尸块 | 若需要语句级覆盖率再引工具，映射表仍保留作所有权源 |
| D5 | 不加 CI（现阶段） | GitHub Actions | 回归纪律本机 make + pre-commit 兜底；CI 需网络装依赖 | 多机协作漂移实际发生时（草案见附录） |
| D6 | gates e2e 保持单一顺序用例 | 拆成独立方法 | 该用例的本质是共享任务状态的连环防假绿叙事；拆开会破坏"篡改→恢复→再全绿"语义 | 无 |

## 5. 演进规则

1. **新增 bridge 模块** ⇒ 同一提交给出属主测试或在 `tests/COVERAGE.md` 登记"不测理由"；
   `test_coverage_map.py` 两者都强制。
2. **vendor 升级** ⇒ `test_vendor_regressions.py` 增对应行为回归（对照 vendor/UPSTREAM.json）。
3. **改 gate/判态口径** ⇒ 先改负向用例（先红），再改实现（后绿）；防假绿叙事不得删步。
4. **support/ 只放机械脚手架**：两代合同（v1/v2）的 suite 形状与评审维度不共享，留在各自文件。
5. 文档计数不写死（"N 项断言"会腐烂）；数量以 `make e2e` 输出为准。

## 6. 运行手册

```bash
make e2e               # 全量（合同 + 集成闸门 + vendor + 映射）
make thinking-test     # thinking + persona 合同
make pipeline-test     # L1/组合清单/批量
make production-test   # 0.5 产线合同
make vendor-test       # 本仓回归 + 三个 vendor 上游测试
.venv/bin/python -B tests/test_gates_e2e.py   # 单文件直跑（任何 test_*.py 均可）
```

失败定位：合同测试失败看断言消息（多数含合同条款）；gates e2e 失败先看 🔴 行的
`| detail` 截断输出，再单跑该文件复现完整 stdout。

## 附录：CI 演进预留（未启用，D5）

```yaml
# .github/workflows/tests.yml（草案）
name: tests
on: [push, pull_request]
jobs:
  e2e:
    runs-on: macos-latest        # svg-lint 需 node；bootstrap 需网络装 PyPI 依赖
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.12'}
      - uses: actions/setup-node@v4
        with: {node-version: '22'}
      - run: python3 scripts/bootstrap.py "$PWD"
      - run: make doctor
      - run: make e2e
```

启用前置条件：确认上游仓库允许 Actions、密钥面为零（本仓测试不读任何密钥；
render 守卫测试显式剥离 HCTI_* 环境变量）。
