# -*- coding: utf-8 -*-
"""e2e_test.py —— 组合流水线端到端自证

正向：桥接（逐字回源）→ 三闸全绿放行。
负向：篡改引文／删 R 层引用／错配日期×引文／漂移 sha，各闸必须变红（防假绿）。

用法：.venv/bin/python tests/e2e_test.py
退出码：0 = 全部通过；1 = 有失败项。
"""
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

WS = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PY = sys.executable
BRIDGE = os.path.join(WS, 'bridge', 'cangjie_to_dsh.py')
AUDIT = os.path.join(WS, 'bridge', 'run_audit.py')
FIX_BOOK = os.path.join(WS, 'tests', 'fixtures', 'books', 'demo-book')
FIX_SRC = os.path.join(WS, 'tests', 'fixtures', 'source-book.md')
ENV = dict(os.environ, PYTHONWARNINGS='ignore::SyntaxWarning')

FAILURES = []


def check(name, cond, detail=''):
    print('%s %s%s' % ('✔' if cond else '🔴', name, ('  | ' + detail.replace('\n', ' ')[:120]) if (detail and not cond) else ''))
    if not cond:
        FAILURES.append(name)


def run(*args):
    return subprocess.run(list(args), capture_output=True, text=True, env=ENV)


def rd(p):
    return open(p, encoding='utf-8').read()


def wr(p, s):
    open(p, 'w', encoding='utf-8', newline='\n').write(s)


def rebridge():
    r = run(PY, BRIDGE, '--book-dir', FIX_BOOK, '--source', FIX_SRC, '--task', 'demo-book')
    assert r.returncode == 0, r.stdout + r.stderr


