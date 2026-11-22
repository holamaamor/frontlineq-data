#!/usr/bin/env python3
"""Daily refresh of auto.json — the small data file the Frontlines site reads at runtime.

  DeepState zones   cyterat/deepstate-map-data (daily GeoJSON of the occupied area, from DeepStateMap.live)
  UA unit positions owlmaps/map-data (Ukraine Control Map daily unit positions + names)
  Losses counters   optional: --losses FILE.json (figures already cross-checked by the caller)

Only auto.json changes, so the site (Netlify) is never re-published and no Netlify credits are used.
Usage:  python3 tools/update_auto.py [--auto auto.json] [--skip-deepstate] [--skip-units] [--losses FILE] [--dry]
Needs:  python3 + shapely + pyproj (pip install shapely pyproj) + git.
Exit code 0 = ran (check the printed summary); 2 = a sanity check refused an update (auto.json left as it was).
"""
import argparse, datetime as dt, json, math, os, re, shutil, subprocess, sys, tempfile, urllib.request, urllib.error, warnings
warnings.filterwarnings('ignore')

CY = 'https://raw.githubusercontent.com/cyterat/deepstate-map-data/main/data/deepstatemap_data_%s.geojson'
OWL = 'https://github.com/owlmaps/map-data'
MAX_CHANGE_KM2 = 2500      # one update may not move more land than this (a week of fighting is ~100-300)
EPS = 0.02                 # km2, drop numerical slivers
LABELS = ["PERSONNEL","TANKS","ARMOURED FIGHTING VEHICLES","ARTILLERY SYSTEMS","MLRS","AIR DEFENCE SYSTEMS","AIRCRAFT","HELICOPTERS","UAVs",
          "CRUISE MISSILES","SHIPS / BOATS","SUBMARINES","VEHICLES & FUEL TANKERS","SPECIAL EQUIPMENT","UGVs"]

class Refuse(Exception): pass

def http_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'frontlines-auto/1'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode('utf-8'))

