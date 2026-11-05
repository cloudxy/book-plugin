# bridge 模块 ↔ 测试所有权映射

每个 `bridge/*.py` 模块要么有属主测试文件，要么在此显式登记不测理由。
`tests/test_coverage_map.py` 强制本表与 bridge/ 目录一致：新增模块不改表 ⇒ `make e2e` 红；
表里登记了不存在的模块 ⇒ 同样红。缺口从"靠人翻"变成"闸门可见"。

| 模块 | 属主测试 | 说明 |
|---|---|---|
| `author_persona.py` | test_persona_contracts | episodes 生成合同经 thinking_audit 变异用例直测 |
| `batch_runner.py` | test_batch_runner、test_pipeline_contracts | 产线分支/动作卡/过滤 + 多书状态推进 |
| `book_skill_common.py` | test_thinking_contracts、test_persona_contracts | verify_package/tree_hashes/digest 等在候选与发布用例直测，其余经各合同间接 |
| `build_book_skill.py` | test_thinking_contracts、test_persona_contracts | 候选构建/发布/程序编译与旧安装保留 |
| `cangjie_to_dsh.py` | test_gates_e2e、test_thinking_contracts | 正向桥接+篡改回源；英文引文上限与缺 R 层 |
| `check_diagrams.py` | test_gates_e2e | 坏图（svg-lint error）与引用缺件两负向 |
| `distill_skill.py` | test_production_contracts | build/verify 与坏包隔离重建；v2 声音/现实边界与用途资产（episodes/habits/PROFILE）、可移植路径 |
| `eval_book_skill.py` | test_thinking_contracts、test_persona_contracts | v1/v2 评测准备、盲评包、报告与发布绑定 |
| `export_portfolio.py` | test_pipeline_contracts | 登记/导出/未过闸拦截/文风锚/逐字守卫 |
| `host_worker.py` | test_host_worker | 假 codex CLI 注入 PATH；信封/事件解析/失败路径 |
| `l1_extract.py` | test_pipeline_contracts | L1 init/check 十分位与哈希闸 |
| `production.py` | test_production_contracts、test_production_loop | claim/collect/预算/失效传播/sync/隔离重建；错误分类与退避、租约过期仍收、策略/解除阻塞留痕、0.5.0 缓存键校验迁移、L1/L3 档位、正文边界 |
| `production_common.py` | test_production_contracts、test_host_worker | atomic_json/decode_result/错误分类；run_worker 经 Scheduling 假执行器用例 |
| `production_eval.py` | test_production_contracts、test_production_loop | 分轮隐藏/评审收集/报告/换宿主检出；按用途维度、失败须归因、宿主自行加载、保留题消费 |
| `production_loop.py` | test_production_loop | 评测→归因→定向返修→复评确认、交付、七项分项交付记录、构建绑定 |
| `production_metrics.py` | test_production_loop | 干预/自动返修/首次可用/一次通过/重复调用/token/失败归类；同范围对照 |
| `production_stages.py` | test_production_contracts、test_production_loop | 阶段模块合同与模板、分批复核/抽查及脚本汇总、分层抽样、复核/抽查失败路由、旧扁平指令包 |
| `render_html_image.py` | test_render_html_image | 仅守卫（banned/大小上限/无密钥拒绝）；无网络路径 |
| `run_audit.py` | test_gates_e2e | 四闸编排与判态留痕 |
| `skill_portfolio.py` | test_production_contracts、test_production_loop | 登记/可迁移导出/元数据篡改；v2 触发/输入/包版本/已测条件、待构建条目不计数 |
| `thinking_audit.py` | test_thinking_contracts、test_persona_contracts | v1/v2 来源闸全部变异用例 |
| `worker_schema.py` | test_worker_schema、test_production_contracts | 各阶段结构化合同与 examples origin 必填 |
| `workflow_optimizer.py` | test_workflow_optimizer、test_production_contracts | propose 有界实验（扁平指令/阶段模块）、跨书失败汇总、经验账本晋级规则、compare 绑定产线包 |

维护规则（见 docs/designs/testing/test-architecture.md）：

1. 新增 bridge 模块 ⇒ 同一提交给出属主测试或在此登记不测理由。
2. vendor 升级 ⇒ `test_vendor_regressions.py` 增对应行为回归。
3. 本表只登记 bridge 模块；tests/support/ 是测试代码，不在此列。
