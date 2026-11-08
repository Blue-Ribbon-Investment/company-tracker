"""Pre-fetch every source for the day's company tracker, one JSON file per company.

Usage:  python -I -X utf8 fetch_companies.py <outdir>      (outdir = runs/YYYY-MM-DD)

Reads watchlist.json from the working directory (the repo root at run time) and writes:
  <outdir>/raw/SYM.json  one file per company: filings, bulk/block deals, company/competitor/industry
                          news (Google News RSS), social signal (StockTwits)
  <outdir>/raw/index.txt  one-line-per-company summary (for quick checking)
  <outdir>/triage.json    which companies have signal (new filings / fresh news / social spike),
                          how they are grouped for the AI step, and every source error

Every source is tried independently; a failure is recorded, never fatal.
Sources: NSE corporate announcements (cookie-primed, as in the markets brief's fetch_numbers.py),
NSE bulk/block deals, SEC EDGAR submissions (no account; User-Agent with contact address),
Google News RSS (per company, per competitor, per industry), StockTwits public API.
"""
import sys, os, json, re, html, subprocess, datetime, urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

OUT = sys.argv[1]
RAW = os.path.join(OUT, 'raw')
os.makedirs(RAW, exist_ok=True)
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
NOW = datetime.datetime.now(IST)
DATE = NOW.strftime('%F')
COOKIES = os.path.join(OUT, 'nse_cookies.txt')
SEC_UA = 'Blue-Ribbon-CompanyTracker contact: newsletterchidananda@gmail.com'
DAYS_BACK = 3          # how far back filings are pulled (covers weekends)
NEWS_PER_COMPANY = 12
NEWS_PER_COMP = 6
MAX_COMP_NEWS = 3      # at most 3 competitors get their own news scan
INDUSTRY_NEWS = 8
SIGNAL_NEWS = 3        # company counts as "signal" with >= this many fresh company news items
SIGNAL_SOCIAL = 40     # or >= this many StockTwits messages in the stream
MAX_GROUP = 5          # companies per AI digest run

errors = []


def curl(url, referer=None, accept='application/json', cookie=False, user_agent=UA, extra=None):
    cmd = ['curl', '-s', '-L', '-m', '40', '-A', user_agent, '-H', 'Accept: ' + accept,
           '-H', 'Accept-Language: en-US,en;q=0.9']
    if referer:
        cmd += ['-H', 'Referer: ' + referer]
    if cookie:
        cmd += ['-b', COOKIES, '-c', COOKIES]
    if extra:
        cmd += extra
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, timeout=70)
    return r.stdout.decode('utf-8', 'ignore')


def getjson(url, **kw):
    return json.loads(curl(url, **kw))


WATCH = json.load(open('watchlist.json', encoding='utf-8'))
if not WATCH:
    sys.exit('watchlist.json is empty; add companies first (see README).')
IN_SYMS = {w['symbol'].upper() for w in WATCH if w.get('market') == 'IN'}
COMP_SYMS = {c.get('s', '').upper() for w in WATCH if w.get('market') == 'IN' for c in w.get('competitors', [])}
WANT_IN = sorted(IN_SYMS | COMP_SYMS)
WANT_US = [w for w in WATCH if w.get('market') == 'US']

# ---------------- NSE filings + deals (cookie-primed, same recipe as the markets brief) ----------------
nse_by_sym, nse_deals = {}, {}
try:
    curl('https://www.nseindia.com/', accept='text/html', cookie=True)
    ref = 'https://www.nseindia.com/companies-listing/corporate-filings-annual-reports'
    frm = (NOW - datetime.timedelta(days=DAYS_BACK)).strftime('%Y-%m-%d')
    url = (f'https://www.nseindia.com/get-attachments?content-type=corpAnnouncement'
           f'&isSummary=true&page=0&from={frm}&to={DATE}')
    data = getjson(url, referer=ref, cookie=True)
    blob = (data or {}).get('data') or {}
    items = blob.get('corpAnnouncement') or blob.get('corporateAnnouncement') or []
    if isinstance(items, dict):
        items = items.get('corporateAnnouncement') or items.get('corpAnnouncement') or []
    for it in items:
        atts = it.get('attachList') or ([it] if it.get('symbol') else [])
        for a in atts:
            sym = (a.get('symbol') or it.get('symbol') or '').upper()
            if sym not in WANT_IN:
                continue
            nse_by_sym.setdefault(sym, []).append({
                'date': (a.get('timestamp') or it.get('timestamp') or '')[:16],
                'title': (a.get('docDescription') or '').strip(),
                'file': a.get('attachment') or '',
                'url': 'https://www.nseindia.com' + (a.get('attachmentLink') or ''),
            })
    for sym in nse_by_sym:
        nse_by_sym[sym].sort(key=lambda z: z['date'], reverse=True)
        nse_by_sym[sym] = nse_by_sym[sym][:10]
    if not items:
        errors.append('NSE: corpAnnouncement returned no items (structure may have changed; check runs/DATE/raw)')
