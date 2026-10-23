# -*- coding: utf-8 -*-
"""bootstrap.py —— book-workflow 插件的按工作区自举（每个工作区跑一次）

做三件事（全部幂等，重复跑安全）：
  1. 找 Python ≥3.10 并在 <ws>/.venv 建虚拟环境，装 PyYAML + PyMuPDF + html-css-to-image 0.3.0
  2. 把 dsh 闸门套装装入 <ws>/tools/ 与 <ws>/.dsh/（官方 init_workspace.py）
  3. 打印体检摘要（node 可用性、闸门件数）与下一步命令

用法：python3 scripts/bootstrap.py <工作区根>
退出码：0=就绪；2=环境错误（带指引）。
本脚本刻意兼容 Python 3.9 语法——它可能被系统 python3 调起，
真正跑闸门/桥接的是它建出的 .venv（≥3.10）。
"""
import os
import shutil
import subprocess
import sys

MIN_MAJOR, MIN_MINOR = 3, 10
REQUIRED = [('yaml', 'PyYAML'), ('fitz', 'PyMuPDF')]
# 第四件 vendor 的运行库。装 wheel，避免现场用 hatchling 重新构建。
# 缺密钥时客户端仍可导入；真正出图由 bridge/render_html_image.py 拒绝访问网络。
HCI_WHEEL = 'html_css_to_image-0.3.0-py3-none-any.whl'


def candidate_pythons():
    out = []
    env = (os.environ.get('BW_PYTHON') or '').strip()
    if env:
        out.append(env)
    out.append('/opt/homebrew/bin/python3')
    for minor in range(14, 9, -1):
        out.append('/opt/homebrew/bin/python3.%d' % minor)
    for minor in range(14, 9, -1):
        out.append('python3.%d' % minor)
    out.append('python3')
    return out


def version_of(cmd):
    try:
        r = subprocess.run([cmd, '-c', 'import sys;print("%d.%d"%sys.version_info[:2])'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return tuple(int(x) for x in r.stdout.strip().split('.'))
    except Exception:
        pass
    return None


def find_python():
    for c in candidate_pythons():
        if os.path.isfile(c) or shutil.which(c):
            v = version_of(c)
            if v and (v[0], v[1]) >= (MIN_MAJOR, MIN_MINOR):
                return os.path.abspath(c) if os.path.isfile(c) else shutil.which(c), v
    return None, None


def main():
    if len(sys.argv) != 2:
        print('用法: python3 scripts/bootstrap.py <工作区根>')
        return 2
    ws = os.path.abspath(sys.argv[1])
    if not os.path.isdir(ws):
        print('🔴 工作区目录不存在：%s' % ws)
        return 2
    here = os.path.dirname(os.path.abspath(__file__))
    plugin = os.path.dirname(here)

    # 1) venv + 依赖
    vpy = os.path.join(ws, '.venv', 'bin', 'python')
    py, v = find_python()
    if not py:
        print('🔴 未找到 Python ≥%d.%d —— 请装 Homebrew python 或设 BW_PYTHON 指向解释器'
              % (MIN_MAJOR, MIN_MINOR))
        return 2
    if not os.path.isfile(vpy):
        print('▶ 用 %s（%d.%d）建 .venv …' % (py, v[0], v[1]))
        r = subprocess.run([py, '-m', 'venv', os.path.join(ws, '.venv')])
        if r.returncode != 0:
            print('🔴 venv 创建失败（rc=%d）' % r.returncode)
            return 2
    miss = []
    for mod, pkg in REQUIRED:
        r = subprocess.run([vpy, '-c', 'import %s' % mod], capture_output=True)
        if r.returncode != 0:
            miss.append(pkg)
    if miss:
        print('▶ 安装依赖：%s …' % '、'.join(miss))
        r = subprocess.run([os.path.join(ws, '.venv', 'bin', 'pip'), 'install',
                            '--quiet', '--disable-pip-version-check'] + miss)
        if r.returncode != 0:
            print('🔴 依赖安装失败：%s' % '、'.join(miss))
            return 2
    hci_ok = subprocess.run([vpy, '-c', 'import html_css_to_image'], capture_output=True)
    if hci_ok.returncode != 0:
        wheel = os.path.join(plugin, 'vendor', 'html-css-to-image', 'dist', HCI_WHEEL)
        if not os.path.isfile(wheel):
            print('🔴 缺少 html-css-to-image wheel：%s' % wheel)
            return 2
        print('▶ 安装 html-css-to-image 0.3.0 …')
        r = subprocess.run([os.path.join(ws, '.venv', 'bin', 'pip'), 'install',
                            '--quiet', '--disable-pip-version-check', wheel])
        if r.returncode != 0:
            print('🔴 html-css-to-image 安装失败')
            return 2

    # 2) dsh 闸门套装（幂等：配置在则跳过）
    cfg = os.path.join(ws, '.dsh', 'gate-kit', 'workspace.json')
    if not (os.path.isfile(cfg) and os.path.isdir(os.path.join(ws, 'tools'))):
        print('▶ 装入 dsh 闸门套装 …')
        r = subprocess.run([vpy, os.path.join(plugin, 'vendor', 'dsh-distillation-director',
                                              'scripts', 'gates', 'init_workspace.py'),
                            ws, '--plugin',
                            os.path.join(plugin, 'vendor', 'dsh-distillation-director')])
        if r.returncode != 0:
            print('🔴 init_workspace 失败（rc=%d）' % r.returncode)
            return 2
    n_tools = len([f for f in os.listdir(os.path.join(ws, 'tools'))
                   if f.endswith('.py')]) if os.path.isdir(os.path.join(ws, 'tools')) else 0

    # 3) 摘要
    node = shutil.which('node')
    print('✔ 工作区就绪：%s' % ws)
    print('   venv python：%s（PyYAML/PyMuPDF/html-css-to-image 齐）' % vpy)
    print('   dsh 闸门：tools/ 下 %d 个 py 件%s' % (
        n_tools, '' if os.path.isfile(cfg) else '（配置缺失⚠）'))
    print('   node：%s%s' % (node or '未找到',
                             '（svg-lint 可用）' if node else '（图件闸 svg-lint 将判不适用）'))
    print('\n下一步（脚本不在工作区内，务必带 --ws）:')
    print('  先按 skills/book-workflow/SKILL.md 重建思想、叙事与完整范例；不要用桥接替代这一步。')
    print('  思想核查: %s %s --book-dir %s/books/<slug> --source <原文> --ws %s'
          % (vpy, os.path.join(plugin, 'bridge', 'thinking_audit.py'), ws, ws))
    print('  下列桥接/四闸只用于存在程序 Bundle 的书：')
    print('  桥接: %s %s --book-dir %s/books/<slug> --source <原文> --task <slug> --ws %s'
          % (vpy, os.path.join(plugin, 'bridge', 'cangjie_to_dsh.py'), ws, ws))
    print('  审计: %s %s --task <slug> --ws %s'
          % (vpy, os.path.join(plugin, 'bridge', 'run_audit.py'), ws))
    return 0


if __name__ == '__main__':
    sys.exit(main())
