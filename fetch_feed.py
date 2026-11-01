#!/usr/bin/env python3
"""WinPilot 2.9: konservative Suche mit zusätzlicher Seitenprüfung.

RSS-Meldungen sind KEINE bestätigten aktiven Gewinnspiele. Zusätzliche gezielte Suchanfragen. Keine automatische Teilnahme.
Die Ausgabe bleibt kompatibel mit WinPilot Family 2.3.
"""
import datetime as dt
import email.utils
import json
import html
import ipaddress
import socket
from html.parser import HTMLParser
import re
import urllib.parse
import urllib.request
import urllib.error
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
    ('Österreich', '"Gewinnspiel" "Teilnahmebedingungen" "Österreich" -lotto -casino'),
    ('Deutschland', '"Gewinnspiel" "Teilnahmebedingungen" "Deutschland" -lotto -casino'),
    ('Österreich', '"jetzt teilnehmen" "Gewinnspiel" Österreich -lotto -casino'),
    ('Deutschland', '"jetzt teilnehmen" "Gewinnspiel" Deutschland -lotto -casino'),
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
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; WinPilotFamily/2.9; RSS hints)'})
    with urllib.request.urlopen(req,timeout=25) as response: body=response.read(2_000_000)
    return ET.fromstring(body).findall('.//channel/item')

def clean_title(title):
    return ' '.join(title.split())

def dedup_key(title):
    # Google News titles typically end in " - Publisher".
    title=re.sub(r'\s+[-–|]\s+[^-–|]{2,75}$','',title)
    return re.sub(r'[^\w]+',' ',title.casefold()).strip()


# Strenge Prüfung: Unbekannte Bedingungen bedeuten immer verified=False.
# Automatische Teilnahme wird nicht durchgeführt.
DEADLINE_TEXT = re.compile(r'(?:teilnahmeschluss|einsendeschluss|teilnahme\s+bis|aktionsende)\s*:?\s*(?:am\s*)?(\d{1,2})\.(\d{1,2})\.(20\d{2})', re.I)
FREE_TEXT = re.compile(r'kostenlose\s+teilnahme|teilnahme\s+ist\s+kostenlos|teilnahme\s+ist\s+gratis|teilnahme\s+ist\s+unentgeltlich', re.I)
COUNTRY_TEXT = {
    'Österreich': re.compile(r'teilnahmeberechtigt.{0,160}(?:österreich|wohnsitz\s+in\s+österreich)|(?:wohnsitz|wohnhaft)\s+in\s+österreich.{0,160}teilnahme', re.I | re.S),
    'Deutschland': re.compile(r'teilnahmeberechtigt.{0,160}(?:deutschland|bundesrepublik)|(?:wohnsitz|wohnhaft)\s+in\s+deutschland.{0,160}teilnahme', re.I | re.S),
}
ENTRY_TEXT = re.compile(r'(?:jetzt\s+teilnehmen|am\s+gewinnspiel\s+teilnehmen|teilnahmeformular|jetzt\s+mitmachen)', re.I)
EXCLUDED_TEXT = re.compile(r'\b(?:abgelaufen|gewinnspiel\s+beendet|teilnahme\s+nicht\s+mehr\s+möglich)\b', re.I)
GOOGLE_HOSTS = {'news.google.com', 'google.com', 'www.google.com'}
# Artikel und Sammelportale gelten nicht als direkte Veranstalter-Teilnahmeseiten.
AGGREGATOR_HOST_PARTS = ('news.google.', 'google.com', 'bing.com', 'facebook.com', 'instagram.com', 'pinterest.', 'youtube.com')
OFFICIAL_CONTEXT = re.compile(r'teilnahmebedingungen|teilnahmeberechtigt|teilnahmeformular', re.I)
FORM_TAG = re.compile(r'<form\b', re.I)


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','noscript'): self.skip+=1
    def handle_endtag(self, tag):
        if tag in ('script','style','noscript') and self.skip: self.skip-=1
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)

