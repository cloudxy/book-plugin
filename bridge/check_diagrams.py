# -*- coding: utf-8 -*-
"""check_diagrams.py —— 图件闸（组合流水线第四闸）

对桥接任务对应的书树（books/<slug>/，路径记于 .work/<task>/bridge-manifest.json）：
  1) 引用完整：书树 .md 文件里引用的每个 *.svg 路径都必须存在（多基解析）——缺件 🔴
  2) 孤儿图：书树里存在但未被任何 .md 引用的 .svg ——黄牌警示（不计红）
  3) 风格合规：书树里每个 .svg 过 vendor/svg-diagram 的 svg-lint——error 🔴；
     warning 默认黄牌（--strict 升红；出图规范见 vendor/svg-diagram/SKILL.md）
  4) node 缺失 / 无 manifest / 无图 ⇒ 判"不适用"，rc=0（与 dsh 闸门口径一致：不适用≠通过）

用法：python bridge/check_diagrams.py --task <slug> [--strict] [--ws <工作区根>]
退出码：0=通过或判不适用；1=有红项；2=用法错误。
"""
import argparse
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REF_RE = re.compile(r'[\w./-]+\.svg')


def walk_files(root, exts):
    """os.walk 遍历（含 .cangjie 等点开头目录——glob 的 ** 按壳规则跳过隐藏目录，会漏整棵侧车层）。"""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        if '.git' in dirpath.split(os.sep):
            continue
        for f in files:
            if os.path.splitext(f)[1].lower() in exts:
                out.append(os.path.join(dirpath, f))
    return sorted(out)


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


def main():
    ap = argparse.ArgumentParser(description='图件闸：svg 引用完整 + svg-lint 风格合规')
    ap.add_argument('--task', required=True)
    ap.add_argument('--strict', action='store_true', help='svg-lint warning 也计红')
    ap.add_argument('--ws', default=None)
    a = ap.parse_args()
    ws = resolve_ws(a.ws)
    tdir = os.path.join(ws, '.work', a.task)

    mf = os.path.join(tdir, 'bridge-manifest.json')
    if not os.path.isfile(mf):
        print('▲ 无 bridge-manifest.json（非桥接任务）——图件闸不适用')
        return 0
    book_dir = json.loads(io.open(mf, encoding='utf-8').read()).get('book_dir', '')
    if not book_dir or not os.path.isdir(book_dir):
        print('🔴 manifest 记录的书目录不存在：%s' % book_dir)
        return 1

    md_files = walk_files(book_dir, {'.md'})
    svg_files = walk_files(book_dir, {'.svg'})
    if not svg_files:
        print('✔ %s：书树无 svg 图件（判不适用——有图时本闸自动生效）' % a.task)
        return 0

    # ── 1) 引用完整（多基解析：md 所在目录 / capabilities / 书根）──
    caps_dir = os.path.join(book_dir, '.cangjie', 'capabilities')
    findings = []
    used = set()
    for mf_path in md_files:
        text = io.open(mf_path, encoding='utf-8', errors='replace').read()
        for ref in REF_RE.findall(text):
            for base in (os.path.dirname(mf_path), caps_dir, book_dir):
                cand = os.path.normpath(os.path.join(base, ref))
                if os.path.isfile(cand):
                    used.add(os.path.abspath(cand))
                    break
            else:
                findings.append('引用缺件：%s 引用的 %s 不存在（相对 md 目录/capabilities/书根 均未找到）'
                                % (os.path.relpath(mf_path, book_dir), ref))

    # ── 2) 孤儿图（黄牌）──
    orphans = [f for f in svg_files if os.path.abspath(f) not in used]

    # ── 3) svg-lint 风格合规 ──
    node = shutil.which('node')
    warnings_n = 0
    lint_bad = []

    def _find_linter():
        # 双布局：开发工作区（$WS/vendor）或插件包（bridge 脚本上两级的 vendor）
        cands = [os.path.join(ws, 'vendor', 'svg-diagram', 'tools', 'svg-lint', 'bin', 'svg-lint.mjs'),
                 os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'vendor', 'svg-diagram', 'tools', 'svg-lint', 'bin', 'svg-lint.mjs')]
        return next((c for c in cands if os.path.isfile(c)), None)

    if not node:
        print('▲ 未找到 node —— svg-lint 判不适用（装 node 后本项自动生效）；引用完整性检查照常执行')
    elif _find_linter() is None:
        findings.append('svg-lint 不在场（$WS/vendor 与插件 vendor 均无）——图件闸无法判风格合规，'
                        '检查插件包完整性')
    else:
        r = subprocess.run([node, _find_linter(), '--json'] + svg_files,
                           capture_output=True, text=True)
        try:
            rep = json.loads(r.stdout or '{}')
        except Exception:
            rep = None
        if r.returncode not in (0, 1) or not isinstance(rep, dict):
            findings.append('svg-lint 未能运行（rc=%d，输出不可解析）：%s'
                            % (r.returncode, (r.stderr or '')[:120]))
        elif not rep.get('files'):
            findings.append('svg-lint 未产出任何文件报告（图 %d 件送检）——环境异常，按未跑处理' % len(svg_files))
        else:
            for fentry in rep.get('files', []):
                errs = [x for x in fentry.get('findings', []) if x.get('severity') == 'error']
                warns = [x for x in fentry.get('findings', []) if x.get('severity') == 'warning']
                warnings_n += len(warns)
                rel = os.path.relpath(fentry['file'], book_dir)
                if errs:
                    lint_bad.append(rel)
                    findings.append('svg-lint error ×%d：%s（%s）' % (
                        len(errs), rel, '；'.join(x.get('code', '?') for x in errs[:3])))
                elif warns and a.strict:
                    findings.append('svg-lint warning ×%d（--strict）：：%s（%s）' % (
                        len(warns), rel, '；'.join(x.get('code', '?') for x in warns[:3])))

    for f in orphans:
        print('⚠ 孤儿图（无 .md 引用）：%s' % os.path.relpath(f, book_dir))
    if warnings_n and not a.strict:
        print('⚠ svg-lint warning ×%d（默认黄牌；--strict 升红）' % warnings_n)

    if findings:
        print('🔴 %s：%d 处' % (a.task, len(findings)))
        for x in findings[:12]:
            print('   · ' + x)
        print('合计 findings：%d' % len(findings))
        return 1
    print('✔ %s：0 处（图 %d／引用完整／lint error 0%s）' % (
        a.task, len(svg_files), '／warning %d' % warnings_n if warnings_n else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