def main():
    task = os.path.join(WS, '.work', 'demo-book')
    shutil.rmtree(task, ignore_errors=True)

    # ── 正向：桥接 + 判态 ──
    r = run(PY, BRIDGE, '--book-dir', FIX_BOOK, '--source', FIX_SRC, '--task', 'demo-book')
    check('桥接正向 rc=0（3 引文全部逐字回源）', r.returncode == 0, r.stdout + r.stderr)
    vm = rd(os.path.join(task, 'verified.md'))
    check('池条目数 = 3', vm.count('### CJ-') == 3, '实得 %d' % vm.count('### CJ-'))
    check('精选备注已打（critical/high → 总纲）', vm.count('备注：总纲｜') == 3, vm)

    r = run(PY, AUDIT, '--task', 'demo-book')
    check('判态全绿放行 rc=0（图件闸在役：图 1 引用完整）',
          r.returncode == 0 and '（图 1／引用完整' in r.stdout, r.stdout + r.stderr)

    # ── 负向 1：篡改 R 层引文 → 桥接回源必红 ──
    tmp = tempfile.mkdtemp(prefix='cj-tamper-')
    tbook = os.path.join(tmp, 'demo-book')
    shutil.copytree(FIX_BOOK, tbook)
    card = os.path.join(tbook, '.cangjie', 'capabilities', 'cards', 'compound-patience.md')
    wr(card, rd(card).replace('三十七倍', '三十八倍'))
    r = run(PY, BRIDGE, '--book-dir', tbook, '--source', FIX_SRC, '--task', 'demo-tamper')
    check('负向：篡改引文 ⇒ 桥接 rc=1 且报告未命中', r.returncode == 1 and '未命中 1' in r.stdout,
          r.stdout + r.stderr)
    shutil.rmtree(os.path.join(WS, '.work', 'demo-tamper'), ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)

    # ── 负向 2：删审计索引（R 层引用）→ G-66 精选未落 R 层必红 ──
    #    连同证据包一起删——否则旧 evidence-pool.md 里的 id 仍会被 G-66 扫到（假绿）
    sk = os.path.join(task, 'skills', 'decision-checklist', 'SKILL.md')
    wr(sk, rd(sk).split('\n---\n\n## 审计索引')[0] + '\n')
    os.remove(os.path.join(task, 'skills', 'decision-checklist', 'evidence-pool.md'))
    r = run(PY, os.path.join(WS, 'tools', 'check_pool_coverage.py'), '--task', 'demo-book')
    check('负向：删 R 层引用 ⇒ G-66 rc=1（精选未落 R 层）',
          r.returncode == 1 and '精选' in r.stdout, r.stdout + r.stderr)
    rebridge()

    # ── 负向 3：日期×引文错配 → G-67 必红 ──
    sk2 = os.path.join(task, 'skills', 'compound-patience', 'SKILL.md')
    wr(sk2, rd(sk2) + '- 「2018年6月19日，某基金因未做压力测试而清盘。」——2019.3.1 复盘记录\n')
    r = run(PY, os.path.join(WS, 'tools', 'check_anchor_consistency.py'), '--task', 'demo-book')
    check('负向：日期×引文错配 ⇒ G-67 rc=1', r.returncode == 1, r.stdout + r.stderr)
    rebridge()

    # ── 负向 4：证据包 sha 漂移 → G-68 必红 ──
    run(PY, os.path.join(WS, 'tools', 'build_evidence_pack.py'), '--task', 'demo-book')
    ep = os.path.join(task, 'skills', 'decision-checklist', 'evidence-pool.md')
    txt = rd(ep)
    i = txt.index('sha256=') + len('sha256=')
    flipped = ('1' if txt[i + 63] != '1' else '0')     # 翻转首个 sha 的末位，保持 64 位形态
    wr(ep, txt[:i + 63] + flipped + txt[i + 64:])
    r = run(PY, os.path.join(WS, 'tools', 'check_evidence_closure.py'), '--task', 'demo-book')
    check('负向：证据漂移 ⇒ G-68 rc=1', r.returncode == 1 and '漂移' in r.stdout + r.stderr,
          r.stdout + r.stderr)
    run(PY, os.path.join(WS, 'tools', 'build_evidence_pack.py'), '--task', 'demo-book')

    # ── 负向 5：坏图（标签溢出盒子，svg-lint error 级）→ 图件闸必红 ──
    svg = os.path.join(FIX_BOOK, '.cangjie', 'capabilities', 'resources', 'compound-patience.svg')
    good_svg = rd(svg)
    wr(svg, good_svg.replace('>每日变化率<', '>每日变化率与周期核对说明<'))   # 12 字 ≈144px ≫ 86px 盒宽
    r = run(PY, os.path.join(WS, 'bridge', 'check_diagrams.py'), '--task', 'demo-book')
    check('负向：坏图 ⇒ 图件闸 rc=1', r.returncode == 1 and 'svg-lint error' in r.stdout,
          r.stdout + r.stderr)
    wr(svg, good_svg)

    # ── 负向 6：引用了不存在的图 → 图件闸必红 ──
    card = os.path.join(FIX_BOOK, '.cangjie', 'capabilities', 'cards', 'compound-patience.md')
    good_card = rd(card)
    wr(card, good_card + '\n另一张图：resources/does-not-exist.svg\n')
    r = run(PY, os.path.join(WS, 'bridge', 'check_diagrams.py'), '--task', 'demo-book')
    check('负向：缺引用 ⇒ 图件闸 rc=1', r.returncode == 1 and '引用缺件' in r.stdout,
          r.stdout + r.stderr)
    wr(card, good_card)

    # ── 收口：恢复后应再次全绿（含图件闸与判态留痕）──
    r = run(PY, AUDIT, '--task', 'demo-book')
    check('恢复后四闸再次全绿（含图件闸）', r.returncode == 0, r.stdout + r.stderr)
    verdict = rd(os.path.join(task, 'audit-verdict.md'))
    check('判态留痕 audit-verdict.md 有 PASS 记录', 'PASS' in verdict, verdict)

    print('\n%s（%d/%d）' % ('✔ e2e 全部通过' if not FAILURES else '🔴 e2e 失败项：%s' % '、'.join(FAILURES),
                           12 - len(FAILURES), 12))
    return 1 if FAILURES else 0


if __name__ == '__main__':
    sys.exit(main())