# ───────────────────────── DeepState ─────────────────────────
def deepstate_step(auto, today):
    from shapely.geometry import shape
    from shapely.ops import unary_union, transform
    from shapely.validation import make_valid
    import pyproj
    ds = auto.get('deepstate') or {}
    old_date = ds.get('date')
    zones = ds.get('zones')
    if not old_date or not zones: raise Refuse('auto.json has no deepstate baseline')
    new_date, new_geo = None, None
    for k in range(0, 7):
        d = today - dt.timedelta(days=k)
        try:
            new_geo = http_json(CY % d.strftime('%Y%m%d')); new_date = d.isoformat(); break
        except urllib.error.HTTPError as e:
            if e.code != 404: raise
    if not new_geo: raise Refuse('no DeepState file found in the last 7 days')
    if new_date <= old_date:
        return {'skipped': 'already at %s (latest archive file %s)' % (old_date, new_date)}
    old_geo = http_json(CY % old_date.replace('-', ''))
    proj = pyproj.Transformer.from_crs(4326, 'EPSG:3035', always_xy=True).transform
    area = lambda g: transform(proj, g).area / 1e6
    V = lambda g: g if g.is_valid else make_valid(g)
    def polys(g):
        if g.is_empty: return []
        if g.geom_type == 'Polygon': return [g]
        if g.geom_type in ('MultiPolygon', 'GeometryCollection'):
            out = []
            for x in g.geoms: out += polys(x)
            return out
        return []
    load = lambda d: unary_union([V(shape(f['geometry'])) for f in d['features']])
    old, new = load(old_geo), load(new_geo)
    A, R = new.difference(old), old.difference(new)
    Ac = [c for c in polys(A) if area(c) >= EPS]; Rc = [c for c in polys(R) if area(c) >= EPS]
    addkm, remkm = sum(map(area, Ac)), sum(map(area, Rc))
    if addkm + remkm > MAX_CHANGE_KM2:
        raise Refuse('DeepState change %s -> %s is %.0f km2 (limit %d) — not applied, check by hand' % (old_date, new_date, addkm + remkm, MAX_CHANGE_KM2))
    feats = zones['features']
    geoms = [V(shape(f['geometry'])) for f in feats]
    isocc = ['status.occupied' in f['properties'].get('name', '') for f in feats]
    occ_ids = [i for i, v in enumerate(isocc) if v]
    if not occ_ids: raise Refuse('baseline zones have no occupied polygon')
    occ_before = unary_union([geoms[i] for i in occ_ids])
    changed, log = set(), []
    Aall = unary_union(Ac) if Ac else None
    Rall = unary_union(Rc) if Rc else None
    for c in sorted(Ac, key=lambda c: -area(c)):                 # additions: merge into the nearest occupied polygon
        best = min(occ_ids, key=lambda i: c.distance(geoms[i]))
        geoms[best] = unary_union([geoms[best], c.buffer(2e-7)]).buffer(0)
        changed.add(best); log.append({'op': 'add', 'poly': best, 'km2': round(area(c), 2), 'lat': round(c.centroid.y, 3), 'lon': round(c.centroid.x, 3)})
    if Aall is not None:                                          # carve additions out of non-occupied polygons
        for i, g in enumerate(geoms):
            if isocc[i] or not g.intersects(Aall): continue
            inter = area(g.intersection(Aall))
            if inter >= EPS / 2:
                geoms[i] = g.difference(Aall).buffer(0); changed.add(i); log.append({'op': 'carve', 'poly': i, 'km2': round(inter, 2)})
    if Rall is not None:                                          # removals: subtract from occupied polygons
        for i in occ_ids:
            g = geoms[i]
            if not g.intersects(Rall): continue
            inter = area(g.intersection(Rall))
            if inter >= EPS / 2:
                geoms[i] = g.difference(Rall).buffer(0); changed.add(i); log.append({'op': 'remove', 'poly': i, 'km2': round(inter, 2)})
    r7 = lambda coords: [[round(x, 7), round(y, 7), 0] for x, y, *_ in coords]
    def to_geojson(g):
        ps = [p for p in polys(g) if area(p) >= 0.005]
        pc = lambda p: [r7(p.exterior.coords)] + [r7(h.coords) for h in p.interiors]
        return {"type": "Polygon", "coordinates": pc(ps[0])} if len(ps) == 1 else {"type": "MultiPolygon", "coordinates": [pc(p) for p in ps]}
    new_feats = json.loads(json.dumps(feats))
    for i in sorted(changed): new_feats[i]['geometry'] = to_geojson(geoms[i])
    # integrity: the occupied area must move by what DeepState moved (±1% + 3 km2)
    occ_after = unary_union([V(shape(new_feats[i]['geometry'])) for i in occ_ids])
    net_expected = addkm - remkm
    net_got = area(occ_after) - area(occ_before)
    if abs(net_got - net_expected) > 3 + 0.01 * (addkm + remkm):
        raise Refuse('integrity check failed: occupied area moved %.2f km2, DeepState moved %.2f km2' % (net_got, net_expected))
    zones2 = dict(zones); zones2['features'] = new_feats
    auto['deepstate'] = {'date': new_date, 'asOf': new_date + ' 03:00 UTC', 'zones': zones2,
                         'change': {'from': old_date, 'addedKm2': round(addkm, 2), 'removedKm2': round(remkm, 2), 'patchesAdded': len(Ac), 'patchesRemoved': len(Rc), 'log': log}}
    return {'from': old_date, 'to': new_date, 'addedKm2': round(addkm, 2), 'removedKm2': round(remkm, 2), 'patches': len(Ac) + len(Rc), 'polysRewritten': len(changed)}

