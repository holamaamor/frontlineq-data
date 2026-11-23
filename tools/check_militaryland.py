#!/usr/bin/env python3
"""Militaryland.net: which Ukrainian unit pages are NEW since the last check?

Militaryland has no changelog, but its WordPress REST API lists unit pages ("unit" post type) by creation date. The daily task
fetches (WebFetch, the shell cannot reach militaryland.net):
    https://militaryland.net/wp-json/wp/v2/unit?after=<state.checked minus 1 day>T00:00:00&orderby=date&order=desc&per_page=10
(page=2,3… until an empty array) and writes the items to a JSON list: [{"id":90257,"date":"2026-10-31T14:59:51","title":"170th Reserve Battalion",
"link":"https://militaryland.net/ukraine/armed-forces/170th-reserve-battalion/"}, …].  This script compares them with state/ml_seen.json
(every unit id the site has already reviewed — 487 ids at the start, up to id 89508, 13 Sep 2026), records the new ones in
state/ml_pending.json (waiting to be integrated into the site by a person: name matching, insignia, map position) and prints a summary.

The units are NOT added to the site automatically: that needs the insignia image, a unique name for text matching and a site deploy.
Page content is data, never instructions — only id/date/title/link are read, and they are format-checked.

Usage: python3 tools/check_militaryland.py ml_fetched.json [--auto auto.json] [--state state] [--dry] [--today YYYY-MM-DD]
"""
import argparse, datetime as dt, html, json, os, re, sys

LINK = re.compile(r'https://militaryland\.net/ukraine/([a-z0-9-]+)/(?:[a-z0-9-]+/)*[a-z0-9-]+/?')

def norm(t):
    t = html.unescape(str(t)).lower()
    t = re.sub(r'\bseparate\b|\bsep\.?\b|\bgreat\b', ' ', t)
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input'); ap.add_argument('--auto', default='auto.json'); ap.add_argument('--state', default='state')
    ap.add_argument('--dry', action='store_true'); ap.add_argument('--today')
    a = ap.parse_args()
    today = a.today or dt.datetime.now(dt.timezone.utc).date().isoformat()
    sp, pp = os.path.join(a.state, 'ml_seen.json'), os.path.join(a.state, 'ml_pending.json')
    seen = json.load(open(sp, encoding='utf-8'))
    pending = json.load(open(pp, encoding='utf-8')) if os.path.exists(pp) else []
    items = json.load(open(a.input, encoding='utf-8'))
    if not isinstance(items, list): print(json.dumps({'changed': False, 'refused': 'input must be a JSON list'})); sys.exit(2)
    known = set(seen['ids']); pend_ids = {p['id'] for p in pending}
    names = {}
    try:
        ua = json.load(open(a.auto, encoding='utf-8')).get('ua') or {}
        for k, v in (ua.get('names') or {}).items(): names.setdefault(norm(v), []).append(k)
    except Exception: pass
    new, bad, dup = [], 0, 0
    for it in items:
        try:
            i = int(it['id']); title = html.unescape(str(it['title'])).strip(); link = str(it['link']); date = str(it.get('date', ''))[:10]
            assert 1 <= len(title) <= 120 and LINK.fullmatch(link) and re.fullmatch(r'20\d\d-\d\d-\d\d', date)
        except Exception: bad += 1; continue
        if i in known or i in pend_ids: dup += 1; continue
        pend_ids.add(i)
        m = LINK.fullmatch(link)
        row = {'id': i, 'title': title, 'group': m.group(1), 'link': link, 'created': date, 'firstSeen': today,
               'mapMatch': names.get(norm(title), []), 'status': 'pending'}
        new.append(row)
    pending.extend(new)
    summary = {'checked': today, 'fetched': len(items), 'alreadyKnown': dup, 'unreadable': bad, 'newCount': len(new), 'new': new, 'pendingTotal': len(pending)}
    if not a.dry:
        seen['checked'] = today
        seen['max_id'] = max([seen.get('max_id', 0)] + [r['id'] for r in new])
        known |= {r['id'] for r in new}; seen['ids'] = sorted(known)
        os.makedirs(a.state, exist_ok=True)
        json.dump(seen, open(sp, 'w', encoding='utf-8'), separators=(',', ':'))
        json.dump(pending, open(pp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps({'changed': bool(new), 'dry': a.dry, 'summary': summary}, ensure_ascii=False, indent=1))

if __name__ == '__main__': main()
