"""Build the searchable company directory (NSE + NSE SME: code + name) into directory.json.

Usage:  python -I -X utf8 fetch_directory.py <outdir>     (outdir = runs/YYYY-MM-DD)

The NSE search API is only reachable from GitHub's servers (blocked on most laptops), so on a
laptop run this writes an empty directory and notes it; on the daily GitHub run it works.
Prefix-scan of the search API (one letter/digit at a time), deduplicated.
"""
import sys, os, json, subprocess, datetime

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
COOKIES = os.path.join(OUT, 'nse_cookies.txt')
BASE = 'https://www.nseindia.com'
REF = 'https://www.nseindia.com/equities-stock-list'


def curl(url, referer=None, accept='application/json'):
    cmd = ['curl', '-s', '-L', '-m', '30', '-A', UA, '-H', 'Accept: ' + accept,
           '-b', COOKIES, '-c', COOKIES, '-H', 'Referer: ' + (referer or BASE), url]
    return subprocess.run(cmd, capture_output=True, timeout=60).stdout.decode('utf-8', 'ignore')


seen, rows, errors = {}, [], []
try:
    curl(BASE + '/')          # cookie prime
except Exception as e:
    errors.append(f'cookie prime: {e}')
for p in [c for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789']:
    try:
        d = json.loads(curl(f'{BASE}/api/search?searchQuery={p}'))
        for e in (d.get('equities') or []):
            ex = (e.get('exchange') or '').upper()
            if ex not in ('NSE', 'NSE SME') or not e.get('symbol'):
                continue
            k = e['symbol'].upper()
            if k in seen:
                continue
            seen[k] = True
            rows.append({'s': k, 'n': (e.get('name') or '').strip(), 'ex': ex})
    except Exception as e:
        errors.append(f'prefix {p}: {e}')
    print(f'prefix {p}: total {len(rows)}', end='\r')
json.dump(rows, open(os.path.join(OUT, 'directory.json'), 'w', encoding='utf-8'), ensure_ascii=False)
if errors:
    print(f'\n{len(rows)} companies; ERRORS: ' + ' | '.join(errors[:8]))
else:
    print(f'\ndirectory: {len(rows)} companies, no errors.')
