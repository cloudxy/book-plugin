# -*- coding: utf-8 -*-
"""run_audit.py —— 组合流水线的审计入口（判态闸）

对已桥接的任务（.work/<task>/，由 bridge/cangjie_to_dsh.py 生成）依次运行：
  0) build_evidence_pack.py   官方证据包构建件（G-68 的输入）
  1) check_pool_coverage.py   G-66 池覆盖闸（精选条目须落 R 层）
  2) check_anchor_consistency.py  G-67 锚一致性闸（日期×引文须在源文窗口内共现）
  3) check_evidence_closure.py    G-68 证据闭包闸（引用 id 闭包 + 池不漂移）

用法：python bridge/run_audit.py --task <slug> [--ws <工作区根>]
判态（全闸 rc 收口）：
  全绿  ⇒ 放行：可进 cangjie 阶段 5（compile 编译交付）
  G-66 红 ⇒ 回炉 cangjie 阶段 1/1.5（补采候选 / 复核淘汰理由），再重跑桥接
  G-67 红 ⇒ 回炉 cangjie 阶段 2（R 层引文与日期锚修正），再重跑桥接
  G-68 红 ⇒ 先重跑本入口（重建证据包）；仍红则查阶段 3/4 的 id 引用映射
"""
import argparse
import io
import os
import subprocess
import sys

from book_skill_common import (ContractError, bridge_state, procedure_hash,
                              read_json, source_hashes, write_json)

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 上游 tools/ 脚本里有少量非裸字符串内联 \s（Python 3.12+ 仅告警、不影响行为），
# 只压这一类噪音，不压其他告警。
ENV = dict(os.environ, PYTHONWARNINGS='ignore::SyntaxWarning')


def resolve_ws(explicit):
    if explicit:
        return os.path.abspath(explicit)
    for k in ('DSH_DISTILL_ROOT', 'DSH_WORKSPACE_ROOT'):
        v = (os.environ.get(k) or '').strip()
        if v and os.path.isdir(v):
            return os.path.abspath(v)
    d = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    for _ in range(6):
        if os.path.isdir(os.path.join(d, '.dsh')):
            return d
        d = os.path.dirname(d)
    sys.exit('🔴 未找到工作区根 —— 请 --ws 指定，或设 DSH_DISTILL_ROOT')


GATES = [
    ('构建件', 'tools/build_evidence_pack.py', '重跑本入口；仍红则查阶段 3/4 的 id 引用映射'),
    ('G-66 池覆盖', 'tools/check_pool_coverage.py', '回炉 cangjie 阶段 1/1.5（补采候选/复核淘汰），重跑桥接'),
    ('G-67 锚一致', 'tools/check_anchor_consistency.py', '回炉 cangjie 阶段 2（R 层引文/日期锚修正），重跑桥接'),
    ('G-68 证据闭包', 'tools/check_evidence_closure.py', '先重跑本入口（重建证据包）；仍红则查阶段 3/4 id 映射'),
    ('图件（svg）', 'bridge/check_diagrams.py', '按 vendor/svg-diagram/SKILL.md 修图或补引用，重跑本入口'),
]

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description='dsh 三闸审计入口（组合流水线判态）')
    ap.add_argument('--task', required=True, help='任务 slug（.work/<task>）')
    ap.add_argument('--ws', default=None, help='工作区根（默认自动解析）')
    a = ap.parse_args()
    ws = resolve_ws(a.ws)
    tdir = os.path.join(ws, '.work', a.task)
    if not os.path.isdir(tdir):
        sys.exit('🔴 任务不存在：%s（先跑 bridge/cangjie_to_dsh.py）' % tdir)
    tools = os.path.join(ws, 'tools')
    env = dict(ENV, DSH_DISTILL_ROOT=ws, DSH_WORKSPACE_ROOT=ws)
    try:
        manifest = read_json(os.path.join(tdir, 'bridge-manifest.json'))
        inputs = read_json(os.path.join(tdir, 'bridge-inputs.json'))
        if (inputs.get('valid') is not True
                or inputs.get('source') != source_hashes(manifest['source'])
                or inputs.get('procedures') != procedure_hash(manifest['book_dir'])
                or inputs.get('bridge_state') != bridge_state(tdir)):
            raise ContractError('桥接输入或审计副本已变更，请重新桥接')
    except (ContractError, OSError, KeyError) as exc:
        write_json(os.path.join(tdir, 'audit-result.json'), {'status': 'failed', 'error': str(exc)})
        print('🔴 %s' % exc)
        return 1

    def script_path(script):
        # tools/* 装在用户工作区；bridge/* 与本入口同目录（HERE 即 bridge 目录本身，勿再拼前缀）
        if script.startswith('tools/'):
            return os.path.join(ws, *script.split('/'))
        return os.path.join(HERE, os.path.basename(script))

    results = []
    for label, script, remedy in GATES:
        cmd = [sys.executable, script_path(script), '--task', a.task]
        print('\n' + '═' * 72)
        print('▶ %s —— %s' % (label, script))
        print('═' * 72)
        r = subprocess.run(cmd, env=env, cwd=ws)
        results.append((label, r.returncode, remedy))

    print('\n' + '─' * 72)
    print('判态（任务：%s）' % a.task)
    print('─' * 72)
    reds = [(l, rem) for l, rc, rem in results if rc != 0]
    for label, rc, _ in results:
        print('  %s %-12s rc=%d' % ('✔' if rc == 0 else '🔴', label, rc))
    verdict = 'PASS' if not reds else 'FAIL(%d)' % len(reds)
    write_json(os.path.join(tdir, 'audit-result.json'), {
        'status': 'passed' if not reds else 'failed', 'task': a.task,
        'source': inputs['source'], 'procedures': inputs['procedures'],
        'audit_state': bridge_state(tdir, include_evidence=True),
        'gates': {label: rc for label, rc, _ in results},
    })
    if not reds:
        print('\n结论：✔ 程序四闸放行 —— 可编译程序依赖；整书思想与口吻另需语义及实际回答验收')
    else:
        print('\n结论：🔴 %d 闸红 —— 按下述去向回炉后重跑桥接与本入口：' % len(reds))
        for label, remedy in reds:
            print('  · %s ⇒ %s' % (label, remedy))
    with io.open(os.path.join(tdir, 'audit-verdict.md'), 'a', encoding='utf-8', newline='\n') as fh:
        import time
        fh.write('- %s %s（%s）\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), verdict,
                                     '；'.join('%s rc=%d' % (l, rc) for l, rc, _ in results)))
    return 0 if not reds else 1


if __name__ == '__main__':
    sys.exit(main())
