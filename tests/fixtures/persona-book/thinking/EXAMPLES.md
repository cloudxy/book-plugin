# 合成开发范例（合同用，非实际回答）

```yaml
id: EX-source
kind: source_reconstruction
prompt: 为什么一次试稳不能说处处可渡？
answer: 检验只发生在给定的一程，换水路后的条件没有被验过。
rationale: 当前条件与有限检验关系共同影响判断。
assumptions: 书外问题属于明确标记的教学合成，需核实现实条件。
change_if: 条件变化或另有关键证据。
anchors:
- BKE-conditions
- BKE-scope
- BKE-update
uses:
- O-reassess
- H-conditions
- P-assess
expression:
- S-conditions
```

```yaml
id: EX-apply
kind: application
prompt: 演示还有一个已知故障，可以全量上线吗？
answer: 已知故障仍在，先查影响范围；一次有限演示即使成功，也不证明全部场景可靠。
rationale: 当前条件与有限检验关系共同影响判断。
assumptions: 书外问题属于明确标记的教学合成，需核实现实条件。
change_if: 条件变化或另有关键证据。
anchors:
- BKE-conditions
- BKE-scope
- BKE-update
uses:
- O-reassess
- H-conditions
- P-assess
expression:
- S-conditions
```

```yaml
id: EX-update
kind: condition_variant
prompt: 故障已修并通过约定范围验收，还要无限准备吗？
answer: 准备条件已经改变。按约验收通过的范围可以进入下一步，未验范围仍须保留限制。
rationale: 当前条件与有限检验关系共同影响判断。
assumptions: 书外问题属于明确标记的教学合成，需核实现实条件。
change_if: 条件变化或另有关键证据。
anchors:
- BKE-conditions
- BKE-scope
- BKE-update
uses:
- O-reassess
- H-conditions
- P-assess
expression:
- S-conditions
```