def safe_public_host(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password: return False
    host=parsed.hostname.lower()
    if host in ('localhost',) or host.endswith(('.local','.internal')): return False
    try:
        infos=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)
    except (OSError,ValueError): return False

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_public_host(newurl): raise urllib.error.URLError('Unsichere Weiterleitung')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

OPENER=urllib.request.build_opener(SafeRedirect())

def check_page(url,country):
    """Bestätigt nur explizite Angaben auf einer erreichbaren HTTPS-Seite."""
    checks={'direct_link':False,'deadline':False,'free':False,'country':False,'entry':False}
    if not safe_public_host(url): return False,'',checks
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; WinPilotFamily/2.9; verification)'})
        with OPENER.open(req,timeout=9) as resp:
            final=resp.geturl()
            if not safe_public_host(final): return False,'',checks
            host=(urllib.parse.urlsplit(final).hostname or '').lower()
            if host in GOOGLE_HOSTS or host.endswith('.google.com') or any(x in host for x in AGGREGATOR_HOST_PARTS): return False,'',checks
            typ=resp.headers.get('Content-Type','').lower()
            if 'text/html' not in typ: return False,'',checks
            raw=resp.read(350_000)
            encoding=resp.headers.get_content_charset() or 'utf-8'
        parser=VisibleText(); parser.feed(raw.decode(encoding,errors='replace'))
        text=' '.join(html.unescape(' '.join(parser.parts)).split())[:120_000]
        # Eine erreichbare Nachrichtenseite allein ist noch kein direkter Teilnahmelink.
        checks['direct_link']=bool(OFFICIAL_CONTEXT.search(text))
        m=DEADLINE_TEXT.search(text)
        deadline=''
        if m:
            try:
                date=dt.date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
                if date>=TODAY:
                    deadline=date.isoformat(); checks['deadline']=True
            except ValueError: pass
        checks['free']=bool(FREE_TEXT.search(text))
        checks['country']=bool(COUNTRY_TEXT[country].search(text))
        checks['entry']=bool(ENTRY_TEXT.search(text) and (FORM_TAG.search(raw.decode(encoding,errors='replace')) or re.search(r'teilnahmeformular|am\s+gewinnspiel\s+teilnehmen',text,re.I)))
        verified=all(checks.values()) and not EXCLUDED_TEXT.search(text)
        return verified,deadline,checks
    except (OSError,ValueError,UnicodeError,urllib.error.URLError):
        return False,'',checks

def fetch_direct_search(country, query):
    """Bing RSS liefert im Unterschied zu Google News oft direkte Ergebnis-URLs.
    Suchergebnisse bleiben UNGEPRÜFT, bis die Zielseite selbst geprüft wurde.
    """
    url = 'https://www.bing.com/search?' + urllib.parse.urlencode({
        'q': query, 'format': 'rss', 'setlang': 'de-DE', 'cc': 'AT' if country == 'Österreich' else 'DE'
    })
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; WinPilotFamily/2.9)'})
    with urllib.request.urlopen(req, timeout=18) as response:
        data = response.read(1_500_000)
    return ET.fromstring(data).findall('.//channel/item')

DIRECT_QUERIES = [
    ('Österreich', 'Gewinnspiel Teilnahmebedingungen Teilnahmeschluss kostenlos Österreich'),
    ('Deutschland', 'Gewinnspiel Teilnahmebedingungen Teilnahmeschluss kostenlos Deutschland'),
    ('Österreich', 'Verlosung jetzt teilnehmen kostenlos Österreich'),
    ('Deutschland', 'Verlosung jetzt teilnehmen kostenlos Deutschland'),
]

AGGREGATOR_EXTRA = ('gewinnspiel-portal', 'gewinnspielportal', 'gewinnspielverzeichnis')

