"""Merge the day's AI digests and auto quiet-blocks into one content.html for the site + email.

Usage:  python -I -X utf8 build_companies_site.py <outdir> "<edition date>"

<outdir> = runs/YYYY-MM-DD (must contain triage.json, raw/*.json; digests may be missing).
Writes <outdir>/content.html: one <section class="sec"> per company, signal companies first
(in watchlist order, with a "New this morning" marker), then quiet companies.
Quiet blocks are generated here from raw/{SYM}.json without AI; digests/digest_*.html
are written by the Claude step using the company-section patterns in example_content.html.
"""
import sys, os, json, re, html as htmlmod, glob

OUT = sys.argv[1]
DATE_LABEL = sys.argv[2]
RAW = os.path.join(OUT, 'raw')
triage = json.load(open(os.path.join(OUT, 'triage.json'), encoding='utf-8'))
watch = {w['symbol']: w for w in json.load(open('watchlist.json', encoding='utf-8'))}
errors = triage.get('errors') or []
fetched = next(iter(glob.glob(os.path.join(RAW, '*.json'))), None)
fetched = json.load(open(fetched, encoding='utf-8'))['fetched_ist'] if fetched else '?'


def esc(x):
    return htmlmod.escape(str(x or ''))


def filing_lines(f):
    out = []
    for x in f['filings'][:8]:
        date = (x.get('date') or '').replace('T', ' ')[:10]
        out.append(f"<li><b>{esc(x.get('form') or x.get('title')[:80])}</b> {esc(date)} "
                   f"&mdash; <a href=\"{esc(x.get('url'))}\">{esc(x.get('source') or 'filing')}</a></li>")
    return '\n'.join(out) or '<li>None in the last 3 days.</li>'


def news_lines(items, heading=None):
    if not items:
        return ''
    head = f'<h3>{heading}</h3>\n' if heading else ''
    lis = []
    for n in items[:8]:
        when = re.sub(r'\s+', ' ', (n.get('when') or n.get('date') or '')[:22]).strip()
        title = esc(n.get('title'))
        link = esc(n.get('link'))
        when_html = f'<span class="fine">({esc(when)})</span>' if when else ''
        lis.append(f'<li>{title} {when_html} &mdash; <a href="{link}">source</a></li>')
    return head + '<ul>\n' + '\n'.join(lis) + '\n</ul>'


def quiet_block(f):
    n = f['name']
    s = f['social'] or {}
    social = ('neutral' if not s.get('sentiment') else esc(s.get('sentiment')))
    if s.get('latest'):
        social_note = f"Recent chatter ({len(s['latest'])} messages): " + '; '.join(
            esc(m['text'][:120]) for m in s['latest'][:2])
    else:
        social_note = 'No recent messages.'
    comps = ', '.join(esc(c.get('n') or c.get('s')) for c in f['competitors']) or 'n/a'
    ind_news = f['industry_news']
    return f"""<section class="sec" data-sym="{esc(f['symbol'])}">
  <p class="kicker">Quiet</p>
  <h2>{esc(n)} ({esc(f['symbol'])})</h2>
  <p>No new filings and no notable {esc(n)} news in the last 24 hours. Social chatter: <b>{social}</b>. {social_note}</p>
  <p class="fine">Competitors: {comps}. Industry: {esc(f['industry'] or 'n/a')}.</p>
  {news_lines(ind_news, 'Industry' + ('' if ind_news else ' (nothing notable this morning)'))}
  <p class="src">Checked {esc(f['fetched_ist'])} IST &mdash; filings: NSE/SEC; news: Google News; social: StockTwits.</p>
</section>"""


parts = []
# signal companies: their digest HTML was written per group by the Claude step
for grp in triage.get('groups') or []:
    path = os.path.join(OUT, 'digests', f'digest_{grp["i"]}.html')
    if os.path.exists(path):
        parts.append(open(path, encoding='utf-8').read())
    else:
        missing = grp['group'].split()
        for sym in missing:
            f = json.load(open(os.path.join(RAW, f'{sym}.json'), encoding='utf-8'))
            parts.append(f'<section class="sec" data-sym="{esc(sym)}">\n  <p class="kicker">Digest missing</p>\n  <h2>'
                         f'{esc(f["name"])} ({esc(sym)})</h2>\n  <p>The AI digest for this company '
                         'could not be produced this morning; the raw scan is available.</p>\n'
                         + filing_lines(f) + '\n' + news_lines(f['news']) + '</section>\n')
# quiet companies in watchlist order
for w in watch.values():
    sym = w['symbol'].upper()
    if sym in set(triage.get('signal') or []):
        continue
    f = json.load(open(os.path.join(RAW, f'{sym}.json'), encoding='utf-8'))
    parts.append(quiet_block(f))

notice = ''
if errors:
    notice = ('<div class="notice"><div class="wrap"><p><b>Source notes this morning:</b> '
              + esc('; '.join(errors[:6])) + '</p></div></div>\n')
n_sig = len(triage.get('signal') or [])
summary = f"""<section class="sec">
  <p class="kicker">Start here</p>
  <h2>{DATE_LABEL} &mdash; Company Tracker</h2>
  <p><b>{n_sig} of {len(watch)} tracked companies</b> have new filings or notable news this morning. Scanned: corporate filings (NSE + SEC), company, competitor and industry news (last 24 hours) and social chatter (StockTwits).</p>
  <p class="fine">Scanned {esc(fetched)} IST. Use the search box to jump to a company; mark the ones you follow with Track. Every item links to its source; anything that could not be confirmed is left out.</p>
</section>
"""
open(os.path.join(OUT, 'content.html'), 'w', encoding='utf-8').write(notice + summary + '\n'.join(parts))
print(f'content.html: {len(parts)} company blocks, {len(triage.get("signal") or [])} signal, {len(errors)} source errors')
