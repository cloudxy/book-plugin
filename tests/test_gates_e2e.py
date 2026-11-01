# -*- coding: utf-8 -*-
"""test_gates_e2e.py —— 组合流水线端到端自证（全临时工作区隔离版）

正向：桥接（逐字回源）→ 三闸全绿放行。
负向：篡改引文／删 R 层引用／错配日期×引文／漂移 sha／坏图／缺引用图，各闸必须变红（防假绿）。
收口：恢复后四闸再次全绿并留痕。

隔离：整条链跑在 setUpClass 建的临时 ws（tools/ 副本 + DSH_DISTILL_ROOT 定向），
不写仓库 .work/，不改 tests/fixtures/（书侧一律用副本）。
顺序性：本用例是一条共享任务状态的连环状态机（篡改→恢复→再全绿），
故为单一 test 方法内 12 项检查，与旧脚本 main() 流程逐一对应。

用法：.venv/bin/python -B tests/test_gates_e2e.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from support.gates import gate_env, prepare_gate_ws  # noqa: E402

PY = sys.executable
BRIDGE = ROOT / 'bridge' / 'cangjie_to_dsh.py'
AUDIT = ROOT / 'bridge' / 'run_audit.py'
FIX_BOOK = ROOT / 'tests' / 'fixtures' / 'books' / 'demo-book'
FIX_SRC = ROOT / 'tests' / 'fixtures' / 'source-book.md'


class GatesE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='book-gates-e2e-')
        cls.ws = prepare_gate_ws(Path(cls.temp.name), ROOT)
        cls.book = cls.ws / 'demo-book'                  # 书侧副本：fixtures 只读
        shutil.copytree(FIX_BOOK, cls.book)
        cls.source = cls.ws / 'source-book.md'
        shutil.copyfile(FIX_SRC, cls.source)
        cls.task = cls.ws / '.work' / 'demo-book'
        cls.failures = []

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_cmd(self, *args):
        return subprocess.run([str(a) for a in args], capture_output=True, text=True,
                              env=gate_env(self.ws), cwd=self.ws)

    def check(self, name, cond, detail=''):
        print('%s %s%s' % ('✔' if cond else '🔴', name,
                           ('  | ' + detail.replace('\n', ' ')[:120]) if (detail and not cond) else ''))
        if not cond:
            self.failures.append(name)

    def rd(self, p):
        with open(p, encoding='utf-8') as fh:
            return fh.read()

    def wr(self, p, s):
        open(p, 'w', encoding='utf-8', newline='\n').write(s)

    def bridge(self, book=None, task='demo-book'):
        r = self.run_cmd(PY, BRIDGE, '--book-dir', book or self.book,
                         '--source', self.source, '--task', task, '--ws', self.ws)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def rebridge(self):
        self.bridge()

    def test_gate_pipeline_sequence(self):
        # ── 正向：桥接 + 判态 ──
        r = self.bridge()
        self.check('桥接正向 rc=0（3 引文全部逐字回源）', r.returncode == 0, r.stdout + r.stderr)
        vm = self.rd(self.task / 'verified.md')
        self.check('池条目数 = 3', vm.count('### CJ-') == 3, '实得 %d' % vm.count('### CJ-'))
        self.check('精选备注已打（critical/high → 总纲）', vm.count('备注：总纲｜') == 3, vm)

        r = self.run_cmd(PY, AUDIT, '--task', 'demo-book', '--ws', self.ws)
        self.check('判态全绿放行 rc=0（图件闸在役：图 1 引用完整）',
                   r.returncode == 0 and '（图 1／引用完整' in r.stdout, r.stdout + r.stderr)

        # ── 负向 1：篡改 R 层引文 → 桥接回源必红（独立书副本 + 独立任务名）──
        tbook = self.ws / 'demo-tamper'
        shutil.copytree(self.book, tbook)
        card = tbook / '.cangjie' / 'capabilities' / 'cards' / 'compound-patience.md'
        self.wr(card, self.rd(card).replace('三十七倍', '三十八倍'))
        r = self.run_cmd(PY, BRIDGE, '--book-dir', tbook, '--source', self.source,
                         '--task', 'demo-tamper', '--ws', self.ws)
        self.check('负向：篡改引文 ⇒ 桥接 rc=1 且报告未命中',
                   r.returncode == 1 and '未命中 1' in r.stdout, r.stdout + r.stderr)
        shutil.rmtree(tbook, ignore_errors=True)
        shutil.rmtree(self.ws / '.work' / 'demo-tamper', ignore_errors=True)

        # ── 负向 2：删审计索引（R 层引用）→ G-66 精选未落 R 层必红 ──
        #    连同证据包一起删——否则旧 evidence-pool.md 里的 id 仍会被 G-66 扫到（假绿）
        sk = self.task / 'skills' / 'decision-checklist' / 'SKILL.md'
        self.wr(sk, self.rd(sk).split('\n---\n\n## 审计索引')[0] + '\n')
        os.remove(self.task / 'skills' / 'decision-checklist' / 'evidence-pool.md')
        r = self.run_cmd(PY, self.ws / 'tools' / 'check_pool_coverage.py', '--task', 'demo-book')
        self.check('负向：删 R 层引用 ⇒ G-66 rc=1（精选未落 R 层）',
                   r.returncode == 1 and '精选' in r.stdout, r.stdout + r.stderr)
        self.rebridge()

        # ── 负向 3：日期×引文错配 → G-67 必红 ──
        sk2 = self.task / 'skills' / 'compound-patience' / 'SKILL.md'
        self.wr(sk2, self.rd(sk2) + '- 「2018年6月19日，某基金因未做压力测试而清盘。」——2019.3.1 复盘记录\n')
        r = self.run_cmd(PY, self.ws / 'tools' / 'check_anchor_consistency.py', '--task', 'demo-book')
        self.check('负向：日期×引文错配 ⇒ G-67 rc=1', r.returncode == 1, r.stdout + r.stderr)
        self.rebridge()

        # ── 负向 4：证据包 sha 漂移 → G-68 必红 ──
        self.run_cmd(PY, self.ws / 'tools' / 'build_evidence_pack.py', '--task', 'demo-book')
        ep = self.task / 'skills' / 'decision-checklist' / 'evidence-pool.md'
        txt = self.rd(ep)
        i = txt.index('sha256=') + len('sha256=')
        flipped = ('1' if txt[i + 63] != '1' else '0')     # 翻转首个 sha 的末位，保持 64 位形态
        self.wr(ep, txt[:i + 63] + flipped + txt[i + 64:])
        r = self.run_cmd(PY, self.ws / 'tools' / 'check_evidence_closure.py', '--task', 'demo-book')
        self.check('负向：证据漂移 ⇒ G-68 rc=1',
                   r.returncode == 1 and '漂移' in r.stdout + r.stderr, r.stdout + r.stderr)
        self.run_cmd(PY, self.ws / 'tools' / 'build_evidence_pack.py', '--task', 'demo-book')

        # ── 负向 5：坏图（标签溢出盒子，svg-lint error 级）→ 图件闸必红 ──
        svg = self.book / '.cangjie' / 'capabilities' / 'resources' / 'compound-patience.svg'
        good_svg = self.rd(svg)
        self.wr(svg, good_svg.replace('>每日变化率<', '>每日变化率与周期核对说明<'))   # 12 字 ≈144px ≫ 86px 盒宽
        r = self.run_cmd(PY, ROOT / 'bridge' / 'check_diagrams.py', '--task', 'demo-book', '--ws', self.ws)
        self.check('负向：坏图 ⇒ 图件闸 rc=1', r.returncode == 1 and 'svg-lint error' in r.stdout,
                   r.stdout + r.stderr)
        self.wr(svg, good_svg)

        # ── 负向 6：引用了不存在的图 → 图件闸必红 ──
        card = self.book / '.cangjie' / 'capabilities' / 'cards' / 'compound-patience.md'
        good_card = self.rd(card)
        self.wr(card, good_card + '\n另一张图：resources/does-not-exist.svg\n')
        r = self.run_cmd(PY, ROOT / 'bridge' / 'check_diagrams.py', '--task', 'demo-book', '--ws', self.ws)
        self.check('负向：缺引用 ⇒ 图件闸 rc=1', r.returncode == 1 and '引用缺件' in r.stdout,
                   r.stdout + r.stderr)
        self.wr(card, good_card)

        # ── 收口：恢复后应再次全绿（含图件闸与判态留痕）──
        r = self.run_cmd(PY, AUDIT, '--task', 'demo-book', '--ws', self.ws)
        self.check('恢复后四闸再次全绿（含图件闸）', r.returncode == 0, r.stdout + r.stderr)
        verdict = self.rd(self.task / 'audit-verdict.md')
        self.check('判态留痕 audit-verdict.md 有 PASS 记录', 'PASS' in verdict, verdict)

        total = 12
        print('\n%s（%d/%d）' % ('✔ e2e 全部通过' if not self.failures
                                  else '🔴 e2e 失败项：%s' % '、'.join(self.failures),
                                  total - len(self.failures), total))
        self.assertFalse(self.failures, 'e2e 存在失败项：%s' % '、'.join(self.failures))


if __name__ == '__main__':
    unittest.main(verbosity=2)
