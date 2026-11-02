#!/usr/bin/env python3
"""WinPilot live diagnostic. Run after fetch_feed.py in the same directory."""
import collections
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parent
FEED = BASE / 'feed.json'
REPORT = BASE / 'winpilot_diagnose.md'
FIELDS = ('direct_link', 'deadline', 'free', 'country', 'entry')

def report(data):
    items = data.get('items', [])
    if not isinstance(items, list):
        raise ValueError('feed.json: items muss eine Liste sein')
    counts = collections.Counter()
    domains = collections.Counter()
    seen = set()
    duplicate = 0
    missing = collections.Counter()
    for item in items:
        if not isinstance(item, dict):
            counts['invalid_items'] += 1
            continue
        url = item.get('url', '')
        domains[urlsplit(url).hostname or 'ohne Host'] += 1
        if url in seen:
            duplicate += 1
        seen.add(url)
        if item.get('verified') is True:
            counts['verified'] += 1
        else:
            counts['unverified'] += 1
        checks = item.get('verification') or {}
        for key in FIELDS:
            if checks.get(key) is True:
                counts[key] += 1
            elif item.get('source') != 'Google News':
                missing[key] += 1
    lines = [
        '# WinPilot – Live-Diagnose',
        '',
        f"Erzeugt: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}",
        f"Feed-Stand: {data.get('updated', 'unbekannt')}",
        f'Einträge: {len(items)}',
        f"Verifiziert: {counts['verified']}",
        f"Nicht verifiziert: {counts['unverified']}",
        f'Doppelte URLs: {duplicate}',
        f"Quellenfehler: {len(data.get('errors', []))}",
        '', '## Nachgewiesene Prüfkriterien (Anzahl)',
        *[f'- {k}: {counts[k]}' for k in FIELDS],
        '', '## Fehlende Kriterien bei Nicht-News-Quellen',
        *[f'- {k}: {missing[k]}' for k in FIELDS],
        '', '## Häufigste Quell-Domains',
        *[f'- {host}: {n}' for host, n in domains.most_common(15)],
        '', '## Beispiele: nicht verifizierte Einträge (max. 12)',
    ]
    for item in [x for x in items if isinstance(x, dict) and x.get('verified') is not True][:12]:
        title = str(item.get('title', ''))[:110].replace('\n', ' ')
        url = str(item.get('url', ''))
        parsed = urlsplit(url)
        safe_url = f'{parsed.scheme}://{parsed.netloc}{parsed.path}' if parsed.scheme in ('https', 'http') else '(ungültig)'
        checks = item.get('verification') or {}
        absent = ', '.join(k for k in FIELDS if checks.get(k) is not True)
        lines.append(f'- {title} | {safe_url} | fehlt: {absent}')
    lines += ['', '## Quellenfehler (max. 10)', *[f'- {str(e)[:200]}' for e in data.get('errors', [])[:10]], '']
    return '\n'.join(lines)

if __name__ == '__main__':
    if not FEED.is_file():
        raise SystemExit('feed.json fehlt. Zuerst fetch_feed.py ausführen.')
    data = json.loads(FEED.read_text(encoding='utf-8'))
    result = report(data)
    REPORT.write_text(result, encoding='utf-8')
    print(result)
    print(f'\nDiagnose gespeichert: {REPORT.name}')
