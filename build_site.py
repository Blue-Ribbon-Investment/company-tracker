"""Build the public website page and the email version from a day's content.html.

Usage:
  python3 -I -X utf8 build_site.py <content.html> <site_dir> <out_dir> "<edition date>" "<built at>" "<page url>"

Writes <site_dir>/index.html (full web page, light and dark themes) and <out_dir>/email.html
(email-safe version: plain CSS plus inline styles, light theme only).

Phone-friendly tables: any table with an "As of" column is folded to three columns,
with the "As of" text shown in small grey type under the name in the first column.
"""
import sys, os, re, html as htmlmod
from html.parser import HTMLParser


# ---------- phone-friendly tables ----------
def _cells(row_html):
    return list(re.finditer(r'<(t[hd])([^>]*)>(.*?)</\1>', row_html, re.S | re.I))


def compact_table(tbl):
    rows = list(re.finditer(r'<tr([^>]*)>(.*?)</tr>', tbl, re.S | re.I))
    if not rows:
        return tbl
    head = _cells(rows[0].group(2))
    idx = next((i for i, c in enumerate(head)
                if c.group(1).lower() == 'th' and re.sub(r'<[^>]+>', '', c.group(3)).strip().lower() == 'as of'), None)
    if idx is None:
        return tbl
    ncols = len(head)
    out, last = [], 0
    for r in rows:
        out.append(tbl[last:r.start()])
        attrs, inner = r.group(1), r.group(2)
        cells = _cells(inner)
        if r is rows[0] or (cells and all(c.group(1).lower() == 'th' for c in cells)):
            new_inner = ''.join(c.group(0) for i, c in enumerate(cells) if i != idx)
        elif len(cells) == 1 or 'grp' in attrs:
            new_inner = re.sub(r'colspan="?(\d+)"?', lambda m: f'colspan="{max(1, int(m.group(1)) - 1)}"', inner)
        elif len(cells) == ncols:
            asof = cells[idx].group(3).strip()
            parts = []
            for i, c in enumerate(cells):
                if i == idx:
                    continue
                body = c.group(3)
                if i == 0 and re.sub(r'<[^>]+>', '', asof).strip():
                    body = body + f'<span class="asof-line">{asof}</span>'
                parts.append(f'<{c.group(1)}{c.group(2)}>{body}</{c.group(1)}>')
            new_inner = ''.join(parts)
        else:
            new_inner = inner
        out.append(f'<tr{attrs}>{new_inner}</tr>')
        last = r.end()
    out.append(tbl[last:])
    return ''.join(out)


def compact_tables(content):
    return re.sub(r'<table class="data">.*?</table>', lambda m: compact_table(m.group(0)), content, flags=re.S | re.I)


# ---------- inline styles for email clients that ignore <style> ----------
MUTED, INK, RULE, NAVY = '#586273', '#18212F', '#E1E6EC', '#14284B'
# Only the table parts are inlined (the layout that matters on phones); everything else relies on
# the <style> block, which keeps the email well under Gmail's ~100 KB clipping limit.
STYLES = {
    ('section', 'sec'): 'background:#FFFFFF;border-radius:10px;padding:16px;margin:12px 0;',
    ('table', 'data'): 'border-collapse:collapse;width:100%;font-size:14px;',
    ('td', 'num'): f'font-family:Consolas,Menlo,monospace;white-space:nowrap;font-size:13px;text-align:right;padding:7px 4px;border-bottom:1px solid {RULE};vertical-align:top;color:{INK};',
    ('td', 'asof'): f'color:{MUTED};font-size:11px;text-align:right;padding:7px 4px;border-bottom:1px solid {RULE};vertical-align:top;',
    ('span', 'asof-line'): f'display:block;font-size:11px;line-height:1.3;color:{MUTED};font-weight:400;margin-top:1px;',
    ('span', 'up'): 'color:#12733A;font-weight:600;',
    ('span', 'down'): 'color:#B3261E;font-weight:600;',
    ('span', 'flat'): f'color:{MUTED};',
    ('th', ''): f'text-align:right;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:{MUTED};font-weight:600;padding:6px 4px;border-bottom:1px solid {RULE};',
    ('td', ''): f'text-align:left;padding:7px 4px;border-bottom:1px solid {RULE};vertical-align:top;color:{INK};',
}
FIRST_TH = f'text-align:left;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:{MUTED};font-weight:600;padding:6px 4px;border-bottom:1px solid {RULE};'
GRP_TD = f'text-align:left;font-weight:700;font-size:13px;padding:12px 4px 4px;color:{INK};'