except Exception as e:
    errors.append(f'NSE filings: {e}')

try:
    ref = 'https://www.nseindia.com/market-data/large-deals'
    d = getjson('https://www.nseindia.com/api/snapshot-capital-market-largedeal', referer=ref, cookie=True)
    rows = (d.get('BULK_DEALS_DATA') or []) + (d.get('BLOCK_DEALS_DATA') or [])
    for r in rows:
        try:
            val = round(float(r['qty']) * float(r['watp']) / 1e7, 1)
        except Exception:
            continue
        sym = (r.get('symbol') or '').upper()
        if sym in IN_SYMS:
            nse_deals.setdefault(sym, []).append({'kind': 'block' if r.get('type') == 'B' else 'bulk',
                                                  'side': r.get('buySell'), 'value_cr': val,
                                                  'client': r.get('clientName'), 'date': r.get('date')})
except Exception as e:
    errors.append(f'NSE deals: {e}')

# ---------------- SEC filings (US) ----------------
sec_by_sym, sec_names = {}, {}
try:
    tick = getjson('https://www.sec.gov/files/company_tickers.json', user_agent=SEC_UA)
    sec_names = {v.get('ticker', '').upper(): v for v in tick.values()}
except Exception as e:
    errors.append(f'SEC tickers: {e}')
for w in WANT_US:
    sym = w['symbol'].upper()
    cik = str(w.get('cik') or '').zfill(10)
    if not cik.lstrip('0') and sym in sec_names:
        cik = str(sec_names[sym]['cik_str']).zfill(10)
    if not cik.lstrip('0'):
        errors.append(f'SEC {sym}: no CIK (add "cik" to watchlist.json)')
        continue
    try:
        sub = getjson(f'https://data.sec.gov/submissions/CIK{cik}', user_agent=SEC_UA)
        rec = (sub.get('filings') or {}).get('recent') or {}
        cut = (NOW - datetime.timedelta(days=DAYS_BACK + 2)).strftime('%Y-%m-%d')
        keep = {'10-K', '10-Q', '8-K', '6-K', '20-F', '424B3'}
        rows = []
        for i, form in enumerate(rec.get('form') or []):
            if form not in keep:
                continue
            fd = rec['filingDate'][i]
            if fd < cut:
                continue
            acc = (rec.get('accessionNumber') or [''])[i]
            prim = (rec.get('primaryDocument') or [''])[i]
            rows.append({'date': fd, 'form': form,
                         'url': f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{prim}" if prim else
                                f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cik)}'})
        sec_by_sym[sym] = rows[:15]
    except Exception as e:
        errors.append(f'SEC {sym}: {e}')

# ---------------- Google News RSS (company / competitor / industry) ----------------
GN = 'https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:en'


def gn(query, hl, gl, limit):
    url = GN.format(q=urllib.parse.quote(query), hl=hl, gl=gl)
    root = ET.fromstring(curl(url, accept='application/rss+xml', extra=['-H', 'Accept: application/rss+xml']))
    rows = []
    for it in root.findall('.//item'):
        t = html.unescape((it.findtext('title') or '').strip())
        link = (it.findtext('link') or '').strip()
        pd = it.findtext('pubDate') or ''
        rows.append({'when': pd, 'title': t, 'link': link})
        if len(rows) >= limit:
            break
    return rows


news_cache, ind_cache = {}, {}
for w in WATCH:
    sym = w['symbol'].upper()
    hl, gl = ('en-IN', 'IN') if w.get('market') == 'IN' else ('en-US', 'US')
    name = w.get('name') or sym
    try:
        news_cache[sym] = gn(f'"{name}" when:1d', hl, gl, NEWS_PER_COMPANY)
    except Exception as e:
        errors.append(f'News {sym}: {e}')
        news_cache[sym] = []
    for c in (w.get('competitors') or [])[:MAX_COMP_NEWS]:
        key = c.get('s', '').upper() or c.get('n', '').upper()
        if not key or key in news_cache:
            continue
        try:
            news_cache[key] = gn(f'"{c.get("n") or key}" when:1d', hl, gl, NEWS_PER_COMP)
        except Exception as e:
            errors.append(f'News competitor {key} ({sym}): {e}')
            news_cache[key] = []
    ind = (w.get('industry') or '').strip()
    if ind and ind not in ind_cache:
        try:
            ind_cache[ind] = gn(f'"{ind}" when:1d', hl, gl, INDUSTRY_NEWS)
        except Exception as e:
            errors.append(f'News industry "{ind}": {e}')
            ind_cache[ind] = []

