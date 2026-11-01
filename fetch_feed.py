#!/usr/bin/env python3
"""WinPilot 2.4: konservative Suche nach kostenlosen Gewinnspiel-Hinweisen.

RSS-Meldungen sind KEINE bestätigten aktiven Gewinnspiele. Keine automatische Teilnahme.
Die Ausgabe bleibt kompatibel mit WinPilot Family 2.3.
"""
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
    ('Österreich', 'Gewinnspiel teilnehmen Österreich -lotto -casino -wetten'),
    ('Österreich', 'Verlosung mitmachen Österreich -lotto -casino -wetten'),
    ('Österreich', 'Gewinnspiel Teilnahmeschluss Österreich -lotto -casino -wetten'),
    ('Deutschland', 'Gewinnspiel teilnehmen Deutschland -lotto -casino -wetten'),
    ('Deutschland', 'Verlosung mitmachen Deutschland -lotto -casino -wetten'),
    ('Deutschland', 'Gewinnspiel Teilnahmeschluss Deutschland -lotto -casino -wetten'),
]
BAD = re.compile(r'lotto|lotterie|casino|sportwetten|glücksspiel|jackpot|poker|wetten|gewinnzahlen|rubbellos|sportwette|spielautomat|tombola\s+mit\s+einsatz', re.I)
ENDED = re.compile(r'\b(?:beendet|abgelaufen|vorbei|ausgelost|auslosung\s+erfolgt|gewinner\s+(?:stehen\s+fest|gekürt|ermittelt)|gewinnerinnen\s+(?:stehen\s+fest|gekürt|ermittelt)|gewinnspielauflösung|gewinnspielbetrug)\b|warnung\s+vor\s+(?:dem\s+)?gewinnspiel|rückblick\s+auf\s+(?:das\s+)?gewinnspiel', re.I)
RELEVANT = re.compile(r'gewinnspiel|verlosung|mitmachen\s+und\s+gewinnen|jetzt\s+gewinnen|teilnahmeplätz', re.I)
LOW_QUALITY = re.compile(r'gewinnspiel(?:e)?\s+(?:im\s+)?überblick|die\s+besten\s+gewinnspiele|gewinnspiel-?kalender|adventskalender\s+\d{4}|gewinnspiel\s+tipps|gewinnspiele\s+finden', re.I)
MONTHS = {'januar':1,'februar':2,'märz':3,'maerz':3,'april':4,'mai':5,'juni':6,'juli':7,'august':8,'september':9,'oktober':10,'november':11,'dezember':12}

def deadline_from_title(title):
    """Nur explizite Fristen MIT Jahr erkennen; nie ein Jahr hinzudichten."""
    m = re.search(r'(?:teilnahmeschluss|einsendeschluss|bis\s+zum|bis)\s*:?\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})\b', title, re.I)
    if m:
        try: return dt.date(int(m.group(3)),int(m.group(2)),int(m.group(1))).isoformat()
        except ValueError: return ''
    m = re.search(r'(?:teilnahmeschluss|einsendeschluss|bis\s+zum|bis)\s*:?\s*(\d{1,2})\.\s*('+'|'.join(MONTHS)+r')\s+(20\d{2})\b',title,re.I)
    if m:
        try: return dt.date(int(m.group(3)),MONTHS[m.group(2).lower()],int(m.group(1))).isoformat()
        except ValueError: return ''
    return ''

def category_for(title):
    categories = [('Reisen',r'reise|urlaub|hotel|flug|übernachtung'),('Technik',r'smartphone|laptop|tablet|fernseher|technik|kopfhörer|konsole'),('Auto',r'auto|fahrzeug|e-bike|fahrrad'),('Gutscheine',r'gutschein|geschenkkarte'),('Geld',r'bargeld|geldpreis'),('Sachpreise',r'paket|set|tickets|eintrittskarten|buch')]
    for category,pattern in categories:
        if re.search(pattern,title,re.I): return category
    return 'Sonstiges'

def fetch_rss(country,query):
    region = 'AT' if country=='Österreich' else 'DE'
    url='https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':query+' when:7d','hl':'de','gl':region,'ceid':region+':de'})
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; WinPilotFamily/2.4; RSS hints)'})
    with urllib.request.urlopen(req,timeout=25) as response: body=response.read(2_000_000)
    return ET.fromstring(body).findall('.//channel/item')

def clean_title(title):
    return ' '.join(title.split())

def dedup_key(title):
    # Google News titles typically end in " - Publisher".
    title=re.sub(r'\s+[-–|]\s+[^-–|]{2,75}$','',title)
    return re.sub(r'[^\w]+',' ',title.casefold()).strip()

def collect():
    seen=set(); results=[]; errors=[]
    for country,query in QUERIES:
        try:
            for entry in fetch_rss(country,query):
                title=clean_title(entry.findtext('title') or '')
                link=(entry.findtext('link') or '').strip()
                if not title or not link.startswith('https://') or not RELEVANT.search(title): continue
                if BAD.search(title) or ENDED.search(title) or LOW_QUALITY.search(title): continue
                try:
                    published=email.utils.parsedate_to_datetime(entry.findtext('pubDate') or '').date()
                except (ValueError,TypeError,OverflowError): continue
                if not 0 <= (TODAY-published).days <= 7: continue
                deadline=deadline_from_title(title)
                if deadline and deadline < TODAY.isoformat(): continue
                key=dedup_key(title)
                if not key or key in seen: continue
                seen.add(key)
                source=clean_title(entry.findtext('source') or 'Google News')
                results.append({'title':title[:180], 'url':link, 'country':country,
                    'published':published.isoformat(), 'deadline':deadline,
                    'category':category_for(title), 'source':source[:90],
                    'description':'Ungeprüfter Pressehinweis. Frist, kostenlose Teilnahme und Berechtigung beim Veranstalter prüfen.',
                    'verified':False})
        except Exception as exc:
            errors.append(country+': '+str(exc)[:160])
    results.sort(key=lambda x:x['published'],reverse=True)
    return results[:60],errors

def main():
    results,errors=collect()
    if len(errors)==len(QUERIES):
        raise SystemExit('Alle RSS-Abfragen fehlgeschlagen; vorhandene feed.json bleibt unverändert.')
    output={'updated':NOW.strftime('%Y-%m-%d %H:%M UTC'), 'updated_at':NOW.strftime('%Y-%m-%d %H:%M UTC'), 'items':results, 'errors':errors}
    Path(__file__).with_name('feed.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{len(results)} ungeprüfte, gefilterte Hinweise; {len(errors)} Quellenfehler')

if __name__=='__main__': main()