# ───────────────────────── UA units ─────────────────────────
def units_step(auto):
    ua = auto.get('ua') or {}
    names = dict(ua.get('names') or {}); prev_pos = ua.get('pos') or {}
    if not names: raise Refuse('auto.json has no unit-name baseline')
    tmp = tempfile.mkdtemp(prefix='owl_')
    try:
        run = lambda *a: subprocess.run(a, cwd=tmp, check=True, capture_output=True, text=True).stdout
        run('git', 'clone', '--depth', '1', '--filter=blob:none', '--no-checkout', OWL, '.')
        files = run('git', 'ls-tree', '-r', 'HEAD', '--name-only').split('\n')
        days = sorted(f for f in files if re.fullmatch(r'data/20\d{6}\.json', f))
        if not days: raise Refuse('owlmaps archive has no daily files')
        latest = days[-1]; snap = '%s-%s-%s' % (latest[5:9], latest[9:11], latest[11:13])
        if snap <= str(ua.get('snap', '')):
            return {'skipped': 'already at %s (latest archive file %s)' % (ua.get('snap'), snap)}
        run('git', 'checkout', 'HEAD', '--', 'data/base.json', latest)
        base = json.load(open(os.path.join(tmp, 'data/base.json'), encoding='utf-8'))
        day = json.load(open(os.path.join(tmp, latest), encoding='utf-8'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    um = base.get('unit_map') or {}
    new_ids = {}
    for k, v in um.items():
        if isinstance(v, dict) and v.get('s') == 'ua' and k not in names:
            nm = str(v.get('n', '')).strip()
            if nm: new_ids[k] = nm
    allnames = dict(names); allnames.update(new_ids)
    r3 = lambda x: math.floor(x * 1000 + 0.5) / 1000
    pos = {}
    for r in (day.get('units') or {}).get('ua', []):
        i, p = str(r[0]), r[1]
        if i in allnames and isinstance(p, list) and len(p) >= 2 and all(isinstance(x, (int, float)) for x in p[:2]):
            pos[i] = [r3(p[1]), r3(p[0])]
    if len(pos) < 300 or len(pos) < 0.85 * len(prev_pos):
        raise Refuse('daily unit file %s has only %d usable positions (previous %d) — not applied' % (latest, len(pos), len(prev_pos)))
    def km(a, b):
        r = math.pi / 180; dA = (b[0] - a[0]) * r; dO = (b[1] - a[1]) * r
        h = math.sin(dA / 2) ** 2 + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin(dO / 2) ** 2
        return 12742 * math.asin(min(1, math.sqrt(h)))
    both = [k for k in pos if k in prev_pos]
    far = sum(1 for k in both if km(prev_pos[k], pos[k]) > 200)
    auto['ua'] = {'snap': snap, 'pos': pos, 'names': allnames}
    return {'snap': snap, 'positions': len(pos), 'previous': len(prev_pos), 'newIds': len(new_ids), 'movedOver200km': far}

# ───────────────────────── losses ─────────────────────────
def losses_step(auto, path):
    d = json.load(open(path, encoding='utf-8'))
    items = d.get('items') or []
    if [i.get('label') for i in items] != LABELS: raise Refuse('losses: the 15 labels must be present, in this order: ' + ', '.join(LABELS))
    num = lambda s: int(re.sub(r'[^\d]', '', s) or '0')
    for i in items:
        if not re.fullmatch(r'\d{1,3}(\.\d{3})*', i['value']) or not re.fullmatch(r'\+\d{1,3}(\.\d{3})*', i['delta']):
            raise Refuse('losses: bad number format for %s: %s %s (use 1.622.860 and +2.230)' % (i['label'], i['value'], i['delta']))
    if not re.fullmatch(r'20\d\d-\d\d-\d\d', d.get('date', '')): raise Refuse('losses: date must be YYYY-MM-DD')
    old = auto.get('losses') or {}
    if old.get('date') and d['date'] < old['date']: raise Refuse('losses: older than what is already stored (%s)' % old['date'])
    if old.get('items'):
        prev = {i['label']: num(i['value']) for i in old['items']}
        for i in items:
            if num(i['value']) < prev.get(i['label'], 0): raise Refuse('losses: %s went DOWN (%s < %d) — cumulative counters cannot fall' % (i['label'], i['value'], prev[i['label']]))
            if prev.get(i['label']) and num(i['value']) > prev[i['label']] * 1.05 + 50: raise Refuse('losses: %s jumped by more than 5%% — check by hand' % i['label'])
    keep = {k: d[k] for k in ('date', 'dateLabel', 'srcDate', 'via', 'bulletin') if d.get(k)}
    keep['items'] = [{'label': i['label'], 'value': i['value'], 'delta': i['delta']} for i in items]
    auto['losses'] = keep
    return {'date': d['date'], 'personnel': items[0]['value']}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--auto', default='auto.json'); ap.add_argument('--skip-deepstate', action='store_true'); ap.add_argument('--skip-units', action='store_true')
    ap.add_argument('--losses'); ap.add_argument('--dry', action='store_true'); ap.add_argument('--today')
    a = ap.parse_args()
    auto = json.load(open(a.auto, encoding='utf-8'))
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()
    summary, refused = {}, []
    steps = []
    if not a.skip_deepstate: steps.append(('deepstate', lambda: deepstate_step(auto, today)))
    if not a.skip_units: steps.append(('units', lambda: units_step(auto)))
    if a.losses: steps.append(('losses', lambda: losses_step(auto, a.losses)))
    for name, fn in steps:
        snapshot = json.dumps(auto.get(name if name != 'units' else 'ua'), separators=(',', ':'))
        try: summary[name] = fn()
        except Refuse as e: summary[name] = {'refused': str(e)}; refused.append(name)
        except Exception as e:
            summary[name] = {'error': '%s: %s' % (type(e).__name__, e)}; refused.append(name)
            auto[name if name != 'units' else 'ua'] = json.loads(snapshot) if snapshot != 'null' else None
    changed = any(isinstance(v, dict) and not (set(v) & {'skipped', 'refused', 'error'}) for v in summary.values())
    if changed:
        auto['updated'] = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        log = auto.setdefault('log', [])
        log.append({'at': auto['updated'], **{k: v for k, v in summary.items() if not (set(v) & {'skipped'})}})
        auto['log'] = log[-60:]
        if not a.dry:
            tmpf = a.auto + '.tmp'
            json.dump(auto, open(tmpf, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
            os.replace(tmpf, a.auto)
    print(json.dumps({'changed': changed, 'dry': a.dry, 'summary': summary}, ensure_ascii=False, indent=1))
    sys.exit(2 if refused and not changed else 0)

if __name__ == '__main__': main()
