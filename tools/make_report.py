#!/usr/bin/env python3
"""Compose the daily report (Turkish, short) from the step outputs and write reports/YYYY-MM-DD.md.

Inputs are the JSON files the steps printed (stdout redirected by the caller), all optional:
  --auto-out   output of tools/update_auto.py  (DeepState, UAControlMap unit positions, Blood Loss of Russia counters)
  --cargo-out  output of tools/update_cargo200.py (Mediazona)
  --ml-out     output of tools/check_militaryland.py
  --notes      a plain-text/markdown file with extra lines from the caller (Militaryland news headlines, anything that went wrong)
Usage: python3 tools/make_report.py --date 2026-11-23 --auto auto.json --auto-out a.json --cargo-out c.json --ml-out m.json [--notes n.md]
Prints the report and writes reports/<date>.md. The site itself is NOT redeployed: it reads auto.json when it opens.
"""
import argparse, json, os

def load(p):
    if not p or not os.path.exists(p): return None
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return None

def fmt(n): return format(int(n), ',').replace(',', '.')   # Turkish style 1.234.567

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True); ap.add_argument('--auto', default='auto.json')
    ap.add_argument('--auto-out'); ap.add_argument('--cargo-out'); ap.add_argument('--ml-out'); ap.add_argument('--notes'); ap.add_argument('--out-dir', default='reports')
    a = ap.parse_args()
    auto = load(a.auto) or {}
    A, C, M = load(a.auto_out) or {}, load(a.cargo_out) or {}, load(a.ml_out) or {}
    S = (A.get('summary') or {})
    L = []
    flag = lambda s: '✔' if s == 'ok' else ('＝' if s == 'same' else '✘')
    def state(x):
        if x is None: return 'none'
        if 'refused' in x or 'error' in x: return 'fail'
        if 'skipped' in x: return 'same'
        return 'ok'
    # Blood Loss of Russia
    x = S.get('losses'); st = state(x)
    if st == 'ok':
        items = {i['label']: i for i in (auto.get('losses') or {}).get('items', [])}
        top = ', '.join('%s %s (%s)' % (k.title() if k.isupper() and len(k) > 5 else k, items[k]['value'], items[k]['delta']) for k in ('PERSONNEL', 'TANKS', 'ARTILLERY SYSTEMS', 'UAVs') if k in items)
        L.append('- **Blood Loss of Russia** ✔ güncellendi — %s bülteni · %s' % ((auto.get('losses') or {}).get('srcDate', x.get('date')), top))
    elif st == 'fail': L.append('- **Blood Loss of Russia** ✘ uygulanamadı — %s' % (x.get('refused') or x.get('error')))
    elif st == 'same': L.append('- **Blood Loss of Russia** ＝ değişmedi — %s' % x['skipped'])
    else: L.append('- **Blood Loss of Russia** ＝ bugün güncellenmedi (iki bağımsız kaynakta aynı rakam bulunamadı ya da yeni bülten yok)')
    # Mediazona
    if C:
        if C.get('changed'):
            s = C['summary']; n = s['named']
            extra = []
            if s.get('statsChanged'): extra.append('; '.join('%s %s→%s' % (d['label'].title(), d['from'], d['to']) for d in s['statsChanged']))
            if s.get('regionsChanged'): extra.append('bölge sıralaması güncellendi')
            if s.get('estimateChanged'): extra.append('istatistiksel tahmin güncellendi')
            L.append('- **Mediazona** ✔ güncellendi — isimli liste %s → %s (+%s, %s%s)%s' % (fmt(n['from']), fmt(n['to']), fmt(n['delta']), s['date'], '' if n.get('exact') else ', yuvarlak', (' · ' + ' · '.join(extra)) if extra else ''))
        elif C.get('refused'): L.append('- **Mediazona** ✘ uygulanamadı — %s' % C['refused'])
        else: L.append('- **Mediazona** ＝ yeni güncelleme yok — %s' % C.get('skipped', ''))
    else: L.append('- **Mediazona** ＝ bugün kontrol edilemedi')
    # DeepState
    x = S.get('deepstate'); st = state(x)
    if st == 'ok': L.append('- **DeepState haritası** ✔ %s → %s: +%s km² / −%s km² (%d yama)' % (x['from'], x['to'], x['addedKm2'], x['removedKm2'], x['patches']))
    elif st == 'same': L.append('- **DeepState haritası** ＝ %s' % x['skipped'])
    elif st == 'fail': L.append('- **DeepState haritası** ✘ %s' % (x.get('refused') or x.get('error')))
    # UAControlMap
    x = S.get('units'); st = state(x)
    if st == 'ok': L.append('- **UAControlMap birlik konumları** ✔ %s: %d konum (önceki %d), %d yeni birlik kimliği, %d birlik 200 km’den fazla yer değiştirdi' % (x['snap'], x['positions'], x['previous'], x['newIds'], x['movedOver200km']))
    elif st == 'same': L.append('- **UAControlMap birlik konumları** ＝ %s' % x['skipped'])
    elif st == 'fail': L.append('- **UAControlMap birlik konumları** ✘ %s' % (x.get('refused') or x.get('error')))
    # Militaryland
    if M and M.get('summary'):
        s = M['summary']
        if s['newCount']:
            L.append('- **Militaryland.net** %d yeni birim sayfası (sitede henüz yok, toplam bekleyen %d):' % (s['newCount'], s['pendingTotal']))
            for r in s['new'][:25]:
                L.append('  - %s — %s · %s%s' % (r['title'], r['group'], r['created'], (' · haritada eşleşti (id %s)' % ', '.join(r['mapMatch'])) if r['mapMatch'] else ''))
            if s['newCount'] > 25: L.append('  - … ve %d tane daha (state/ml_pending.json)' % (s['newCount'] - 25))
        else: L.append('- **Militaryland.net** ＝ yeni birim sayfası yok (bekleyen toplam %d)' % s['pendingTotal'])
    elif M.get('refused'): L.append('- **Militaryland.net** ✘ %s' % M['refused'])
    else: L.append('- **Militaryland.net** ＝ bugün kontrol edilemedi')
    notes = ''
    if a.notes and os.path.exists(a.notes): notes = open(a.notes, encoding='utf-8').read().strip()
    body = '## Günlük güncelleme — %s\n\n%s\n' % (a.date, '\n'.join(L))
    if notes: body += '\n%s\n' % notes
    body += '\nSite yeniden yayınlanmadı (Netlify kredisi harcanmadı): güncel veri `auto.json` olarak depoda; site açıldığında kendisi okur.\n'
    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, a.date + '.md'), 'w', encoding='utf-8').write(body)
    print(body)

if __name__ == '__main__': main()
