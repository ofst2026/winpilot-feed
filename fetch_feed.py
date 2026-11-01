#!/usr/bin/env python3
"""WinPilot 3.4: Veranstalterseiten und verlinkte Teilnahmebedingungen prüfen.

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
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; WinPilotFamily/3.2; RSS hints)'})
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

def read_official_page(url, allowed_host):
    """HTTPS, öffentliche Ziele und gleiche Veranstalter-Domain erzwingen."""
    if not safe_public_host(url): return None
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (WinPilotFamily/3.4; verification)'})
    with OPENER.open(req,timeout=9) as resp:
        final=resp.geturl()
        host=(urllib.parse.urlsplit(final).hostname or '').lower()
        if host != allowed_host or not safe_public_host(final): return None
        if 'text/html' not in resp.headers.get('Content-Type','').lower(): return None
        raw=resp.read(350_000)
        encoding=resp.headers.get_content_charset() or 'utf-8'
    source=raw.decode(encoding,errors='replace')
    parser=VisibleText(); parser.feed(source)
    text=' '.join(html.unescape(' '.join(parser.parts)).split())[:120_000]
    links=LinkCollector(); links.feed(source)
    return text, source, links.links, final


def check_page(url,country,diagnostic=False):
    """Prüft Veranstalterseite plus höchstens drei relevante verlinkte Regel-Seiten.

    Belege müssen auf derselben Veranstalter-Domain liegen. Kein Treffer wird
    bestätigt, wenn wesentliche Bedingungen unbekannt bleiben.
    """
    checks={'direct_link':False,'deadline':False,'free':False,'country':False,'entry':False}
    host=(urllib.parse.urlsplit(url).hostname or '').lower()
    if not host or any(x in host for x in AGGREGATOR_HOST_PARTS):
        return False,'',checks
    try:
        primary=read_official_page(url,host)
        if not primary:
            if diagnostic: print('[Prüfung] Veranstalterseite nicht abrufbar oder Weiterleitung außerhalb der Domain',flush=True)
            return False,'',checks
        text,source,links,final=primary
        # Die Aktionsseite muss selbst einen Gewinnspielbezug aufweisen.
        has_contest=bool(re.search(r'gewinnspiel|verlosung|gewinnen',text[:16000],re.I))
        checks['direct_link']=has_contest and bool(OFFICIAL_CONTEXT.search(text))
        related=[]; visited={final}
        for href,label in links:
            if not re.search(r'teilnahmebedingungen|gewinnspielbedingungen|aktionsbedingungen|teilnahmeregeln|\bteilnahme\b',href+' '+label,re.I):
                continue
            target=urllib.parse.urljoin(final,href)
            parts=urllib.parse.urlsplit(target)
            if parts.scheme!='https' or (parts.hostname or '').lower()!=host: continue
            target=urllib.parse.urlunsplit((parts.scheme,parts.netloc,parts.path,parts.query,''))
            if target in visited: continue
            visited.add(target)
            related.append(target)
            if len(related)>=3: break
        texts=[text]; sources=[source]
        for target in related:
            try:
                page=read_official_page(target,host)
                if page:
                    texts.append(page[0]); sources.append(page[1])
            except (OSError,ValueError,UnicodeError,urllib.error.URLError): pass
        # Keine pauschalen Freigaben aus allgemeinen Website-Fußzeilen.
        combined=' '.join(texts)
        deadline=''
        for match in DEADLINE_TEXT.finditer(combined):
            try:
                date=dt.date(int(match.group(3)),int(match.group(2)),int(match.group(1)))
                if date>=TODAY:
                    deadline=date.isoformat(); checks['deadline']=True; break
            except ValueError: pass
        checks['free']=bool(FREE_TEXT.search(combined))
        checks['country']=bool(COUNTRY_TEXT[country].search(combined))
        checks['entry']=bool(ENTRY_TEXT.search(text) and (FORM_TAG.search(source) or re.search(r'teilnahmeformular|am\s+gewinnspiel\s+teilnehmen',text,re.I)))
        # Unklare Altersberechtigung und widersprechende Bedingungen bleiben ungeprüft.
        age=bool(re.search(r'(?:teilnahmeberechtigt|teilnehmen).{0,100}(?:ab\s+\d{1,2}\s+jahren|mindestens\s+\d{1,2}\s+jahre|volljährig)',combined,re.I))
        ended=bool(EXCLUDED_TEXT.search(text))
        verified=all(checks.values()) and age and not ended
        if diagnostic:
            print('[Prüfung] Kriterien: '+', '.join(f'{k}={str(v).lower()}' for k,v in checks.items())+f'; altersregel={str(age).lower()}; regelseiten={len(texts)-1}; abgelaufen_markierung={str(ended).lower()}; verifiziert={str(verified).lower()}',flush=True)
        return verified,deadline,checks
    except (OSError,ValueError,UnicodeError,urllib.error.URLError) as exc:
        if diagnostic: print('[Prüfung] Abruf fehlgeschlagen: '+type(exc).__name__,flush=True)
        return False,'',checks

def fetch_direct_search(country, query):
    """Bing RSS liefert im Unterschied zu Google News oft direkte Ergebnis-URLs.
    Suchergebnisse bleiben UNGEPRÜFT, bis die Zielseite selbst geprüft wurde.
    """
    url = 'https://www.bing.com/search?' + urllib.parse.urlencode({
        'q': query, 'format': 'rss', 'setlang': 'de-DE'
    })
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; WinPilotFamily/3.2)'})
    with urllib.request.urlopen(req, timeout=18) as response:
        data = response.read(1_500_000)
    entries = ET.fromstring(data).findall('.//channel/item')
    # Bing can silently ignore the requested search terms; report it clearly.
    print(f'[Bing] {country} | Suchbegriff={query!r} | erster Treffer={(entries[0].findtext("title") or "")[:95] if entries else "keiner"}', flush=True)
    return entries

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

def debug_rejection(title, link, reason, diagnostics):
    """Log at most ten filtered web hits; omit query strings and fragments."""
    if len(diagnostics) >= 10:
        return
    parsed = urllib.parse.urlsplit(link)
    safe_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path[:120], '', ''))
    safe_title = re.sub(r'[\r\n\t]+', ' ', title)[:110]
    diagnostics.append((reason, safe_title, safe_url))
    print(f'[Webfilter {len(diagnostics)}/10] Grund={reason} | Titel={safe_title} | URL={safe_url}', flush=True)

# Ausgangsseiten bekannter Veranstalter. Eine Domain auf dieser Liste ist
# KEIN Beweis für ein gültiges Gewinnspiel; jede Unterseite wird geprüft.
OFFICIAL_START_PAGES = [
    ('Österreich', 'https://www.kronehit.at/'),
    ('Österreich', 'https://www.energy.at/'),
    ('Deutschland', 'https://www.antenne.de/'),
    ('Deutschland', 'https://www.radiohamburg.de/'),
]

class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.title=''; self.in_title=False
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='a' and attrs.get('href'):
            self.links.append((attrs['href'],attrs.get('title','')))
        if tag=='title': self.in_title=True
    def handle_endtag(self,tag):
        if tag=='title': self.in_title=False
    def handle_data(self,data):
        if self.in_title: self.title+=data

def discover_official(country, homepage):
    """Findet mögliche Gewinnspielseiten innerhalb einer Veranstalter-Domain."""
    if not safe_public_host(homepage): return []
    req=urllib.request.Request(homepage,headers={'User-Agent':'Mozilla/5.0 (WinPilotFamily/3.2)'})
    with OPENER.open(req,timeout=12) as resp:
        if 'text/html' not in resp.headers.get('Content-Type','').lower(): return []
        raw=resp.read(350_000)
        final=resp.geturl()
    parser=LinkCollector(); parser.feed(raw.decode('utf-8',errors='replace'))
    basehost=(urllib.parse.urlsplit(final).hostname or '').lower()
    candidates=[]; seen=set()
    for href,label in parser.links:
        url=urllib.parse.urljoin(final,href)
        parsed=urllib.parse.urlsplit(url)
        host=(parsed.hostname or '').lower()
        if parsed.scheme!='https' or host!=basehost: continue
        url=urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))
        if url in seen: continue
        seen.add(url)
        if re.search(r'gewinnspiel|verlosung|mitmachen|gewinnen',parsed.path+' '+label,re.I) and not BAD.search(parsed.path+' '+label) and not re.search(r'/aktionen/?$|/programm/aktionen/?$',parsed.path,re.I):
            candidates.append((url, clean_title(label) or parsed.path.rsplit('/',1)[-1]))
    return candidates[:12]

def collect():
    results=[]; errors=[]; seen=set()
    stats={'official_links':0,'official_checked':0,'official_verified':0,'news_hints':0}
    for country,homepage in OFFICIAL_START_PAGES:
        try:
            links=discover_official(country,homepage)
            stats['official_links']+=len(links)
            print(f'[Offizielle Seiten] {homepage}: {len(links)} Kandidaten',flush=True)
            for url,label in links:
                if url in seen or stats['official_checked']>=35: continue
                seen.add(url)
                print(f'[Kandidat {stats["official_checked"]+1}] {country} | {url}',flush=True)
                verified,deadline,checks=check_page(url,country,diagnostic=True)
                stats['official_checked']+=1
                if verified: stats['official_verified']+=1
                reason=reason_for(checks,'Veranstalterseite')
                print(f'[Ergebnis] {reason}',flush=True)
                results.append({'title':label[:180] or 'Gewinnspiel beim Veranstalter',
                    'url':url,'country':country,'published':TODAY.isoformat(),
                    'deadline':deadline,'category':category_for(label),
                    'source':urllib.parse.urlsplit(homepage).hostname,
                    'description':('Automatische Vorprüfung erfolgreich; Teilnahmebedingungen selbst prüfen.' if verified else 'Ungeprüfter Hinweis: '+reason),
                    'verified':verified,'verification':checks,'verification_reason':reason})
        except Exception as exc:
            errors.append('Offizielle Seite '+homepage+': '+str(exc)[:120])
            print(f'[Offizielle Seiten] {homepage}: nicht erreichbar/auswertbar',flush=True)
    for country,query in QUERIES:
        try:
            entries=fetch_rss(country,query)
            for entry in entries:
                title=clean_title(entry.findtext('title') or '')
                url=(entry.findtext('link') or '').strip()
                if not title or not url.startswith('https://') or not RELEVANT.search(title): continue
                if BAD.search(title) or ENDED.search(title) or LOW_QUALITY.search(title): continue
                try: published=email.utils.parsedate_to_datetime(entry.findtext('pubDate') or '').date()
                except (ValueError,TypeError,OverflowError): continue
                if not 0 <= (TODAY-published).days <= 7: continue
                key=dedup_key(title)
                if key in seen: continue
                seen.add(key)
                stats['news_hints']+=1
                results.append({'title':title[:180],'url':url,'country':country,
                    'published':published.isoformat(),'deadline':deadline_from_title(title),
                    'category':category_for(title),'source':clean_title(entry.findtext('source') or 'Google News')[:90],
                    'description':'Ungeprüfter Pressehinweis: kein direkter Veranstalterlink.',
                    'verified':False,'verification':{'direct_link':False,'deadline':False,'free':False,'country':False,'entry':False},
                    'verification_reason':'Pressehinweis: keine bestätigte Veranstalterseite'})
        except Exception as exc:
            errors.append('Google News '+country+': '+str(exc)[:120])
    print('[Diagnose] '+', '.join(f'{k}={v}' for k,v in stats.items()),flush=True)
    results.sort(key=lambda x:(bool(x['verified']),x['published']),reverse=True)
    return results[:60],errors

def main():
    results,errors=collect()
    if not results:
        raise SystemExit('Keine Treffer: vorhandene feed.json bleibt unverändert.')
    output={'updated':NOW.strftime('%Y-%m-%d %H:%M UTC'),
        'updated_at':NOW.strftime('%Y-%m-%d %H:%M UTC'),'items':results,'errors':errors}
    Path(__file__).with_name('feed.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{len(results)} Hinweise, davon {sum(bool(x["verified"]) for x in results)} streng geprüft; {len(errors)} Quellenfehler')

if __name__=='__main__': main()