def reason_for(checks, source_type):
    if source_type == 'Google News':
        return 'Pressehinweis: kein bestätigter direkter Veranstalterlink'
    labels = {'direct_link': 'Direkte Veranstalterseite nicht nachgewiesen',
              'deadline': 'Gültige Teilnahmefrist nicht nachgewiesen',
              'free': 'Kostenlose Teilnahme nicht nachgewiesen',
              'country': 'Teilnahmeberechtigung für das Land nicht nachgewiesen',
              'entry': 'Teilnahmemöglichkeit nicht nachgewiesen'}
    missing = [label for key, label in labels.items() if not checks.get(key)]
    return '; '.join(missing) if missing else 'Prüfung erfolgreich'

def collect():
    seen=set(); results=[]; errors=[]; checked_count=0
    # Direkte Web-Suchergebnisse zuerst prüfen, News-Meldungen nur als Hinweise.
    search_sets = [(country, query, 'Websuche') for country, query in DIRECT_QUERIES]
    search_sets += [(country, query, 'Google News') for country, query in QUERIES]
    for country, query, kind in search_sets:
        try:
            entries = fetch_direct_search(country, query) if kind == 'Websuche' else fetch_rss(country, query)
            for entry in entries:
                title=clean_title(entry.findtext('title') or '')
                link=(entry.findtext('link') or '').strip()
                if not title or not link.startswith('https://') or not RELEVANT.search(title): continue
                if BAD.search(title) or ENDED.search(title) or LOW_QUALITY.search(title): continue
                host=(urllib.parse.urlsplit(link).hostname or '').lower()
                if kind == 'Websuche' and (any(x in host for x in AGGREGATOR_HOST_PARTS + AGGREGATOR_EXTRA) or host.endswith('.ch')): continue
                try:
                    published=email.utils.parsedate_to_datetime(entry.findtext('pubDate') or '').date()
                except (ValueError,TypeError,OverflowError):
                    # Websuche hat nicht immer ein Veröffentlichungsdatum.
                    if kind == 'Google News': continue
                    published=TODAY
                if not 0 <= (TODAY-published).days <= 7: continue
                deadline=deadline_from_title(title)
                if deadline and deadline < TODAY.isoformat(): continue
                key=dedup_key(title)
                if not key or key in seen: continue
                seen.add(key)
                source=clean_title(entry.findtext('source') or (host if kind == 'Websuche' else 'Google News'))
                checks={'direct_link':False,'deadline':False,'free':False,'country':False,'entry':False}
                verified=False; checked_deadline=''
                if kind == 'Websuche' and checked_count < 35:
                    verified,checked_deadline,checks=check_page(link,country)
                    checked_count+=1
                if checked_deadline: deadline=checked_deadline
                reason=reason_for(checks,kind)
                results.append({'title':title[:180], 'url':link, 'country':country,
                    'published':published.isoformat(), 'deadline':deadline,
                    'category':category_for(title), 'source':source[:90],
                    'description':('Automatische Vorprüfung erfolgreich; Bedingungen persönlich kontrollieren.' if verified else 'Ungeprüfter Hinweis: '+reason),
                    'verified':verified, 'verification':checks, 'verification_reason':reason})
        except Exception as exc:
            errors.append(kind+' / '+country+': '+str(exc)[:130])
    results.sort(key=lambda x:(bool(x['verified']),x['published']),reverse=True)
    return results[:60],errors

def main():
    results,errors=collect()
    if len(errors)==len(QUERIES)+len(DIRECT_QUERIES):
        raise SystemExit('Alle RSS-Abfragen fehlgeschlagen; vorhandene feed.json bleibt unverändert.')
    output={'updated':NOW.strftime('%Y-%m-%d %H:%M UTC'), 'updated_at':NOW.strftime('%Y-%m-%d %H:%M UTC'), 'items':results, 'errors':errors}
    Path(__file__).with_name('feed.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{len(results)} Hinweise, davon {sum(bool(x["verified"]) for x in results)} streng geprüft; {len(errors)} Quellenfehler')

if __name__=='__main__': main()
