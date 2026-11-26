#!/usr/bin/env python3
"""Builds cargo200/front/* (the front-line history shown on the CARGO200 map) from two public sources.

  1. DeepState (daily, from 2024-07-08)   cyterat/deepstate-map-data on GitHub (GPL-3.0), occupied territory as a MultiPolygon per day
  2. Schematic frames (2022-02-24 .. 2024-07-01), reconstructed from ISW assessments, about 5-10 km accurate
     longlinecode/russo-ukrainian-front-daily, data/history.json

Output (coordinates are integers in 1/1000 degree; a ring is [x0, y0, dx, dy, dx, dy, ...]):
  cargo200/front/index.json    {"v":1,"s":1000,"pre":[dates],"days":[dates]}      every frame date, so the slider knows the steps
  cargo200/front/pre.json      {"v":1,"s":1000,"f":[{"d":date,"p":[[ring,...],...]}, ...]}   schematic frames (one file)
  cargo200/front/YYYY-MM.json  same shape, DeepState days of that month

Usage:
  build_front.py --all ALL.geojson --pre HISTORY.json --files NAMES.txt
                                                          full build (ALL = deepstate-map-data.geojson, unzipped; features in date order, the
                                                          first ones have no date: their dates are the file names listed in NAMES.txt, i.e. the
                                                          output of `git ls-tree -r --name-only HEAD data` of the DeepState archive)
  build_front.py --update                                 add the missing days up to today from the per-day files on GitHub
"""
import argparse, json, os, sys, datetime, urllib.request
from shapely.geometry import shape, Polygon, MultiPolygon

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'cargo200', 'front')
S = 1000
TOL = 0.002          # simplification, degrees (about 200 m)
MIN_KM2 = 0.4        # drop specks
RAW = 'https://raw.githubusercontent.com/cyterat/deepstate-map-data/main/data/deepstatemap_data_%s.geojson'


def enc_ring(coords):
    pts = []
    for x, y in coords:
        q = (round(x * S), round(y * S))
        if not pts or q != pts[-1]:
            pts.append(q)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        return None
    out = [pts[0][0], pts[0][1]]
    for i in range(1, len(pts)):
        out += [pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]]
    return out


def km2(poly):
    c = poly.centroid.y
    import math
    return poly.area * 111.32 * math.cos(math.radians(c)) * 110.57


def frame_from_geom(g):
    g = g.simplify(TOL, preserve_topology=True)
    polys = list(g.geoms) if isinstance(g, MultiPolygon) else [g]
    out = []
    for p in polys:
        if p.is_empty or km2(p) < MIN_KM2:
            continue
        rings = [enc_ring(list(p.exterior.coords))]
        for h in p.interiors:
            if km2(Polygon(h)) >= MIN_KM2:
                rings.append(enc_ring(list(h.coords)))
        rings = [r for r in rings if r]
        if rings and rings[0]:
            out.append(rings)
    return out


def write(name, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), 'w', encoding='utf-8') as f:
        json.dump(obj, f, separators=(',', ':'))


def load_months():
    m = {}
    for fn in sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []:
        if len(fn) == 12 and fn.endswith('.json') and fn[4] == '-':
            m[fn[:7]] = json.load(open(os.path.join(OUT, fn), encoding='utf-8'))['f']
    return m


def save_index(pre_dates, months):
    days = sorted(f['d'] for fr in months.values() for f in fr)
    write('index.json', {'v': 1, 's': S, 'pre': pre_dates, 'days': days})
    return days


def full(all_path, pre_path, files_path):
    feats = json.load(open(all_path, encoding='utf-8'))['features']
    undated = [f for f in feats if not f['properties'].get('date')]
    dated = [f for f in feats if f['properties'].get('date')]
    # the undated ones are the days before the first dated feature, in file order; their dates are the file names in the archive's data/ folder
    first_dated = dated[0]['properties']['date'][:10]
    names = sorted(l.strip() for l in open(files_path) if l.strip())
    dates = []
    for nme in names:
        t = nme.rsplit('_', 1)[-1].split('.')[0]
        d = '%s-%s-%s' % (t[:4], t[4:6], t[6:8])
        if d < first_dated:
            dates.append(d)
    if len(dates) != len(undated):
        sys.exit('undated features %d != file names before %s: %d' % (len(undated), first_dated, len(dates)))
    months = {}
    for f, d in list(zip(undated, dates)) + [(f, f['properties']['date'][:10]) for f in dated]:
        fr = {'d': d, 'p': frame_from_geom(shape(f['geometry']))}
        months.setdefault(d[:7], []).append(fr)
    for k, v in months.items():
        v.sort(key=lambda x: x['d'])
        write(k + '.json', {'v': 1, 's': S, 'f': v})
    # schematic frames (already integers in 1/1000 degree, rings of one polygon each)
    h = json.load(open(pre_path, encoding='utf-8'))['frames']
    pre = []
    for x in h:
        ru = json.loads(x['ru']) if isinstance(x['ru'], str) else x['ru']
        pre.append({'d': x['d'], 'p': [[r] for r in ru]})
    write('pre.json', {'v': 1, 's': S, 'f': pre})
    days = save_index([x['d'] for x in pre], months)
    print('schematic frames', len(pre), 'days', len(days), days[0], days[-1])


def update():
    months = load_months()
    idx = json.load(open(os.path.join(OUT, 'index.json'), encoding='utf-8'))
    have = set(idx['days'])
    d = datetime.date.fromisoformat(idx['days'][-1]) + datetime.timedelta(days=1)
    today = datetime.datetime.utcnow().date()
    added = 0
    while d <= today:
        ds = d.isoformat()
        try:
            raw = urllib.request.urlopen(RAW % ds.replace('-', ''), timeout=60).read()
        except Exception as e:
            print('no file for', ds, e)
            d += datetime.timedelta(days=1)
            continue
        feats = json.loads(raw)['features']
        polys = []
        for f in feats:
            g = shape(f['geometry'])
            polys += list(g.geoms) if isinstance(g, MultiPolygon) else [g]
        fr = {'d': ds, 'p': frame_from_geom(MultiPolygon(polys))}
        months.setdefault(ds[:7], []).append(fr)
        have.add(ds)
        added += 1
        d += datetime.timedelta(days=1)
    for k, v in months.items():
        v.sort(key=lambda x: x['d'])
        write(k + '.json', {'v': 1, 's': S, 'f': v})
    save_index(idx['pre'], months)
    print('added', added)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--all'); ap.add_argument('--pre'); ap.add_argument('--files'); ap.add_argument('--update', action='store_true')
    a = ap.parse_args()
    if a.update:
        update()
    elif a.all and a.pre and a.files:
        full(a.all, a.pre, a.files)
    else:
        ap.print_help()