class Inliner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out = []
        self.row_cell = 0
        self.in_grp = False

    def _style_for(self, tag, cls):
        if tag == 'td' and self.in_grp:
            return GRP_TD
        if tag in ('th', 'td') and self.row_cell == 1 and 'num' not in cls:
            return FIRST_TH if tag == 'th' else STYLES[('td', '')]
        for c in cls:
            if (tag, c) in STYLES:
                return STYLES[(tag, c)]
        return STYLES.get((tag, ''))

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = (d.get('class') or '').split()
        if tag == 'tr':
            self.row_cell = 0
            self.in_grp = 'grp' in cls
        if tag in ('th', 'td'):
            self.row_cell += 1
        style = self._style_for(tag, cls)
        if style:
            d['style'] = style + (d.get('style') or '')
        a = ''.join(f' {k}' if v is None else f' {k}="{htmlmod.escape(v, quote=True)}"' for k, v in d.items())
        self.out.append(f'<{tag}{a}>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.out.append(f'</{tag}>')

    def handle_data(self, data):
        self.out.append(data)

    def handle_entityref(self, name):
        self.out.append(f'&{name};')

    def handle_charref(self, name):
        self.out.append(f'&#{name};')

    def handle_comment(self, data):
        pass


def inline_styles(fragment):
    p = Inliner()
    p.feed(fragment)
    p.close()
    return ''.join(p.out)


def _json_file(path):
    if path and os.path.exists(path):
        return open(path, encoding='utf-8').read().strip()
    return '[]'


if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))
    content_path, site_dir, out_dir, date_label, built_at, page_url = sys.argv[1:7]
    directory_path = sys.argv[7] if len(sys.argv) > 7 else ''
    watchlist_path = sys.argv[8] if len(sys.argv) > 8 else ''
    content = open(content_path, encoding='utf-8').read()
    for bad in ('<html', '<head', '<body', '<!doctype', '<!DOCTYPE'):
        if bad in content:
            sys.exit(f'content.html must not contain {bad} tags')
    content = compact_tables(content)
    directory_json = _json_file(directory_path)
    watch_seed_json = '[]'
    if watchlist_path and os.path.exists(watchlist_path):
        import json as _json
        seed = [{'s': w.get('symbol', '').upper(), 'n': w.get('name') or w.get('symbol')}
                for w in _json.load(open(watchlist_path, encoding='utf-8')) if w.get('symbol')]
        watch_seed_json = _json.dumps(seed)

    # ---------- website ----------
    tpl = open(os.path.join(here, 'page_template.html'), encoding='utf-8').read()
    split_at = tpl.index('<header class="mast">')
    head_part, body_part = tpl[:split_at], tpl[split_at:]
    head_part = (head_part.replace('{{DIRECTORY_JSON}}', directory_json)
                          .replace('{{WATCH_SEED_JSON}}', watch_seed_json))
    body_part = (body_part.replace('{{EDITION_DATE}}', date_label)
                          .replace('{{BUILT_AT}}', built_at)
                          .replace('{{NOTICE}}', '')
                          .replace('{{CONTENT}}', content))
    page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + head_part + '</head>\n<body>\n' + body_part + '\n</body>\n</html>\n')
    os.makedirs(site_dir, exist_ok=True)
    open(os.path.join(site_dir, 'index.html'), 'w', encoding='utf-8').write(page)

    # ---------- email ----------
    etpl = open(os.path.join(here, 'email_template.html'), encoding='utf-8').read()
    email = (etpl.replace('{{EDITION_DATE}}', date_label)
                 .replace('{{BUILT_AT}}', built_at)
                 .replace('{{PAGE_URL}}', page_url)
                 .replace('{{CONTENT}}', inline_styles(content)))
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, 'email.html'), 'w', encoding='utf-8').write(email)
    print('website', len(page), 'chars; email', len(email), 'chars')
