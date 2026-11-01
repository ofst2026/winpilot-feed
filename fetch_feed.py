#!/usr/bin/env python3
"""WinPilot 2.1: konservative RSS-Hinweise, keine verifizierten Teilnahmelinks."""
import datetime as dt
import email.utils
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.date()
QUERIES = [
    ('Österreich', '"Gewinnspiel" "teilnehmen" Österreich -lotto -casino -wetten'),
    ('Österreich', '"Gewinnspiel" "Teilnahmeschluss" Österreich -lotto -casino'),
    ('Deutschland', '"Gewinnspiel" "teilnehmen" Deutschland -lotto -casino -wetten'),
    ('Deutschland', '"Gewinnspiel" "Teilnahmeschluss" Deutschland -lotto -casino'),
]
BAD = re.compile(r'lotto|lotterie|casino|sportwetten|glücksspiel|jackpot|poker|wetten|gewinnzahlen|rubbellos|sportwette|spielautomat', re.I)
EXCLUDE = re.compile(r'gewinnspielauflösung|gewinner(?:innen)?\s+(?:stehen|wurden)|gewinner\s+gekürt|gewinnspiel\s+beendet|rückblick|gewinnspielbetrug|warnung\s+vor\s+gewinnspiel', re.I)
RELEVANT = re.compile(r'gewinnspiel|verlosung|mitmachen\s+und\s+gewinnen|jetzt\s+gewinnen|teilnahmeplätz', re.I)
MONTHS = {'januar':1,'februar':2,'märz':3,'maerz':3,'april':4,'mai':5,'juni':6,'juli':7,'august':8,'september':9,'oktober':10,'november':11,'dezember':12}

def deadline_from_title(title):
    """Nur explizite, eindeutige Frist mit Jahr; keine Schätzung."""
    m = re.search(r'(?:teilnahmeschluss|einsendeschluss|bis zum|bis)\s*[:]?\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})\b', title, re.I)
    if m:
        try: return dt.date(int(m.group(3)),int(m.group(2)),int(m.group(1))).isoformat()
        except ValueError: return ''
    m = re.search(r'(?:teilnahmeschluss|einsendeschluss|bis zum|bis)\s*[:]?\s*(\d{1,2})\.\s*('+'|'.join(MONTHS)+r')\s+(20\d{2})\b',title,re.I)
    if m:
        try: return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
        except ValueError: return ''
    return ''

def category_for(title):
    categories = [('Reisen',r'reise|urlaub|hotel|flug|übernachtung'),('Technik',r'smartphone|laptop|tablet|fernseher|technik|kopfhörer|konsole'),('Auto',r'auto|fahrzeug|e-bike|fahrrad'),('Gutscheine',r'gutschein|geschenkkarte'),('Geld',r'bargeld|geldpreis'),('Sachpreise',r'paket|set|tickets|eintrittskarten|buch')]
    for category,pattern in categories:
        if re.search(pattern,title,re.I): return category
    return 'Sonstiges'

def fetch_rss(country, query):
    region = 'AT' if country == 'Österreich' else 'DE'
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q':query+' when:7d','hl':'de','gl':region,'ceid':region+':de'})
    req = urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; WinPilotFamily/2.1; RSS hints)'})
    with urllib.request.urlopen(req,timeout=25) as response: body=response.read(2_000_000)
    return ET.fromstring(body).findall('.//channel/item')

seen=set(); results=[]; errors=[]
for country,query in QUERIES:
    try:
        for entry in fetch_rss(country,query):
            title=' '.join((entry.findtext('title') or '').split())
            link=(entry.findtext('link') or '').strip()
            if not title or not link.startswith('https://') or not RELEVANT.search(title) or BAD.search(title) or EXCLUDE.search(title): continue
            date_text=entry.findtext('pubDate') or ''
            try:
                published=email.utils.parsedate_to_datetime(date_text).date()
                if (TODAY-published).days > 7 or published > TODAY+dt.timedelta(days=1): continue
            except (ValueError,TypeError,OverflowError): continue
            deadline=deadline_from_title(title)
            if deadline and deadline < TODAY.isoformat(): continue
            # Same title syndicated by several publishers is not a new contest.
            key=re.sub(r'\s*[-–|]\s*[^-–|]{2,65}$','',title).strip().casefold()
            key=re.sub(r'[^\w]+',' ',key).strip()
            if key in seen: continue
            seen.add(key)
            source=entry.findtext('source') or 'Google News'
            results.append({'title':title[:180],'url':link,'country':country,'published':published.isoformat(), 'deadline':deadline,'category':category_for(title),'source':source[:90], 'description':'Pressehinweis – Teilnahmelink, Frist, Kostenfreiheit und Berechtigung beim Veranstalter prüfen.', 'verified':False})
    except Exception as exc:
        errors.append(country+': '+str(exc)[:160])
results.sort(key=lambda x:x['published'],reverse=True)
output={'updated':NOW.strftime('%Y-%m-%d %H:%M UTC'),'updated_at':NOW.strftime('%Y-%m-%d %H:%M UTC'),'items':results[:60], 'errors':errors}
# Bei einem vollständigen RSS-Ausfall keine zuvor funktionierende Liste überschreiben.
if len(errors)==len(QUERIES):
    raise SystemExit('Alle RSS-Quellen fehlgeschlagen; feed.json bleibt unverändert.')
Path(__file__).with_name('feed.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'{len(output["items"])} gefilterte Hinweise; {len(errors)} Quellenfehler')
