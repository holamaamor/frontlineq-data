#!/usr/bin/env python3
"""Ambargo media fetcher (runs in a GitHub Actions job — the cloud sandbox cannot reach t.me / CDNs).

Input tools/amb_jobs.json:
  { "get":   ["https://t.me/channel/123", ...],                      # download the photos / short videos of these public posts
    "probe": [ {"id":"r12","ch":"exilenova_plus","q":"Пенза"},        # list public posts of a channel matching a search (metadata only)
              {"id":"r3","ch":"soprotivleniye_lsr","from":349,"to":355} ] }   # list posts by id range (metadata only)
Output: amb/media/<channel>_<id>_<n>.jpg|mp4 (photos <=1280 px JPEG; videos <=~8 MB), amb/result.json (post text, date, media files)
Only public posts shown by Telegram's own web preview are read. Polite: honest User-Agent, ~1 request/second.
"""
import html, io, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from PIL import Image

UA = 'FrontlinesAmbargoMedia/1.0 (personal non-commercial OSINT map; polite, ~1 req/s; contact via github.com/holamaamor)'
DELAY = 1.0
OUT = 'amb'
MEDIA = os.path.join(OUT, 'media')
MAXPX = 1280
VID_MAX_DL = 60 * 1024 * 1024
VID_TARGET = 8 * 1024 * 1024
os.makedirs(MEDIA, exist_ok=True)
fails = {'n': 0}

def log(*a): print(' '.join(str(x) for x in a), flush=True)

def http(url, binary=False, maxbytes=None, tries=3):
    last = ''
    for t in range(1, tries + 1):
        time.sleep(DELAY)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*', 'Accept-Language': 'en,ru;q=0.8'})
            with urllib.request.urlopen(req, timeout=60) as r:
                if maxbytes:
                    cl = r.headers.get('Content-Length')
                    if cl and int(cl) > maxbytes: return None
                data = r.read(maxbytes + 1 if maxbytes else -1)
                if maxbytes and len(data) > maxbytes: return None
            return data if binary else data.decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            last = 'HTTP %s' % e.code
            if e.code == 404: return None
            time.sleep(3 * t)
        except Exception as e:
            last = str(e)[:80]; time.sleep(2 * t)
    log('  x giving up:', last, url); fails['n'] += 1
    return None

def strip(s):
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'[ \t]+', ' ', html.unescape(s)).strip()

def parse_blocks(page):
    """Split a Telegram widget page into messages."""
    out = []
    parts = re.split(r'(?=<div class="tgme_widget_message [^"]*"[^>]*data-post=")', page)
    for b in parts:
        m = re.search(r'data-post="([^"]+)"', b)
        if not m or '/' not in m.group(1): continue
        post = m.group(1)
        d = re.search(r'<time[^>]*datetime="([^"]+)"', b)
        txt = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
        photos = [html.unescape(x) for x in re.findall(r'tgme_widget_message_photo_wrap[^>]*background-image:url\(\'([^\']+)\'\)', b)]
        vids = [html.unescape(x) for x in re.findall(r'<video[^>]*\ssrc="([^"]+)"', b)]
        thumbs = [html.unescape(x) for x in re.findall(r'tgme_widget_message_(?:video|roundvideo)_thumb[^>]*background-image:url\(\'([^\']+)\'\)', b)]
        prev = [html.unescape(x) for x in re.findall(r'link_preview_(?:image|right_image)[^>]*background-image:url\(\'([^\']+)\'\)', b)]
        out.append({'post': post, 'date': d.group(1) if d else '', 'text': strip(txt.group(1)) if txt else '',
                    'photos': photos, 'videos': vids, 'thumbs': thumbs, 'preview': prev,
                    'has_video': ('message_video' in b or 'roundvideo' in b)})
    return out

def embed(ch, pid):
    page = http('https://t.me/%s/%s?embed=1&mode=tme' % (ch, pid))
    if not page: return None
    bl = parse_blocks(page)
    if bl:
        for x in bl:
            if x['post'] == '%s/%s' % (ch, pid): return x
        return bl[0]
    return None

