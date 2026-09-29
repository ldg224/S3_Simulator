"""High-level entry points: simulate a match, a week of fixtures, or a calibration batch."""

import csv
import gzip
import hashlib
import json
import os
import time

from . import output, sheet, teams
from .engine import Match
from .validate import validate


def match_seed(*parts):
    return int(hashlib.sha256('|'.join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def simulate(league, home_code, away_code, seed=None, fps=5, info=None, include_frames=True, on_progress=None):
    home = teams.build_team(league, home_code)
    away = teams.build_team(league, away_code)
    if seed is None:
        seed = match_seed(home_code, away_code, time.time())
    info = dict(info or {})
    info.update({'home': home_code, 'away': away_code})
    m = Match(home, away, seed=seed, fps=fps, info=info).run(on_progress=on_progress)
    return output.build(m, include_frames=include_frames)


def write_match(data, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    text = json.dumps(data, separators=(',', ':'))
    if path.endswith('.gz'):
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            f.write(text)
    else:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
    return os.path.getsize(path)


def read_match(path):
    if path.endswith('.gz'):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return json.load(f)
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def summarise_match(data, report, fname=None, size=None):
    """Small description of a match for the simulator page's library."""
    from datetime import datetime
    names = {p['id']: p['name'] for p in data['players']}
    th, ta = data['teams']['home'], data['teams']['away']
    return {
        'file': fname,
        'created': datetime.now().isoformat(timespec='seconds'),
        'seed': data['engine']['seed'],
        'week': data['match'].get('week'),
        'date': data['match'].get('date'),
        'time': data['match'].get('time'),
        'home': {'code': th['code'], 'name': th['name'], 'colour': th['colour']},
        'away': {'code': ta['code'], 'name': ta['name'], 'colour': ta['colour']},
        'result': {
            'home': data['result']['home'], 'away': data['result']['away'],
            'goals': [dict(g, scorer_name=names.get(g['scorer'], g['scorer']),
                           assist_name=names.get(g['assist']) if g['assist'] else None)
                      for g in data['result']['goals']],
        },
        'stats': data['stats']['teams'],
        'valid': report['ok'],
        'problems': [f'{k}: {d}' for k, d in report['problems'][:5]],
        'size': size,
    }


def sheet_goal_columns(data, max_goals=None):
    """Goals in the Schedule & Results format: [(minute, player id), ...] in time order."""
    out = []
    for g in data['result']['goals']:
        pid = g['scorer'] + (' (OG)' if g['own_goal'] else '')
        out.append((g['minute'], pid))
    return out[:max_goals] if max_goals else out


def results_rows(fixtures):
    """CSV rows matching the league sheet's Schedule & Results columns."""
    n = max([len(sheet_goal_columns(d)) for _, d in fixtures] + [6])
    header = ['WEEK', 'DATE', 'TIME', 'STATUS', 'HOME', 'HOME SCORE', 'AWAY', 'AWAY SCORE', 'YOUTUBE LINK']
    for i in range(1, n + 1):
        header += [f'GOAL {i} MIN', f'GOAL {i} ID']
    rows = [header]
    for fx, d in fixtures:
        row = [fx.get('week', ''), fx.get('date', ''), fx.get('time', ''), 'FINALISED', fx.get('home', ''),
               d['result']['home'], fx.get('away', ''), d['result']['away'], '']
        for minute, pid in sheet_goal_columns(d):
            row += [minute, pid]
        rows.append(row + [''] * (len(header) - len(row)))
    return rows


def simulate_week(league, week, out_dir, fps=5, seed_salt=''):
    fixtures = [r for r in league['schedule'] if (r.get('week') or '').strip() == str(week)]
    if not fixtures:
        raise ValueError(f'No fixtures found for week {week} on the Schedule tab')
    done = []
    for fx in fixtures:
        h = sheet.resolve_team(league, fx['home'])
        a = sheet.resolve_team(league, fx['away'])
        seed = match_seed(week, h, a, fx.get('date'), seed_salt)
        data = simulate(league, h, a, seed=seed, fps=fps, info={'week': week, 'date': fx.get('date'), 'time': fx.get('time')})
        rep = validate(data)
        path = os.path.join(out_dir, f'week{week}_{h}_v_{a}.json.gz')
        size = write_match(data, path)
        done.append((fx, data, path, size, rep))
    csv_path = os.path.join(out_dir, f'week{week}_results.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows(results_rows([(fx, d) for fx, d, *_ in done]))
    return done, csv_path
