"""Turn a company list into watchlist.json entries (adds to the existing list).

Usage:
  python -I -X utf8 import_watchlist.py names.txt          # one name or "SYM, Name" per line
  python -I -X utf8 import_watchlist.py screener_in.csv    # a screener.in CSV export

Recognises screener.in's columns (Name, Symbol, Market, ...). Names without a symbol are used as
the search name; competitors and industry are left blank for the "Suggest competitors" step to fill.
US-listed companies get their SEC CIK looked up (company_tickers.json) when no CIK is given.
"""
import sys, os, json, csv, re, subprocess

path = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
SEC_UA = 'Blue-Ribbon-CompanyTracker contact: newsletterchidananda@gmail.com'


def load():
    p = os.path.join(here, 'watchlist.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else []


def save(watch):
    json.dump(watch, open(os.path.join(here, 'watchlist.json'), 'w', encoding='utf-8'), indent=2, ensure_ascii=False)


def norm(s):
    return re.sub(r'[^A-Z0-9]', '', (s or '').upper())


watch = load()
have = {norm(w.get('symbol')) for w in watch}
added = []

def add(sym, name, market='IN', cik=None):
    k = norm(sym)
    if not k or k in have:
        return
    entry = {'symbol': sym, 'name': name or sym, 'market': market, 'exchange': 'NSE' if market == 'IN' else 'US',
             'industry': '', 'competitors': []}
    if market == 'US':
        entry['cik'] = cik
    watch.append(entry)
    have.add(k)
    added.append(sym)


if path.lower().endswith('.csv'):
    for row in csv.DictReader(open(path, encoding='utf-8-sig')):
        cols = {norm(k2).lower(): v for k2, v in row.items()}
        sym = next((cols[x] for x in ('symbol', 'tsym', 'ticker') if cols.get(x)), '')
        name = next((cols[x] for x in ('name', 'company', 'companyname') if cols.get(x)), '')
        mkt = (cols.get('market') or '').strip().upper()
        market = 'US' if mkt in ('US', 'USD', 'NASDAQ', 'NYSE', 'AMEX') or not mkt else 'IN'
        add(sym or name, name or sym, market)
else:
    # one entry per line: "SYM, Name" or "Name"
    US_NAMES = {}
    try:
        tick = json.loads(subprocess.run(['curl', '-s', '-m', '30', '-A', SEC_UA,
                                          'https://www.sec.gov/files/company_tickers.json'],
                                         capture_output=True, timeout=60).stdout.decode('utf-8', 'ignore'))
        US_NAMES = {norm(v['ticker']): str(v['cik_str']).zfill(10) for v in tick.values()}
    except Exception:
        pass
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p.strip() for p in line.split(',', 1)]
        sym = norm(parts[0])
        name = parts[1].strip() if len(parts) > 1 else parts[0].strip()
        if not name or len(name) < 2:
            name = parts[0].strip()
        k = norm(name)
        if k in US_NAMES or sym in US_NAMES:
            add(sym or name, name, 'US', US_NAMES.get(k) or US_NAMES.get(sym))
        else:
            add(sym or name, name, 'IN')

save(watch)
print(f'{len(added)} added: {", ".join(added) or "none (all already in the list)"}; total {len(watch)}.')