def save_photo(url, base):
    data = http(url, True, 25 * 1024 * 1024)
    if not data: return None
    try:
        im = Image.open(io.BytesIO(data))
        if im.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', im.size, (255, 255, 255)); im = im.convert('RGBA'); bg.paste(im, mask=im.split()[-1]); im = bg
        else: im = im.convert('RGB')
        w, h = im.size
        im.thumbnail((MAXPX, MAXPX), Image.LANCZOS)
        dst = os.path.join(MEDIA, base + '.jpg')
        im.save(dst, 'JPEG', quality=80, optimize=True, progressive=True)
        return {'file': dst.replace('\\', '/'), 'kind': 'image', 'orig': [w, h], 'bytes': os.path.getsize(dst)}
    except Exception as e:
        log('  x image decode failed', str(e)[:80], url); return None

def save_video(url, base):
    data = http(url, True, VID_MAX_DL)
    if not data: return None
    raw = os.path.join(MEDIA, base + '.raw.mp4'); dst = os.path.join(MEDIA, base + '.mp4')
    open(raw, 'wb').write(data)
    size = len(data)
    if size <= VID_TARGET:
        os.replace(raw, dst)
    else:
        cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-i', raw, '-t', '75', '-vf', "scale='min(854,iw)':-2", '-c:v', 'libx264', '-crf', '31',
               '-preset', 'veryfast', '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', dst]
        try: subprocess.run(cmd, check=True, timeout=600)
        except Exception as e:
            log('  x ffmpeg failed', str(e)[:80]); os.remove(raw); return None
        os.remove(raw)
        if os.path.getsize(dst) > 12 * 1024 * 1024:
            log('  x video too big after compression', os.path.getsize(dst)); os.remove(dst); return None
    return {'file': dst.replace('\\', '/'), 'kind': 'video', 'orig_bytes': size, 'bytes': os.path.getsize(dst)}

def do_get(url):
    m = re.match(r'https?://(?:t|telegram)\.me/([^/?#]+)/(\d+)', url)
    res = {'url': url, 'ok': False}
    if not m: res['err'] = 'not a telegram post url'; return res
    ch, pid = m.group(1), m.group(2)
    x = embed(ch, pid)
    if not x: res['err'] = 'embed page not readable'; return res
    res.update({'date': x['date'], 'text': x['text'][:1200], 'ok': True, 'files': [], 'poster': None, 'big_video': False})
    for i, u in enumerate(x['photos'][:6]):
        r = save_photo(u, '%s_%s_%d' % (ch, pid, i + 1))
        if r: res['files'].append(r)
    for i, u in enumerate(x['videos'][:2]):
        r = save_video(u, '%s_%s_v%d' % (ch, pid, i + 1))
        if r: res['files'].append(r)
    if x['has_video'] and not any(f['kind'] == 'video' for f in res['files']):
        res['big_video'] = True            # Telegram does not give the file out: keep a poster picture
        th = (x['thumbs'] or x['preview'] or [None])[0]
        if th:
            r = save_photo(th, '%s_%s_poster' % (ch, pid))
            if r: res['poster'] = r['file']
    if not res['files'] and not res['poster'] and x['preview']:
        r = save_photo(x['preview'][0], '%s_%s_1' % (ch, pid))
        if r: res['files'].append(r)
    return res

def do_probe(job):
    ch = job['ch']; out = {'id': job['id'], 'ch': ch, 'posts': []}
    if 'q' in job:
        page = http('https://t.me/s/%s?q=%s' % (ch, urllib.parse.quote(job['q'])))
        if page:
            for x in parse_blocks(page): out['posts'].append(x)
    else:
        for pid in range(job['from'], job['to'] + 1):
            x = embed(ch, pid)
            if x: out['posts'].append(x)
    for x in out['posts']:
        x['text'] = x['text'][:700]
        x['n_photos'] = len(x.pop('photos')); x['n_videos'] = len(x.pop('videos')); x.pop('thumbs'); x.pop('preview')
    return out


