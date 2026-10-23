# -*- coding: utf-8 -*-
"""cangjie_to_dsh.py —— cangjie→dsh 桥接器

把 cangjie-skill 的蒸馏产物（books/<slug>/，v2.5 Capability Bundle 布局）转换成
dsh-distillation-director 三闸（G-66 池覆盖 / G-67 锚一致 / G-68 证据闭包）可审计的
任务结构 .work/<task>/。

用法：
  python bridge/cangjie_to_dsh.py --book-dir books/<slug> --source <原文.txt|.md|.pdf> \
      [--task <slug>] [--ws <工作区根>]

产出（.work/<task>/）：
  book_text.md              原文全文（PDF 用 PyMuPDF 抽取；审计的回源锚定对象）
  verified.md               dsh 格式候选池：`### CJ-NNN  [类型] [技能=<卡slug>]` + `- 原文：「…」`
  skills/<卡slug>/SKILL.md  能力卡副本 + 尾部「审计索引」：每条 R 引文挂（`CJ-NNN`：出处）
  id-map.json               引文→池 id 稳定映射（重跑不换号）
  bridge-report.md          桥接报告：逐条引文的逐字回源结果

判态：
  退出码 0 = 全部引文逐字回源成功（可进 run_audit.py 跑三闸）
  退出码 1 = 存在回源失败 ⇒ 回炉 cangjie 阶段 2（修正 R 层引文）
  退出码 2 = 用法/环境错误

口径对齐（与 tools/ 闸门同一把尺子）：
  - qnorm = 去全部空白后逐字比对（同 check_anchor_consistency._qnorm）
  - 池 id 语法 CJ-NNN 合法性由 _bandid.ID 校验（字母开头波段 + 三位序号）
"""
import argparse
import glob
import hashlib
import io
import json
import os
import re
import sys
import time

from book_skill_common import bridge_state, procedure_hash, source_hashes, write_json

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BAND = 'CJ'                      # cangjie 桥接池的波段前缀
TYPE_MAP = {
    'framework': 'FR', 'principle': 'PR', 'calculation': 'CL', 'procedure': 'PC',
    'troubleshooting': 'TS', 'case': 'CS', 'counter-example': 'CE',
    'counter_example': 'CE', 'term': 'GL', 'glossary': 'GL',
}
FEATURED_TAG = '总纲'            # 映射到 G-66 精选覆盖的默认 tag（--tags 总纲,划范围,数值包络）
IMPORTANCE_FEATURED = ('critical', 'high')
QUOTE_LIMIT_CN = 150


def quote_over_limit(quote):
    if any('\u3400' <= char <= '\u9fff' for char in quote):
        return len(qnorm(quote)) > QUOTE_LIMIT_CN
    return len(quote.split()) > 100


def qnorm(s):
    """单一标尺：仅去空白（与闸门 _qnorm 同口径）。"""
    return re.sub(r'\s', '', s)


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


