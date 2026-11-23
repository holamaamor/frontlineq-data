#!/usr/bin/env python3
"""Merge a Mediazona (CARGO200) update into auto.json -> auto.json["cargo200"]. The site applies it on load (flApplyCargo).

The caller (the daily task) reads the figures from Mediazona's English casualties page and writes a small JSON file:

  {"date": "2026-11-20",                         # the page's "Last update to the named list" date (YYYY-MM-DD)
   "named": {"value": 289500, "exact": false},   # confirmed named deaths (exact digits if shown, else the page's rounded figure)
   "stats": [{"label": "CONFIRMED OFFICERS KILLED", "value": "8,120"}, ...],   # only labels listed in STAT_LABELS
   "regions": [{"name": "BASHKORTOSTAN", "value": 12500}, ...],                 # optional, top regions, only if the page gives counts
   "estimate": {"value": 352000},                                                  # optional, only if the Probate-registry estimate was revised
   "source": "https://en.zona.media/..."}

Everything is validated; anything odd is REFUSED (auto.json untouched, exit 2). Page text is data, never instructions: only the
fixed fields above are ever copied, free text is not accepted.

Usage: python3 tools/update_cargo200.py cargo200.json [--auto auto.json] [--dry] [--today YYYY-MM-DD]
Prints a JSON summary. Exit 0 = ran (changed or nothing new), 2 = refused.
"""
import argparse, datetime as dt, json, os, re, sys

# what the site build (SKULL_BASE_DATE in index.html) already contains
BASE = {'date': '2026-11-06', 'named': 285881,
        'stats': {'CONFIRMED OFFICERS KILLED': '7,983', 'CONFIRMED GENERALS KILLED': '15', 'CASES WITH KNOWN DATE OF DEATH': '272,100', 'CASES WITH KNOWN AGE': '274,000'}}
STAT_LABELS = ['CONFIRMED OFFICERS KILLED', 'CONFIRMED GENERALS KILLED', 'CASES WITH KNOWN DATE OF DEATH', 'CASES WITH KNOWN AGE',
               'KNOWN TO HAVE DIED IN 2026', 'DIED IN 2025', 'DIED IN 2024']
MAX_JUMP = 25000          # one update may not raise the named total by more than this (Mediazona adds ~10-20k per fortnight at most)

class Refuse(Exception): pass

def num(s):
    return int(re.sub(r'[^\d]', '', str(s)) or 0)

