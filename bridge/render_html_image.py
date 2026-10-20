# -*- coding: utf-8 -*-
"""可选栅格出图：本地 HTML/CSS → html-css-to-image 0.3.0。

无 HCTI_API_ID / HCTI_API_KEY 时不访问网络。
不读取 books/ 与 .work/。不提供 URL 截图。
图件闸仍只审计 SVG；本脚本不是闸门。
"""
import argparse
import os
import shutil
import sys

PINNED = '0.3.0'
GROK_FILES = '/Users/xuyun/Documents/grok-files'
MAX_BYTES = 200000


def q(*parts):
    return os.path.realpath(os.path.join(*parts))


def under(path, root):
    path = os.path.realpath(path)
    root = os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def banned(path, ws):
    roots = [os.path.join(ws, 'books'), os.path.join(ws, '.work')]
    return any(os.path.isdir(r) and under(path, r) for r in roots)


def keys_present():
    return bool(os.environ.get('HCTI_API_ID')) and bool(os.environ.get('HCTI_API_KEY'))


def load_client_module():
    import html_css_to_image
    return html_css_to_image


def cmd_check():
    try:
        mod = load_client_module()
    except Exception as e:
        print('🔴 未能导入 html_css_to_image：%s' % e)
        return 1
    ver = getattr(mod, '__version__', '')
    if ver != PINNED:
        print('🔴 html-css-to-image 版本是 %s，登记的是 %s' % (ver or '未知', PINNED))
        return 1
    if keys_present():
        print('✔ html-css-to-image %s 已安装；密钥已配置（值不打印）。远程出图仍须显式调用。' % ver)
    else:
        print('✔ html-css-to-image %s 已安装；未配置 HCTI_API_ID 或 HCTI_API_KEY，远程出图跳过。' % ver)
    return 0


def read_text(path, ws, label):
    if not os.path.isfile(path):
        print('🔴 找不到%s：%s' % (label, path))
        return None
    if banned(path, ws):
        print('🔴 %s 在 books/ 或 .work/ 内，不送出。' % label)
        return None
    if os.path.getsize(path) > MAX_BYTES:
        print('🔴 %s 超过 %d 字节，拒绝送出。' % (label, MAX_BYTES))
        return None
    with open(path, encoding='utf-8') as f:
        return f.read()


def cmd_render(args):
    ws = os.path.abspath(args.ws)
    html_path = os.path.abspath(args.html)
    html = read_text(html_path, ws, 'HTML')
    if html is None:
        return 2
    css = ''
    if args.css:
        css = read_text(os.path.abspath(args.css), ws, 'CSS')
        if css is None:
            return 2
    if not keys_present():
        print('🔴 未配置 HCTI_API_ID 或 HCTI_API_KEY，未发起请求。')
        return 2
    mod = load_client_module()
    if getattr(mod, '__version__', '') != PINNED:
        print('🔴 客户端版本与 vendor 登记的 %s 不一致。' % PINNED)
        return 1
    out = os.path.abspath(args.out)
    if banned(out, ws):
        print('🔴 输出路径不能落在 books/ 或 .work/。')
        return 2
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    request = mod.CreateHtmlCssImageRequest(html=html, css=css or None)
    try:
        with mod.HtmlCssToImageClient.from_env() as client:
            result = client.create_image(request)
    except Exception as e:
        print('🔴 出图请求失败：%s' % type(e).__name__)
        return 1
    if not getattr(result, 'success', False):
        print('🔴 服务未返回图片（HTTP %s）。' % getattr(result, 'status_code', '?'))
        return 1
    url = getattr(result, 'url', '') or ''
    if not url.startswith('https://'):
        print('🔴 返回的地址不是 https。')
        return 1
    import httpx
    try:
        resp = httpx.get(url, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print('🔴 下载图片失败：%s' % type(e).__name__)
        return 1
    with open(out, 'wb') as f:
        f.write(resp.content)
    os.makedirs(GROK_FILES, exist_ok=True)
    copy_to = os.path.join(GROK_FILES, os.path.basename(out))
    if os.path.realpath(copy_to) != os.path.realpath(out):
        shutil.copyfile(out, copy_to)
    print('✔ 已写出 %s' % out)
    print('✔ 副本 %s' % copy_to)
    return 0


def main():
    ap = argparse.ArgumentParser(description='可选：本地 HTML/CSS 栅格出图')
    ap.add_argument('--check', action='store_true', help='只检查安装与密钥是否存在，不访问网络')
    ap.add_argument('--html', help='本地 HTML 文件，不能在 books/ 或 .work/')
    ap.add_argument('--css', help='可选的本地 CSS 文件')
    ap.add_argument('--out', help='图片输出路径')
    ap.add_argument('--ws', default=os.getcwd(), help='工作区根，用于拦住 books/ 与 .work/')
    args = ap.parse_args()
    if args.check:
        return cmd_check()
    if not args.html or not args.out:
        ap.error('出图需要 --html 与 --out；只体检用 --check')
    return cmd_render(args)


if __name__ == '__main__':
    sys.exit(main())