# ---------------------------------------------------------------- X / Twitter (public posts, via FxTwitter + the public syndication timeline)
def fx_status(sid):
    txt = http('https://api.fxtwitter.com/status/%s' % sid)
    if not txt: return None
    try: return json.loads(txt).get('tweet')
    except Exception: return None

def tweet_media(t):
    out = {'videos': [], 'photos': []}
    for m in ((t.get('media') or {}).get('all') or []):
        if m.get('type') in ('video', 'gif') and m.get('url'): out['videos'].append(m['url'])
        elif m.get('type') == 'photo' and m.get('url'): out['photos'].append(m['url'])
    return out

def do_xget(sid):
    t = fx_status(sid)
    res = {'id': sid, 'ok': bool(t), 'files': []}
    if not t: return res
    res.update({'handle': (t.get('author') or {}).get('screen_name'), 'date': t.get('created_at'), 'text': (t.get('text') or '')[:800]})
    mm = tweet_media(t)
    for i, u in enumerate(mm['videos'][:3]):
        r = save_video(u, 'x_%s_v%d' % (sid, i + 1))
        if r: res['files'].append(r)
    for i, u in enumerate(mm['photos'][:6]):
        r = save_photo(u, 'x_%s_%d' % (sid, i + 1))
        if r: res['files'].append(r)
    return res

def do_xtimeline(handle):
    out = {'handle': handle, 'tweets': []}
    page = http('https://syndication.twitter.com/srv/timeline-profile/screen-name/%s?showReplies=false' % handle)
    if not page: out['err'] = 'no page'; return out
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S)
    if not m: out['err'] = 'no data'; out['head'] = page[:300]; return out
    try:
        entries = json.loads(m.group(1))['props']['pageProps']['timeline']['entries']
    except Exception as e:
        out['err'] = 'parse ' + str(e)[:80]; return out
    for e in entries:
        t = (e.get('content') or {}).get('tweet')
        if not t: continue
        vids = []
        for med in ((t.get('extended_entities') or {}).get('media') or []):
            vi = med.get('video_info') or {}
            best = sorted([v for v in vi.get('variants', []) if v.get('content_type') == 'video/mp4'], key=lambda v: v.get('bitrate', 0))
            if best: vids.append(best[-1]['url'])
        out['tweets'].append({'id': t.get('id_str'), 'date': t.get('created_at'), 'text': (t.get('full_text') or t.get('text') or '')[:300], 'videos': len(vids)})
    return out

def main():
    jobs = json.load(open(sys.argv[1], encoding='utf-8'))
    res = {'get': [], 'probe': []}
    for u in jobs.get('get', []):
        log('GET', u); res['get'].append(do_get(u))
        if fails['n'] >= 12: log('too many failures, stopping'); break
    for j in jobs.get('probe', []):
        log('PROBE', j.get('id'), j.get('ch'), j.get('q') or ('%s-%s' % (j.get('from'), j.get('to')))); res['probe'].append(do_probe(j))
        if fails['n'] >= 12: log('too many failures, stopping'); break
    for sid in jobs.get('xget', []):
        log('XGET', sid); res.setdefault('xget', []).append(do_xget(sid))
    for sid in jobs.get('xtimeline_of', []):
        t = fx_status(sid); h = ((t or {}).get('author') or {}).get('screen_name')
        log('XTIMELINE of', sid, '->', h)
        if h: res.setdefault('xtimeline', []).append(do_xtimeline(h))
    for h in jobs.get('xtimeline', []):
        log('XTIMELINE', h); res.setdefault('xtimeline', []).append(do_xtimeline(h))
    json.dump(res, open(os.path.join(OUT, 'result.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log('done: %d posts fetched, %d probes' % (len(res['get']), len(res['probe'])))

if __name__ == '__main__': main()