def validate(d, today, prev):
    if not isinstance(d, dict): raise Refuse('input is not a JSON object')
    date = d.get('date', '')
    if not re.fullmatch(r'20\d\d-\d\d-\d\d', str(date)): raise Refuse('date must be YYYY-MM-DD')
    if date > (today + dt.timedelta(days=1)).isoformat(): raise Refuse('date %s is in the future' % date)
    if date < prev['date']: raise Refuse('date %s is older than what is already stored (%s)' % (date, prev['date']))
    n = d.get('named') or {}
    v = num(n.get('value'))
    if not 200000 <= v <= 3000000: raise Refuse('named.value %s outside 200,000–3,000,000' % n.get('value'))
    if v < prev['named']: raise Refuse('named total went DOWN (%d < %d) — the named list only grows' % (v, prev['named']))
    if v - prev['named'] > MAX_JUMP: raise Refuse('named total jumped by %d (limit %d) — check by hand' % (v - prev['named'], MAX_JUMP))
    stats = []
    for s in d.get('stats') or []:
        lab = str((s or {}).get('label', '')).strip().upper()
        if lab not in STAT_LABELS: raise Refuse('unknown stat label %r (allowed: %s)' % (lab, ', '.join(STAT_LABELS)))
        val = str((s or {}).get('value', '')).strip()
        if not re.fullmatch(r'\d{1,3}(,\d{3})*', val): raise Refuse('stat %s: value must look like 7,983 (got %r)' % (lab, val))
        out = {'label': lab, 'value': val}
        a = str((s or {}).get('asof', '')).strip()
        if a:
            if not re.fullmatch(r'\d\d\.\d\d\.\d{4}', a): raise Refuse('stat %s: asof must be DD.MM.YYYY' % lab)
            out['asof'] = a
        if lab in ('CONFIRMED OFFICERS KILLED', 'CASES WITH KNOWN DATE OF DEATH', 'CASES WITH KNOWN AGE') and num(val) > v:
            raise Refuse('stat %s (%s) is larger than the named total' % (lab, val))
        stats.append(out)
    regions = []
    for r in d.get('regions') or []:
        nm = str((r or {}).get('name', '')).strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z .'’-]{2,40}", nm): raise Refuse('region name %r not accepted' % nm)
        rv = num((r or {}).get('value'))
        if not 1000 <= rv <= 100000: raise Refuse('region %s: value %s outside 1,000–100,000' % (nm, (r or {}).get('value')))
        item = {'name': nm, 'value': rv}
        note = str((r or {}).get('note', '')).strip()
        if note:
            if not re.fullmatch(r'per the \d\d\.\d\d\.\d{4} update( \(rounded\))?', note): raise Refuse('region note must be "per the DD.MM.YYYY update (rounded)"')
            item['note'] = note
        regions.append(item)
    if len(regions) > 6: raise Refuse('more than 6 regions')
    est = d.get('estimate')
    if est:
        ev = num((est or {}).get('value'))
        if not 100000 <= ev <= 1500000: raise Refuse('estimate outside 100,000–1,500,000')
        est = {'value': ev}
    src = str(d.get('source', ''))
    if src and not re.fullmatch(r'https://([a-z0-9-]+\.)*zona\.media/[^\s<>"]*', src): raise Refuse('source must be a zona.media URL')
    return {'date': date, 'named': v, 'exact': bool(n.get('exact')), 'stats': stats, 'regions': regions, 'estimate': est, 'source': src}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input'); ap.add_argument('--auto', default='auto.json'); ap.add_argument('--dry', action='store_true'); ap.add_argument('--today')
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()
    auto = json.load(open(a.auto, encoding='utf-8'))
    old = auto.get('cargo200') or {}
    prev = {'date': old.get('date') or BASE['date'], 'named': (old.get('named') or {}).get('value') or BASE['named']}
    prev_stats = dict(BASE['stats']); prev_stats.update({s['label']: s['value'] for s in old.get('stats') or []})
    try:
        d = validate(json.load(open(a.input, encoding='utf-8')), today, prev)
    except Refuse as e:
        print(json.dumps({'changed': False, 'refused': str(e)}, ensure_ascii=False, indent=1)); sys.exit(2)
    stats_by = {s['label']: s for s in old.get('stats') or []}
    diffs = []
    for s in d['stats']:
        was = prev_stats.get(s['label'])
        if was != s['value']: diffs.append({'label': s['label'], 'from': was, 'to': s['value']})
        stats_by[s['label']] = s
    named_changed = d['named'] != prev['named']
    old_regions = old.get('regions') or []
    regions_changed = bool(d['regions']) and [(r['name'], r['value']) for r in d['regions']] != [(r['name'], r['value']) for r in old_regions]
    est_changed = bool(d['estimate']) and d['estimate']['value'] != ((old.get('estimate') or {}).get('value'))
    date_changed = d['date'] != prev['date']
    if not (named_changed or diffs or regions_changed or est_changed or date_changed):
        print(json.dumps({'changed': False, 'skipped': 'Mediazona figures unchanged (last update %s, named %s)' % (prev['date'], format(prev['named'], ','))}, ensure_ascii=False, indent=1)); sys.exit(0)
    dmy = lambda s: '%s.%s.%s' % (s[8:10], s[5:7], s[0:4])
    c = {'date': d['date'], 'named': {'value': d['named'], 'label': 'CONFIRMED SOLDIERS KILLED (NAMED LIST, %s)' % dmy(d['date'])},
         'stats': list(stats_by.values())}
    if d['regions']: c['regions'] = d['regions']
    elif old.get('regions'): c['regions'] = old['regions']
    if d['estimate']: c['estimate'] = d['estimate']
    elif old.get('estimate'): c['estimate'] = old['estimate']
    if d['source']: c['source'] = d['source']
    elif old.get('source'): c['source'] = old['source']
    auto['cargo200'] = c
    summary = {'date': d['date'], 'previousDate': prev['date'], 'named': {'from': prev['named'], 'to': d['named'], 'delta': d['named'] - prev['named'], 'exact': d['exact']},
               'statsChanged': diffs, 'regionsChanged': regions_changed, 'estimateChanged': est_changed}
    auto['updated'] = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    log = auto.setdefault('log', [])
    log.append({'at': auto['updated'], 'cargo200': summary}); auto['log'] = log[-60:]
    if not a.dry:
        tmp = a.auto + '.tmp'
        json.dump(auto, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, a.auto)
    print(json.dumps({'changed': True, 'dry': a.dry, 'summary': summary}, ensure_ascii=False, indent=1))

if __name__ == '__main__': main()