# ---------------- StockTwits social signal ----------------
def stocktwits(w):
    sym = w['symbol'].upper()
    st_sym = f"NSE:{sym}" if w.get('market') == 'IN' else sym
    d = getjson(f'https://api.stocktwits.com/api/2/streams/symbol/{st_sym}.json')
    ent = d.get('entity') or {}
    out = {'symbol': st_sym}
    ss = ent.get('streaming_sentiment') or {}
    if ss:
        out.update({'messages_24h': ss.get('message_count'), 'sentiment': ss.get('sentiment'),
                    'sentiment_score': ss.get('sentiment_score')})
    latest = []
    for m in (ent.get('latest_messages') or [])[:5]:
        msg = m.get('message') or m
        latest.append({'text': re.sub(r'\s+', ' ', msg.get('body') or '').strip()[:200],
                      'when': msg.get('created_at', ''), 'sentiment': (msg.get('sentiment') or {}).get('score')})
    out['latest'] = latest
    return out


# ---------------- assemble per-company files + triage ----------------
signal, quiet = [], []
index_lines = []
for w in WATCH:
    sym = w['symbol'].upper()
    ind = (w.get('industry') or '').strip()
    comp_syms = [c.get('s', '').upper() for c in (w.get('competitors') or []) if c.get('s')]
    filings = []
    if w.get('market') == 'IN':
        filings = [{'source': 'NSE', **f} for f in nse_by_sym.get(sym, [])]
        filings += [{'source': 'NSE deal', 'date': d.get('date'), 'title':
                     f"{d.get('kind')} deal {'buy' if d.get('side') == 'BUY' else 'sell'} Rs{d.get('value_cr')}cr by {d.get('client')}",
                     'url': 'https://www.nseindia.com/market-data/large-deals'} for d in nse_deals.get(sym, [])]
    else:
        filings = [{'source': 'SEC', **f} for f in sec_by_sym.get(sym, [])]
    comp_news = []
    for cs in comp_syms[:MAX_COMP_NEWS]:
        for n in news_cache.get(cs, []):
            comp_news.append({**n, 'about': cs})
    ind_news = ind_cache.get(ind, []) if ind else []
    social = {}
    try:
        social = stocktwits(w)
    except Exception as e:
        errors.append(f'StockTwits {sym}: {e}')
    n_social = social.get('messages_24h') or (len(social.get('latest') or []) * 100)
    has_signal = bool(filings) or len(news_cache.get(sym, [])) >= SIGNAL_NEWS or n_social >= SIGNAL_SOCIAL
    doc = {
        'symbol': sym, 'name': w.get('name') or sym, 'market': w.get('market', 'IN'),
        'industry': ind, 'competitors': w.get('competitors') or [],
        'fetched_ist': NOW.strftime('%a %d %b %Y %H:%M'),
        'filings': filings[:20],
        'news': news_cache.get(sym, []),
        'competitor_news': comp_news,
        'industry_news': ind_news,
        'social': social,
        'has_signal': has_signal,
    }
    json.dump(doc, open(os.path.join(RAW, f'{sym}.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    (signal if has_signal else quiet).append(sym)
    my_news = news_cache.get(sym) or []
    top = (filings[0]['title'][:90] if filings else
           (my_news[0].get('title', 'no news')[:90] if my_news else 'no news'))
    index_lines.append(f"{sym:<12} {'SIGNAL' if has_signal else 'quiet ':6} "
                       f"filings {len(filings):<3} news {len(news_cache.get(sym, [])):>2} "
                       f"social {n_social:<4} | {top}")

# group signal companies (watchlist order) into AI runs of at most MAX_GROUP
order = [w['symbol'].upper() for w in WATCH]
flat = [s for s in order if s in set(signal)]
groups = [{'i': k, 'group': ' '.join(flat[k * MAX_GROUP:(k + 1) * MAX_GROUP])}
          for k in range((len(flat) + MAX_GROUP - 1) // MAX_GROUP)]
triage = {'date': DATE, 'signal': flat, 'quiet': [s for s in order if s in quiet],
          'groups': groups, 'errors': errors}
json.dump(triage, open(os.path.join(OUT, 'triage.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
open(os.path.join(RAW, 'index.txt'), 'w', encoding='utf-8').write(
    f'Company tracker pre-fetch {NOW:%a %d %b %Y %H:%M} IST ({len(WATCH)} companies)\n' +
    '\n'.join(index_lines) + ('\n\nERRORS: ' + ' | '.join(errors) if errors else '\n\nNo source errors.'))
print(f'{len(flat)} of {len(WATCH)} companies have signal -> {len(groups)} digest group(s). Errors: {len(errors)}')
