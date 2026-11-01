#!/usr/bin/env python3
"""Öffentliche Google-News-RSS-Hinweise, keine automatische Teilnahme."""
import datetime, email.utils, json, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
NOW=datetime.datetime.now(datetime.timezone.utc)
QUERIES=[('Österreich','kostenloses Gewinnspiel gewinnen Österreich -lotto -casino -wetten -lotterie'),('Deutschland','kostenloses Gewinnspiel gewinnen Deutschland -lotto -casino -wetten -lotterie')]
seen=set(); results=[]
for country,q in QUERIES:
    url='https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':q+' when:7d','hl':'de','gl':'AT' if country=='Österreich' else 'DE','ceid':('AT' if country=='Österreich' else 'DE')+':de'})
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'WinPilotFamily/2.0 (RSS reader)'})
        with urllib.request.urlopen(req,timeout=25) as response: body=response.read(2_000_000)
        root=ET.fromstring(body)
        for item in root.findall('.//channel/item'):
            title=' '.join((item.findtext('title') or '').split())
            link=(item.findtext('link') or '').strip()
            if not title or not link.startswith('https://'):continue
            if re.search(r'lotto|lotterie|casino|sportwetten|glücksspiel|jackpot|poker|wetten',title,re.I):continue
            key=title.casefold()
            if key in seen:continue
            seen.add(key)
            date=item.findtext('pubDate') or ''
            try: published=email.utils.parsedate_to_datetime(date).date().isoformat()
            except Exception: published=''
            results.append({'title':title[:180],'url':link,'country':country,'published':published})
    except Exception as ex: print('RSS Fehler',country,str(ex))
results.sort(key=lambda x:x['published'],reverse=True)
out={'updated':NOW.strftime('%Y-%m-%d %H:%M UTC'),'items':results[:100]}
Path(__file__).with_name('feed.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(len(results),'Hinweise')
