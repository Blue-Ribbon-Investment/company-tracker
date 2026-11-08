"""Build the searchable company directory into <outdir>/directory.json.

Usage:  python -I -X utf8 fetch_directory.py <outdir>     (outdir = runs/YYYY-MM-DD)

Starts from the committed static directory.json in the repo root (all NSE mainboard companies),
so the "add a company" box ALWAYS has something to search. Then, best-effort, it refreshes that
list with the live NSE search API (adds new IPOs and NSE SME) when NSE is reachable from this
machine (GitHub's servers usually, a laptop usually not). The live part never blocks the build:
if it returns nothing, the static list still ships.
"""
import sys, os, json, subprocess, datetime

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, 'directory.json')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
COOKIES = os.path.join(OUT, 'nse_cookies.txt')
BASE = 'https://www.nseindia.com'


def curl(url, referer=None, accept='application/json'):
    cmd = ['curl', '-s', '-L', '-m', '30', '-A', UA, '-H', 'Accept: ' + accept,
           '-b', COOKIES, '-c', COOKIES, '-H', 'Referer: ' + (referer or BASE), url]
    return subprocess.run(cmd, capture_output=True, timeout=60).stdout.decode('utf-8', 'ignore')


# Start from the committed static list (never empty), keyed by symbol.
by_sym = {}
if os.path.exists(STATIC):
    for e in json.load(open(STATIC, encoding='utf-8')):
        if e.get('s'):
            by_sym[e['s'].upper()] = e
base_count = len(by_sym)

# Best-effort live refresh from NSE (prefix-scan). Silently skips anything NSE blocks.
live_added = 0
try:
    curl(BASE + '/')
    for p in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789':
        try:
            d = json.loads(curl(f'{BASE}/api/search?searchQuery={p}'))
        except Exception:
            continue
        for e in (d.get('equities') or []):
            ex = (e.get('exchange') or '').upper()
            if ex not in ('NSE', 'NSE SME') or not e.get('symbol'):
                continue
            k = e['symbol'].upper()
            if k in by_sym:
                continue
            by_sym[k] = {'s': k, 'n': (e.get('name') or '').strip(), 'ex': ex}
            live_added += 1
except Exception:
    pass

rows = sorted(by_sym.values(), key=lambda z: (z.get('n') or '').lower())
json.dump(rows, open(os.path.join(OUT, 'directory.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, separators=(',', ':'))
print(f'directory: {len(rows)} companies ({base_count} static + {live_added} live).')