def load_source(path):
    """原文载入：txt/md 直读；pdf 用 PyMuPDF 抽全文（页间换行）。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf':
        try:
            import fitz  # PyMuPDF
        except ImportError:
            sys.exit('🔴 需要 PyMuPDF 才能抽 PDF 原文：.venv/bin/pip install PyMuPDF')
        doc = fitz.open(path)
        pages = [pg.get_text() for pg in doc]
        doc.close()
        return '\n'.join(pages), len(pages)
    text = io.open(path, encoding='utf-8').read()
    return text, None


# ── cangjie 侧解析 ────────────────────────────────────────────────────────────

def parse_cangjie_units(path):
    """cangjie verified.md（YAML 单元流水记录）→ [{id,title,type,location}]。
    单元以 `id:` 行起始；location 取 source_evidence[0].location。"""
    if not os.path.isfile(path):
        return {}
    units, cur = {}, None
    for raw in io.open(path, encoding='utf-8').read().split('\n'):
        st = raw.strip()
        m = re.match(r'^id:\s*(\S+)$', st)
        if m:
            cur = {'id': m.group(1), 'title': '', 'type': '', 'location': ''}
            units[cur['id']] = cur
            continue
        if cur is None:
            continue
        m = re.match(r'^title:\s*(.+)$', st)
        if m:
            cur['title'] = m.group(1).strip().strip('"')
        m = re.match(r'^type:\s*(\S+)$', st)
        if m:
            cur['type'] = m.group(1).strip().lower()
        m = re.match(r'^location:\s*(.+)$', st)
        if m and not cur['location']:
            cur['location'] = m.group(1).strip()
    return units


def load_bundle(book_dir):
    """Capability Bundle（.cangjie/capabilities/verified.yaml）→ 按 card 文件名索引。
    缺 Bundle（legacy 布局）返回 {} 并由调用方降级。"""
    p = os.path.join(book_dir, '.cangjie', 'capabilities', 'verified.yaml')
    if not os.path.isfile(p):
        return None
    try:
        import yaml
        data = yaml.safe_load(io.open(p, encoding='utf-8').read()) or {}
    except Exception as e:
        print('⚠ Bundle 解析失败（按 legacy 降级）：%s' % e)
        return None
    out = {}
    for cap in data.get('capabilities') or []:
        if not isinstance(cap, dict):
            continue
        card = os.path.basename((cap.get('card') or '').strip())
        locs = [se.get('location') for se in (cap.get('source_evidence') or [])
                if isinstance(se, dict) and se.get('location')]
        out[card] = {
            'capability_id': cap.get('capability_id', ''),
            'slug': cap.get('slug', os.path.splitext(card)[0]),
            'importance': (cap.get('importance') or '').strip().lower(),
            'title': cap.get('title', ''),
            'location': locs[0] if locs else '',
        }
    return out


def extract_r_quotes(card_text):
    """能力卡 R 段 → [(quote, attribution)]。
    R 段 = `## R` 标题到下一个 `## ` 标题之间；引文取 blockquote 行（`> …`），
    `— 作者, 出处` 形态的行计为署名/出处而非引文；无 blockquote 时回退取「…」跨行 span。"""
    m = re.search(r'^##\s+R\b.*$', card_text, re.M)
    if not m:
        return [], None
    nxt = re.search(r'^##\s+', card_text[m.end():], re.M)
    sect = card_text[m.end():m.end() + nxt.start()] if nxt else card_text[m.end():]
    quotes, attribution = [], None
    buf = []
    for raw in sect.split('\n'):
        line = raw.strip()
        if not line.startswith('>'):
            if buf:
                quotes.append('\n'.join(buf))
                buf = []
            continue
        inner = line[1:].strip()
        if not inner:
            if buf:
                quotes.append('\n'.join(buf))
                buf = []
            continue
        if re.match(r'^[—–\-]{1,2}\s*', inner):        # — AUTHOR, CHAPTER
            attribution = re.sub(r'^[—–\-]{1,2}\s*', '', inner)
            continue
        buf.append(inner)
    if buf:
        quotes.append('\n'.join(buf))
    quotes = [q.strip() for q in quotes if qnorm(q)]
    if not quotes:                                       # 回退：R 段内的「…」span
        for qm in re.finditer(r'[「“]([^「”」\n]{6,})[」”]', sect):
            quotes.append(qm.group(1).strip())
    return quotes, attribution


def guess_type(quotes, unit_type):
    if unit_type in TYPE_MAP:
        return TYPE_MAP[unit_type]
    blob = qnorm(''.join(quotes))
    for kw, code in (('公式', 'CL'), ('计算', 'CL'), ('步骤', 'PC'), ('清单', 'PR'),
                     ('原则', 'PR'), ('反例', 'CE'), ('失败', 'CE'), ('术语', 'GL')):
        if kw in blob:
            return code
    return 'FR'


def clean_anchor(s, limit=40):
    """锚（出处）写入池/引用行前清洗：去掉会截断 CITE 正则的字符并限长。"""
    s = re.sub(r'[（）)`]', '', (s or '').strip())
    s = re.sub(r'\s+', ' ', s)
    return s[:limit]


# ── 池 id 铸造（稳定映射） ────────────────────────────────────────────────────

def load_idmap(path):
    if os.path.isfile(path):
        try:
            return json.loads(io.open(path, encoding='utf-8').read())
        except Exception:
            pass
    return {}


def next_id(used):
    n = 1
    while '%s-%03d' % (BAND, n) in used:
        n += 1
    return '%s-%03d' % (BAND, n)


def main():
    ap = argparse.ArgumentParser(description='cangjie→dsh 桥接器')
    ap.add_argument('--book-dir', required=True, help='cangjie 输出目录 books/<slug>')
    ap.add_argument('--source', required=True, help='原文文本（.txt/.md/.pdf）')
    ap.add_argument('--task', default=None, help='任务 slug（默认取 book-dir 名）')
    ap.add_argument('--ws', default=None, help='工作区根（默认自动解析）')
    a = ap.parse_args()

    book_dir = os.path.abspath(a.book_dir)
    if not os.path.isdir(book_dir):
        sys.exit('🔴 找不到 cangjie 输出目录：%s' % book_dir)
    if not os.path.isfile(a.source):
        sys.exit('🔴 找不到原文文件：%s' % a.source)
    task = a.task or os.path.basename(book_dir.rstrip('/'))
    ws = resolve_ws(a.ws)
    tdir = os.path.join(ws, '.work', task)
    os.makedirs(tdir, exist_ok=True)

    src_text, npage = load_source(a.source)
    srcn = qnorm(src_text)
    io.open(os.path.join(tdir, 'book_text.md'), 'w', encoding='utf-8', newline='\n').write(src_text)
    print('✔ book_text.md：%s%s（%d 字）' % (
        os.path.basename(a.source), '（PDF %d 页）' % npage if npage else '', len(srcn)))

    bundle = load_bundle(book_dir)
    units = parse_cangjie_units(os.path.join(book_dir, 'verified.md'))
    if bundle is None:
        print('⚠ 未找到 Capability Bundle（legacy 布局）：importance/出处按降级口径处理')

    card_files = sorted(glob.glob(os.path.join(book_dir, '.cangjie', 'capabilities', 'cards', '*.md')))
    if not card_files:                                   # legacy：无 Bundle 侧车层时退回目录顶层
        card_files = sorted(glob.glob(os.path.join(book_dir, 'skills', '*', 'SKILL.md')))
    if not card_files:
        sys.exit('🔴 未找到能力卡（.cangjie/capabilities/cards/*.md 或 skills/*/SKILL.md）')

    idmap_path = os.path.join(tdir, 'id-map.json')
    idmap = load_idmap(idmap_path)
    used = set(idmap.values())

    pool_lines = ['# cangjie→dsh 桥接生成（勿手改；重跑 bridge/cangjie_to_dsh.py 覆盖）', '']
    report_rows = []          # (id, card, importance, quote, anchor, ok)
    warnings = []
    per_skill_quotes = {}     # slug -> [(id, quote, anchor)]

    for cf in card_files:
        base = os.path.basename(cf)
        slug = os.path.splitext(base)[0]
        cap = (bundle or {}).get(base) or {}
        imp = cap.get('importance', '')
        cap_id = cap.get('capability_id', '')
        quotes, attribution = extract_r_quotes(io.open(cf, encoding='utf-8').read())
        if not quotes:
            warnings.append('%s：R 段未解析到引文（无法入池参与审计）' % slug)
            per_skill_quotes[slug] = []
            continue
        anchor_base = clean_anchor(cap.get('location') or attribution or '出处未标注')
        unit_type = ''
        for u in units.values():                        # 以出处/标题粗匹配 cangjie 单元类型
            if (u['location'] and u['location'] in anchor_base) or \
               (u['title'] and cap.get('title') and u['title'] in cap['title']):
                unit_type = u['type']
                break
        tcode = guess_type(quotes, unit_type)
        sq = []
        for q in quotes:
            key = hashlib.sha1((slug + '\x00' + qnorm(q)).encode('utf-8')).hexdigest()
            if key not in idmap:
                pid = next_id(used)
                idmap[key] = pid
                used.add(pid)
            pid = idmap[key]
            ok = qnorm(q) in srcn
            nchar = len(qnorm(q))
            anchor = anchor_base
            featured = imp in IMPORTANCE_FEATURED
            pool_lines += [
                '### %s  [%s] [技能=%s]' % (pid, tcode, slug),
                '- 锚：%s' % anchor,
                '- 原文：「%s」' % q.replace('\n', ''),
                '- 字数：%d' % nchar,
                '- 备注：%s%s｜cap=%s｜card=%s' % (
                    FEATURED_TAG + '｜' if featured else '', 'importance=%s' % (imp or '?'),
                    cap_id or '?', base),
                '',
            ]
            if not ok:
                warnings.append('%s：%s 引文未能逐字回源（回炉 cangjie 阶段2 修正 R 层）：「%s…」'
                                % (slug, pid, q[:30]))
            if quote_over_limit(q):
                warnings.append('%s：%s 引文超 cangjie 红线上限（中文150字/英文100词）' % (slug, pid))
            report_rows.append((pid, slug, imp or '?', q, anchor, ok))
            sq.append((pid, q, anchor))
        per_skill_quotes[slug] = sq

    io.open(os.path.join(tdir, 'verified.md'), 'w', encoding='utf-8', newline='\n') \
        .write('\n'.join(pool_lines))
    io.open(idmap_path, 'w', encoding='utf-8', newline='\n') \
        .write(json.dumps(idmap, ensure_ascii=False, indent=1))
    io.open(os.path.join(tdir, 'bridge-manifest.json'), 'w', encoding='utf-8', newline='\n') \
        .write(json.dumps({'task': task, 'book_dir': book_dir,
                           'source': os.path.abspath(a.source),
                           'bridged_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                           'generator': 'bridge/cangjie_to_dsh.py'},
                          ensure_ascii=False, indent=1))

    for slug, sq in per_skill_quotes.items():
        if not sq:
            continue
        sdir = os.path.join(tdir, 'skills', slug)
        os.makedirs(sdir, exist_ok=True)
        card_src = os.path.join(book_dir, '.cangjie', 'capabilities', 'cards', slug + '.md')
        if not os.path.isfile(card_src):
            card_src = os.path.join(book_dir, 'skills', slug, 'SKILL.md')
        body = io.open(card_src, encoding='utf-8').read()
        idx_lines = ['', '---', '', '## 审计索引（cangjie→dsh 桥接生成，勿手改）', '']
        for pid, q, anchor in sq:
            idx_lines.append('- 「%s」（`%s`：%s）' % (q.replace('\n', ''), pid, anchor))
        io.open(os.path.join(sdir, 'SKILL.md'), 'w', encoding='utf-8', newline='\n') \
            .write(body + '\n'.join(idx_lines) + '\n')

    # ── 桥接报告 ──
    n_ok = sum(1 for r in report_rows if r[5])
    n_bad = len(report_rows) - n_ok
    rep = ['# cangjie→dsh 桥接报告', '',
           '- 任务：%s' % task,
           '- 原文：%s（归一 %d 字）' % (os.path.basename(a.source), len(srcn)),
           '- 能力卡：%d 张；引文 %d 条；逐字回源 ✔ %d／✗ %d' % (
               len(card_files), len(report_rows), n_ok, n_bad),
           '',
           '| 池 id | 能力卡 | importance | 回源 | 引文（前 40 字） |',
           '|---|---|---|---|---|']
    for pid, slug, imp, q, _anchor, ok in report_rows:
        rep.append('| %s | %s | %s | %s | %s… |' % (
            pid, slug, imp, '✔' if ok else '🔴', q.replace('\n', '')[:40]))
    if warnings:
        rep += ['', '## 警示'] + ['- %s' % w for w in warnings]
    io.open(os.path.join(tdir, 'bridge-report.md'), 'w', encoding='utf-8', newline='\n') \
        .write('\n'.join(rep) + '\n')

    print('✔ verified.md：池 %d 条（%s/skills/* 共 %d 张卡）' % (
        len(report_rows), tdir, len(per_skill_quotes)))
    print('✔ 回源判态：逐字命中 %d／未命中 %d' % (n_ok, n_bad))
    for w in warnings:
        print('⚠ %s' % w)
    print('报告：%s' % os.path.join(tdir, 'bridge-report.md'))
    invalid_quotes = bool(n_bad or any(not sq for sq in per_skill_quotes.values())
                          or any(quote_over_limit(row[3]) for row in report_rows))
    # Bind the gate run to the actual source, Bundle and copied audit text.
    # A re-bridge revokes every prior passing receipt for this task.
    write_json(os.path.join(tdir, 'bridge-inputs.json'), {
        'source': source_hashes(a.source), 'procedures': procedure_hash(book_dir),
        'bridge_state': bridge_state(tdir), 'valid': not invalid_quotes,
    })
    receipt = os.path.join(tdir, 'audit-result.json')
    if os.path.isfile(receipt):
        os.unlink(receipt)
    if invalid_quotes:
        print('🔴 存在未回源引文 —— 回炉 cangjie 阶段 2（修正 R 层）后重跑本桥接')
        return 1
    print('✔ 桥接完成 —— 下一步：python bridge/run_audit.py --task %s' % task)
    return 0


if __name__ == '__main__':
    sys.exit(main())
