#!/usr/bin/env python3
"""WinPilot 4.1: Veranstalterseiten und verlinkte Teilnahmebedingungen prüfen.

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

def extract_deadline(text):
    """Return the earliest explicit future closing date near a deadline label."""
    labels=r'(?:teilnahmeschluss|einsendeschluss|aktionsende|teilnahme\s+bis|teilnahmezeitraum.{0,60}?bis|gewinnspiel\s+endet\s+am)'
    date=r'(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(20\d{2})'
    matches=[]
    for m in re.finditer(labels+r'\s*:?\s*(?:am\s*)?'+date,text,re.I):
        try:
            d=dt.date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
            if d>=TODAY: matches.append(d)
        except ValueError: pass
    month_names='|'.join(MONTHS)
    for m in re.finditer(labels+r'\s*:?\s*(?:am\s*)?(\d{1,2})\.?\s*('+month_names+r')\s+(20\d{2})',text,re.I):
        try:
            d=dt.date(int(m.group(3)),MONTHS[m.group(2).lower()],int(m.group(1)))
            if d>=TODAY: matches.append(d)
        except ValueError: pass
    return min(matches).isoformat() if matches else ''

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
DEADLINE_TEXT = re.compile(r'(?:teilnahmeschluss|einsendeschluss|teilnahme\s+bis|aktionsende|teilnahmezeitraum.{0,90}?bis|gewinnspiel\s+endet\s+am)\s*:?\s*(?:am\s*)?(\d{1,2})\.(\d{1,2})\.(20\d{2})', re.I)
FREE_TEXT = re.compile(r'kostenlose\s+teilnahme|teilnahme\s+(?:ist|erfolgt)\s+(?:kostenlos|gratis|unentgeltlich)|teilnahme\s+ohne\s+(?:kosten|kauf|zahlung)|(?:keine|ohne)\s+(?:teilnahmegebühr|teilnahmegebuehr|kaufverpflichtung)', re.I)
COUNTRY_TEXT = {
    'Österreich': re.compile(r'teilnahmeberechtigt.{0,160}(?:österreich|wohnsitz\s+in\s+österreich)|(?:wohnsitz|wohnhaft)\s+in\s+österreich.{0,160}teilnahme', re.I | re.S),
    'Deutschland': re.compile(r'teilnahmeberechtigt.{0,160}(?:deutschland|bundesrepublik)|(?:wohnsitz|wohnhaft)\s+in\s+deutschland.{0,160}teilnahme', re.I | re.S),
}
ENTRY_TEXT = re.compile(r'(?:jetzt\s+teilnehmen|am\s+gewinnspiel\s+teilnehmen|teilnahmeformular|jetzt\s+mitmachen|hier\s+teilnehmen|mitmachen\s+und\s+gewinnen)', re.I)
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
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (WinPilotFamily/4.1; verification)'})
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
        has_contest=bool(re.search(r'gewinnspiel|verlosung|gewinnen',text[:16000],re.I)) and is_contest_candidate(url, text[:350])
        # Ein direkter Veranstalterlink wird durch die konkrete Aktionsseite
        # belegt, nicht durch das Vorhandensein eines Regel-Keywords.
        checks['direct_link']=has_contest
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
        deadline=extract_deadline(combined)
        checks['deadline']=bool(deadline)
        checks['free']=bool(FREE_TEXT.search(combined))
        checks['country']=bool(COUNTRY_TEXT[country].search(combined))
        # Manche Formulare werden per JavaScript eingebettet; dies ist nur ein
        # Indiz, keine Bestätigung einer tatsächlich funktionierenden Teilnahme.
        form_html=bool(FORM_TAG.search(source))
        form_embed=bool(re.search(r'<(?:iframe|script)\b[^>]*(?:form|gewinnspiel|contest|participat)',source,re.I))
        entry_words=bool(ENTRY_TEXT.search(text))
        # Auch ein klar beschrifteter Teilnahme-Link kann auf ein externes
        # Formular führen. Den Link nur als Indiz werten, wenn das Ziel HTTPS
        # verwendet und kein Social-/Nachrichtenaggregator ist.
        entry_link=False
        for href,label in links:
            if not ENTRY_TEXT.search(label):
                continue
            target=urllib.parse.urljoin(final,href)
            parts=urllib.parse.urlsplit(target)
            target_host=(parts.hostname or '').lower()
            if parts.scheme=='https' and target_host and not any(x in target_host for x in AGGREGATOR_HOST_PARTS):
                entry_link=True
                break
        checks['entry']=bool(entry_words and (form_html or form_embed or entry_link))
        # Altersgrenzen sind keine pauschale Freigabe: Ü18-Angebote bleiben
        # für minderjährige Nutzer grundsätzlich ungeprüft.
        age_matches=re.findall(r'(?:ab|mindestens)\s*(\d{1,2})\s*(?:jahren|jahre)|(?:18\s*\+|volljährig)',combined,re.I)
        age_restricted=bool(age_matches or re.search(r'\b(?:volljährig|ab\s*18|18\s*\+)\b',combined,re.I))
        ended=bool(EXCLUDED_TEXT.search(text))
        verified=all(checks.values()) and not age_restricted and not ended
        if diagnostic:
            print('[Prüfung] Kriterien: '+', '.join(f'{k}={str(v).lower()}' for k,v in checks.items())+f'; altersbeschraenkung={str(age_restricted).lower()}; formular_html={str(form_html).lower()}; formular_einbettung={str(form_embed).lower()}; regelseiten={len(texts)-1}; abgelaufen_markierung={str(ended).lower()}; verifiziert={str(verified).lower()}',flush=True)
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

DIRECT_QUERIES = []  # Disabled: RSS results repeatedly irrelevant or empty.

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
MAX_CHECKED_TOTAL = 160
MAX_CHECKED_PER_SOURCE = 12
MAX_CANDIDATES_PER_SOURCE = 35

OFFICIAL_START_PAGES = [
    ('Österreich', 'https://www.kronehit.at/'),
    ('Österreich', 'https://www.liferadio.at/'),
    ('Österreich', 'https://www.energy.at/'),
    ('Deutschland', 'https://www.antenne.de/'),
    ('Deutschland', 'https://www.radiohamburg.de/'),
    # Weitere offizielle Veranstalter-Startseiten; jede Fundstelle wird
    # weiterhin einzeln geprüft, Domains sind keine Freigabe.
    ('Österreich', 'https://oe3.orf.at/'),
    ('Österreich', 'https://fm4.orf.at/'),
    ('Österreich', 'https://www.antenne.at/'),
    ('Deutschland', 'https://www.swr3.de/'),
    ('Deutschland', 'https://www.radioeins.de/'),
    ('Deutschland', 'https://www.radio7.de/'),
    ('Deutschland', 'https://www.rpr1.de/programm/aktionen/uebersicht-rpr1'),
    ('Deutschland', 'https://www.bigfm.de/programm/aktionen/uebersicht-bigfm'),
    ('Deutschland', 'https://www.charivari.de/radio/aktionen'),
    ('Deutschland', 'https://www.rtlradio.de/Aktionen/Gewinnspiele/'),
    ('Deutschland', 'https://www.104.6rtl.com/aktionen/gewinnspiele/'),
]

# Direkt erreichbare Aktionsrubriken als zweite Suchroute.
# Nicht jede Rubrik ist selbst ein Gewinnspiel.
OFFICIAL_SECTIONS = {
    'www.energy.at': ['/winzone/'],
    'www.liferadio.at': ['/gewinnspiele/', '/aktionen/'],
    'www.kronehit.at': ['/gewinnspiele/', '/aktionen/'],
    'www.antenne.at': ['/gewinnspiele/', '/aktionen/'],
    'oe3.orf.at': ['/mitmachen/'],
    'fm4.orf.at': ['/mitmachen/'],
    'www.antenne.de': ['/programm/aktionen/'],
    'www.swr3.de': ['/aktionen/'],
    'www.radio7.de': ['/aktionen/'],
    'www.rpr1.de': ['/programm/aktionen/uebersicht-rpr1'],
    'www.bigfm.de': ['/programm/aktionen/uebersicht-bigfm'],
    'www.charivari.de': ['/radio/aktionen'],
    'www.rtlradio.de': ['/Aktionen/Gewinnspiele/'],
    'www.104.6rtl.com': ['/aktionen/gewinnspiele/'],
}

class LinkCollector(HTMLParser):
    """Linktext einschließlich verschachtelter <span>-Elemente erfassen."""
    def __init__(self):
        super().__init__(); self.links=[]; self.title=''; self.in_title=False
        self.active=None; self.depth=0; self.fragments=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='a' and attrs.get('href'):
            if self.active is not None: self._finish()
            self.active=(attrs['href'],attrs.get('title',''))
            self.depth=1; self.fragments=[]
        elif self.active is not None: self.depth+=1
        if tag=='title': self.in_title=True
    def handle_endtag(self,tag):
        if self.active is not None:
            self.depth-=1
            if self.depth<=0: self._finish()
        if tag=='title': self.in_title=False
    def handle_data(self,data):
        if self.in_title: self.title+=data
        if self.active is not None: self.fragments.append(data)
    def _finish(self):
        href, title=self.active
        label=clean_title(' '.join(self.fragments)) or title
        self.links.append((href,label[:220]))
        self.active=None; self.fragments=[]; self.depth=0

# Eine Übersichtsseite darf zur Suche dienen, ist aber selbst kein Gewinnspiel.
NON_CONTEST_PATH = re.compile(
    r'(?:^|/)(?:datenschutz|privacy|newsletter|impressum|kontakt|agb|faq|'
    r'teilnahmebedingungen|gewinnspielbedingungen|sammlung|uebersicht|übersicht|'
    r'archiv|news|presse|podcast|sendungen|gewinner|gewinnerinnen)'
    r'(?:/|\.|$)|(?:datenschutz|privacy|newsletter|impressum|teilnahmebedingungen)', re.I)
CONTEST_WORDS = re.compile(r'gewinnspiel|verlosung|gewinnen|mitmachen|winzone',re.I)
DISCOVERY_SECTION = re.compile(r'(?:^|/)(?:gewinnspiele?|aktionen|mitmachen|winzone|verlosungen)(?:/|$)',re.I)
ARTICLE_FALSE_POSITIVES = re.compile(
    r'gewinneinbruch|gewinnwarnung|gewinnmitnahme|gewinnrueckgang|'
    r'gewinnrückgang|gewinnzahlen|gewinnspielbetrug|gewinnspielauflösung|'
    r'gewinnspiel-tipps|gewinnspiele-finden|gewinnspielkalender', re.I)
DATE_IN_PATH = re.compile(r'(?<!\d)(20\d{2})[/-](0?[1-9]|1[0-2])[/-]([0-2]?\d|3[01])(?!\d)')

def old_article(url):
    path=urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    match=DATE_IN_PATH.search(path)
    if not match: return False
    try: published=dt.date(int(match.group(1)),int(match.group(2)),int(match.group(3)))
    except ValueError: return False
    return (TODAY-published).days>90

def links_on_page(url, allowed_host):
    page=read_official_page(url,allowed_host)
    if not page: return [],''
    _,_,links,final=page
    found=[]; seen=set()
    for href,label in links:
        target=urllib.parse.urljoin(final,href)
        parts=urllib.parse.urlsplit(target)
        if parts.scheme!='https' or (parts.hostname or '').lower()!=allowed_host: continue
        target=urllib.parse.urlunsplit((parts.scheme,parts.netloc,parts.path,'',''))
        if target in seen: continue
        seen.add(target)
        found.append((target,clean_title(label)))
    return found,final

def is_contest_candidate(url,label):
    path=urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    context=path+' '+label
    if NON_CONTEST_PATH.search(path) or BAD.search(context): return False
    if re.search(r'\b(?:ab\s*18|18\s*\+|nur\s+für\s+erwachsene)\b',context,re.I): return False
    if ARTICLE_FALSE_POSITIVES.search(context) or old_article(url): return False
    if not CONTEST_WORDS.search(context) and not re.search(r'\b(?:tickets?|preise?|gewinne?|verlose[n]?|aktion)\b',label,re.I): return False
    # Rubrik ist ein Einstiegspunkt, aber keine einzelne Aktion.
    if DISCOVERY_SECTION.search(path) and re.search(r'/(?:gewinnspiele?|aktionen|mitmachen|winzone|verlosungen)/?$',path,re.I): return False
    if re.search(r'/(?:gewinnspiele?|verlosungen|winzone)/?$',path,re.I): return False
    return True

def candidate_score(url, label):
    """Nur Priorisierung, niemals Beweis für ein aktives Gewinnspiel."""
    path=urllib.parse.unquote(urllib.parse.urlsplit(url).path).lower()
    score=0
    if re.search(r'gewinnspiel|verlosung|winzone',path): score+=4
    if re.search(r'gewinnspiel|verlosung|jetzt mitmachen|jetzt teilnehmen',label,re.I): score+=3
    if re.search(r'gewinnen|mitmachen',path+' '+label,re.I): score+=1
    if re.search(r'/20\d{2}/|\b20\d{2}\b',path): score-=1
    return score

def discover_official(country, homepage):
    """Startseite und explizite Rubriken; Treffer sortiert statt blind gekürzt."""
    host=(urllib.parse.urlsplit(homepage).hostname or '').lower()
    stats={'rubriken':0,'gefiltert':0,'veraltet':0,'gesichtet':0,'relevant':0}
    if not safe_public_host(homepage): return [], stats
    try: root_links,_=links_on_page(homepage,host)
    except (OSError,ValueError,UnicodeError,urllib.error.URLError): root_links=[]
    sections=[urllib.parse.urljoin(homepage,x) for x in OFFICIAL_SECTIONS.get(host,[])]
    for url,label in root_links:
        path=urllib.parse.urlsplit(url).path
        if DISCOVERY_SECTION.search(path) and not NON_CONTEST_PATH.search(path):
            sections.append(url)
    pool=list(root_links)
    for section in list(dict.fromkeys(sections))[:7]:
        if not safe_public_host(section): continue
        try:
            extra,_=links_on_page(section,host)
            pool.extend(extra); stats['rubriken']+=1
        except (OSError,ValueError,UnicodeError,urllib.error.URLError): pass
    candidates=[]; seen=set()
    for url,label in pool:
        if url in seen: continue
        seen.add(url); stats['gesichtet']+=1
        if old_article(url): stats['veraltet']+=1; continue
        if not is_contest_candidate(url,label): stats['gefiltert']+=1; continue
        stats['relevant']+=1
        candidates.append((url,label or urllib.parse.urlsplit(url).path.rstrip('/').rsplit('/',1)[-1]))
    candidates.sort(key=lambda item:candidate_score(*item),reverse=True)
    return candidates[:MAX_CANDIDATES_PER_SOURCE], stats

def normalize_url(url):
    """Canonicalize tracking parameters without changing the destination."""
    parts=urllib.parse.urlsplit(url)
    query=urllib.parse.parse_qsl(parts.query,keep_blank_values=True)
    query=[(k,v) for k,v in query if not (k.lower().startswith('utm_') or k.lower() in ('fbclid','gclid','mc_cid','mc_eid'))]
    return urllib.parse.urlunsplit((parts.scheme.lower(),parts.netloc.lower(),parts.path.rstrip('/') or '/',urllib.parse.urlencode(query),''))


def meaningful_title(title):
    title=clean_title(title)
    return len(title)>=12 and bool(re.search(r'[A-Za-zÄÖÜäöüß]{3,}',title)) and not bool(re.fullmatch(r'[\d\W_]+',title))


def diagnostic_summary(items):
    counts={k:sum(bool(x.get('verification',{}).get(k)) for x in items if x.get('source')!='Google News') for k in ('direct_link','deadline','free','country','entry')}
    return {'criteria_met':counts,'verified':sum(x.get('verified') is True for x in items),'unverified':sum(x.get('verified') is not True for x in items)}


def collect():
    results=[]; errors=[]; seen=set()
    stats={'official_links':0,'official_checked':0,'official_verified':0,'news_hints':0,'official_sources':len(OFFICIAL_START_PAGES),'rubriken':0,'gefiltert':0,'veraltet':0,'gesichtet':0,'relevant':0}
    for country,homepage in OFFICIAL_START_PAGES:
        try:
            links,discovery=discover_official(country,homepage)
            for k,v in discovery.items(): stats[k]+=v
            stats['official_links']+=len(links)
            print(f'[Offizielle Seiten] {homepage}: {len(links)} Kandidaten; Rubriken={discovery["rubriken"]}; gefiltert={discovery["gefiltert"]}; veraltet={discovery["veraltet"]}; relevant={discovery["relevant"]}',flush=True)
            source_checked=0
            for url,label in links:
                if stats['official_checked']>=MAX_CHECKED_TOTAL or source_checked>=MAX_CHECKED_PER_SOURCE: break
                if url in seen: continue
                if not meaningful_title(label): continue
                seen.add(url)
                print(f'[Kandidat {stats["official_checked"]+1}] {country} | {url}',flush=True)
                verified,deadline,checks=check_page(url,country,diagnostic=True)
                stats['official_checked']+=1
                source_checked+=1
                if verified: stats['official_verified']+=1
                reason=reason_for(checks,'Veranstalterseite')
                print(f'[Ergebnis] {reason}',flush=True)
                results.append({'title':label[:180] or 'Gewinnspiel beim Veranstalter',
                    'url':url,'country':country,'published':TODAY.isoformat(),
                    'deadline':deadline,'category':category_for(label),
                    'source':urllib.parse.urlsplit(homepage).hostname,
                    'description':('Automatische Vorprüfung erfolgreich; Bedingungen selbst prüfen.' if verified else 'Gefundene Veranstalteraktion: Teilnahmebedingungen und Aktualität selbst prüfen.'),
                    'verified':verified,'verification':checks,'verification_reason':reason,
                     'freeEntry':bool(verified and checks['free']),
                     'eligibleCountriesVerified':bool(verified and checks['country']),
                     'deadlineVerified':bool(verified and checks['deadline']),
                     'directEntryVerified':bool(verified and checks['direct_link'] and checks['entry'])})
        except Exception as exc:
            errors.append('Offizielle Seite '+homepage+': '+str(exc)[:120])
            print(f'[Offizielle Seiten] {homepage}: nicht erreichbar/auswertbar',flush=True)
    for country,query in []:  # News articles are not direct entry pages.
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
                    'verification_reason':'Pressehinweis: keine bestätigte Veranstalterseite',
                     'freeEntry':False,'eligibleCountriesVerified':False,
                     'deadlineVerified':False,'directEntryVerified':False})
        except Exception as exc:
            errors.append('Google News '+country+': '+str(exc)[:120])
    # Direct search is a separate discovery route. Search results never count as verified.
    stats['direct_search_hints']=0
    for country, query in DIRECT_QUERIES:
        try:
            for entry in fetch_direct_search(country,query)[:12]:
                title=clean_title(entry.findtext('title') or '')
                url=(entry.findtext('link') or '').strip()
                if not meaningful_title(title) or not url.startswith('https://'): continue
                if BAD.search(title) or ENDED.search(title) or LOW_QUALITY.search(title): continue
                host=(urllib.parse.urlsplit(url).hostname or '').lower()
                if any(x in host for x in AGGREGATOR_HOST_PARTS): continue
                key=normalize_url(url)
                if key in seen: continue
                seen.add(key)
                stats['direct_search_hints']+=1
                results.append({'title':title[:180], 'url':url,'country':country,
                    'published':TODAY.isoformat(),'deadline':deadline_from_title(title),
                    'category':category_for(title),'source':host,
                    'description':'Direkter Suchtreffer – Teilnahmebedingungen manuell prüfen.',
                    'verified':False,'verification':{'direct_link':False,'deadline':False,'free':False,'country':False,'entry':False},
                    'verification_reason':'Suchtreffer nicht auf der Veranstalterseite geprüft',
                    'freeEntry':False,'eligibleCountriesVerified':False,
                    'deadlineVerified':False,'directEntryVerified':False})
        except Exception as exc:
            errors.append('Direktsuche '+country+': '+str(exc)[:120])
    print('[Quellen] Direkte Veranstalter-Rubriken AT/DE; Bing und Google-News-Eintraege deaktiviert',flush=True)
    print('[Diagnose] '+', '.join(f'{k}={v}' for k,v in stats.items()),flush=True)
    # Einfache Qualitätskontrolle vor Veröffentlichung: eindeutige URLs, sinnvolle Titel,
    # keine bereits abgelaufenen Fristen und keine offensichtlichen Glücksspielangebote.
    cleaned=[]; urls=set()
    for item in results:
        title=item['title'].strip(); url=item['url']
        if not meaningful_title(title): continue
        normalized=normalize_url(url)
        if normalized in urls: continue
        if BAD.search(title) or ENDED.search(title): continue
        if item.get('deadline') and item['deadline']<TODAY.isoformat(): continue
        urls.add(normalized);cleaned.append(item)
    results=cleaned
    for item in results:
        item['review_status'] = 'bestätigt' if item['verified'] else 'noch_pruefen'
    results.sort(key=lambda x:(bool(x['verified']),bool(x.get('deadline')),x['published']),reverse=True)
    return results[:MAX_CHECKED_TOTAL],errors

def main():
    results,errors=collect()
    if not results:
        print('Keine neuen Treffer; veröffentliche leeren Feed statt veraltete Aktionen zu behalten.',flush=True)
    output={'updated':NOW.strftime('%Y-%m-%d %H:%M UTC'),
        'updated_at':NOW.strftime('%Y-%m-%d %H:%M UTC'),'items':results,'errors':errors,'diagnostics':diagnostic_summary(results),'schema_version':2}
    Path(__file__).with_name('feed.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{len(results)} Hinweise, davon {sum(bool(x["verified"]) for x in results)} streng geprüft; {len(errors)} Quellenfehler')

if __name__=='__main__': main()
