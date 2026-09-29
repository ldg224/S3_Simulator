"""Runs a batch of matches and compares the statistics with real football.

Targets are typical per-team, per-match figures from top-flight 11-a-side football.
They're a sanity check on realism, not something every single match must hit.
"""

import itertools
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor

from .run import simulate
from .validate import validate

# (label, key, low, high) per team per match unless noted
TARGETS = [
    ('Goals per match (both teams)', 'goals_total', 2.2, 3.3),
    ('Shots', 'shots', 9, 16),
    ('Shots on target', 'shots_on_target', 3, 6.5),
    ('Conversion % (goals/shots)', 'conversion', 8, 14),
    ('xG', 'xg', 1.0, 1.8),
    ('Passes', 'passes', 300, 600),
    ('Pass accuracy %', 'pass_accuracy', 72, 88),
    ('Tackles', 'tackles', 12, 24),
    ('Interceptions', 'interceptions', 6, 16),
    ('Fouls', 'fouls', 8, 14),
    ('Yellow cards', 'yellow_cards', 1.0, 2.5),
    ('Corners', 'corners', 3.5, 7),
    ('Offsides', 'offsides', 1, 3),
    ('Saves', 'saves', 2, 4.5),
    ('Ball in play (min; no subs in HCL)', 'in_play', 55, 64),
    ('Distance per outfield player (km)', 'km_per_outfield', 9, 12),
]


def _one(job):
    league, h, a, seed = job
    t0 = time.time()
    d = simulate(league, h, a, seed=seed, include_frames=True)
    rep = validate(d)
    d.pop('frames')
    return d, rep, time.time() - t0


def run_calibration(league, n, workers=0):
    codes = sorted(league['teams'])
    pairs = list(itertools.permutations(codes, 2))
    rng = random.Random(7)
    jobs = [(league, *pairs[i % len(pairs)], rng.randrange(1 << 30)) for i in range(n)]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_one, jobs))
    wall = time.time() - t0

    per_team = []
    invalid = 0
    for d, rep, _ in results:
        invalid += 0 if rep['ok'] else 1
        for side in ('home', 'away'):
            s = dict(d['stats']['teams'][side])
            s['goals_total'] = d['result']['home'] + d['result']['away']
            s['conversion'] = 100 * s['goals'] / s['shots'] if s['shots'] else 0
            s['in_play'] = d['stats']['ball_in_play_minutes']
            outfield = [p for p in d['players'] if p['team'] == d['teams'][side]['code'] and p['position'] != 'GK']
            s['km_per_outfield'] = sum(d['stats']['players'][p['id']]['distance_km'] for p in outfield) / max(len(outfield), 1)
            per_team.append(s)

    print(f'\n{len(results)} matches in {wall:.0f}s ({sum(r[2] for r in results) / len(results):.1f}s each, {workers} workers)')
    print(f'Validation: {len(results) - invalid} passed, {invalid} failed\n')
    print(f"  {'Statistic':<38}{'Sim avg':>9}   {'Real range':<14}")
    for label, key, lo, hi in TARGETS:
        avg = sum(s[key] for s in per_team) / len(per_team)
        mark = 'ok ' if lo <= avg <= hi else 'LOW' if avg < lo else 'HIGH'
        print(f'  {label:<38}{avg:>9.2f}   {lo:g} - {hi:g}   {mark}')
    scores = {}
    by_team = {}
    for d, _, _ in results:
        k = f"{d['result']['home']}-{d['result']['away']}"
        scores[k] = scores.get(k, 0) + 1
        for side, other in (('home', 'away'), ('away', 'home')):
            code = d['teams'][side]['code']
            t = by_team.setdefault(code, [0, 0, 0, 0.0, 0.0])
            t[0] += 1
            t[1] += d['result'][side]
            t[2] += d['result'][other]
            t[3] += d['stats']['teams'][side]['xg']
            t[4] += d['stats']['teams'][other]['xg']
    print('\n  Scorelines: ' + ', '.join(f'{k} x{v}' for k, v in sorted(scores.items(), key=lambda kv: -kv[1])))
    print('\n  Per team (avg per match):  scored  conceded  xG for  xG against')
    for code, (n, gf, ga, xf, xa) in sorted(by_team.items()):
        print(f'    {code:<6} {gf / n:>12.2f} {ga / n:>9.2f} {xf / n:>7.2f} {xa / n:>11.2f}')
    return per_team
