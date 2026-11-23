#!/usr/bin/env python3
"""Militaryland.net insignia scan (runs in a GitHub Actions job — the cloud sandbox cannot reach militaryland.net).

Input  tools/ml_targets.json : {"labels":[{"label":"Kraken","queries":["Kraken"]}, ...], "ids":[85449, ...]}
  labels — unit names used on the site's event cards that have no insignia yet: each query is searched in Militaryland's WordPress API
           (/wp-json/wp/v2/unit?search=...); the best few candidates get their insignia downloaded for a human to compare.
  ids    — Militaryland unit ids the site already knows but has no picture for: the picture is downloaded directly.
Output scan/result.json, scan/img/<id>.png (<=128 px, 256 colours), scan/credits.csv
Polite: honest User-Agent, ~1 request/second, stops when the site answers with a bot check or repeated errors.
Content licence: MilitaryLand.net CC BY-SA 4.0 (attribution is kept on the site's unit window).
"""
import csv, html, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from PIL import Image

BASE = 'https://militaryland.net'
UA = 'FrontlinesInsigniaScan/1.0 (personal non-commercial OSINT map; polite, ~1 req/s; contact via github.com/holamaamor)'
DELAY = 0.9
MAXPX = 128
LOG = []
STOP = {'why': ''}

def log(*a):
    s = ' '.join(str(x) for x in a); LOG.append(s); print(s, flush=True)

def get(url, binary=False, tries=3):
    if STOP['why']: return None
    last = ''
    for t in range(1, tries + 1):
        time.sleep(DELAY)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
            if not binary:
                txt = data.decode('utf-8', 'replace')
                if txt.lstrip().startswith('<') or 'One moment, please' in txt[:400]:
                    last = 'bot check / html instead of json'
                    log('  !', last, url); time.sleep(4 * t); continue
                return json.loads(txt)
            return data
        except urllib.error.HTTPError as e:
            last = 'HTTP %s' % e.code
            if e.code in (401, 403, 429): log('  !', last, url); time.sleep(5 * t)
            elif e.code == 404: return None
        except Exception as e:
            last = str(e)[:80]; time.sleep(2 * t)
    log('  x giving up:', last, url)
    STOP['fails'] = STOP.get('fails', 0) + 1
    if STOP['fails'] >= 8: STOP['why'] = 'too many failures (' + last + ')'
    return None

def png_from(url, dst):
    data = get(url, True)
    if not data: return 0
    try:
        im = Image.open(io.BytesIO(data)).convert('RGBA')
        im.thumbnail((MAXPX, MAXPX), Image.LANCZOS)
        # 256 colours keep the file small (same as the insignia already on the site)
        q = im.quantize(colors=255, method=Image.FASTOCTREE, dither=Image.NONE) if im.getchannel('A').getextrema()[0] < 255 else im.convert('RGB').quantize(colors=256, method=Image.MEDIANCUT)
        if im.getchannel('A').getextrema()[0] < 255:
            q = im.quantize(colors=255, method=Image.FASTOCTREE, dither=Image.NONE)
        q.save(dst, optimize=True)
        return os.path.getsize(dst)
    except Exception as e:
        log('  x image', url, str(e)[:80]); return 0

def info(uid):
    j = get('%s/wp-json/orbat/v1/unit/%s' % (BASE, uid))
    return j if isinstance(j, dict) else None

def main():
    tgt = json.load(open(sys.argv[1], encoding='utf-8')); out = sys.argv[2]
    os.makedirs(os.path.join(out, 'img'), exist_ok=True)
    credits, res = {}, {'labels': [], 'ids': [], 'stopped': ''}

    def fetch_png(uid, title='', link=''):
        dst = os.path.join(out, 'img', '%s.png' % uid)
        if os.path.exists(dst): return {'png': '%s.png' % uid, 'bytes': os.path.getsize(dst)}
        j = info(uid)
        if not j or not j.get('insignia_url'): return {'png': '', 'note': 'no insignia_url'}
        n = png_from(j['insignia_url'], dst)
        if not n: return {'png': '', 'note': 'download failed', 'insignia_url': j['insignia_url']}
        credits[uid] = [uid, html.unescape(j.get('title') or title), j.get('permalink') or link, j['insignia_url'], 'CC BY-SA 4.0 (MilitaryLand.net)']
        return {'png': '%s.png' % uid, 'bytes': n, 'insignia_url': j['insignia_url'], 'permalink': j.get('permalink', ''), 'mltitle': html.unescape(j.get('title') or '')}

    # 1) labels -> candidates
    for t in tgt.get('labels', []):
        if STOP['why']: break
        seen, cands = set(), []
        for q in t['queries']:
            items = get('%s/wp-json/wp/v2/unit?search=%s&per_page=6' % (BASE, urllib.parse.quote(q)))
            for it in (items or []):
                try: uid = int(it['id'])
                except Exception: continue
                if uid in seen: continue
                seen.add(uid)
                m = re.match(r'https://militaryland\.net/ukraine/([a-z0-9-]+)/', str(it.get('link', '')))
                cands.append({'id': uid, 'title': html.unescape(str((it.get('title') or {}).get('rendered', ''))), 'link': it.get('link', ''), 'group': m.group(1) if m else '', 'query': q})
        cands = cands[:7]
        for c in cands[:4]:
            c.update(fetch_png(c['id'], c['title'], c['link']))
        log('label %-48s -> %s' % (t['label'][:48], '; '.join('%s %s%s' % (c['id'], c['title'][:30], '' if c.get('png') else ' (no img)') for c in cands[:4])))
        res['labels'].append({'label': t['label'], 'queries': t['queries'], 'candidates': cands})

    # 2) ids -> picture
    for uid in tgt.get('ids', []):
        if STOP['why']: break
        r = fetch_png(uid)
        r['id'] = uid
        res['ids'].append(r)
        log('id %s -> %s' % (uid, r.get('mltitle') or r.get('note') or ''))

    res['stopped'] = STOP['why']
    res['log_tail'] = LOG[-40:]
    json.dump(res, open(os.path.join(out, 'result.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    with open(os.path.join(out, 'credits.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['ml_id', 'title', 'source_page', 'image_url', 'license'])
        for k in sorted(credits, key=int): w.writerow(credits[k])
    open(os.path.join(out, 'log.txt'), 'w', encoding='utf-8').write('\n'.join(LOG) + '\n')
    log('done; stopped =', STOP['why'] or 'no')

if __name__ == '__main__':
    main()
