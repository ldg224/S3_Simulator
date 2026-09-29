"""Reads the HCL league Google Sheet (published CSV tabs).

Columns are matched by header name, in the same way as the website, so the sheet can be
reordered or extended without breaking the simulator. Every fetch is cached to disk, so
`--offline` works with the last downloaded copy.
"""

import csv
import io
import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def header_key(h):
    """'HOME SCORE' -> 'home_score'"""
    return re.sub(r'^_|_$', '', re.sub(r'[^a-z0-9]+', '_', h.strip().lower()))


def bracket_code(v):
    """'[TUR] FC Turtle' -> 'TUR'. Plain values are returned stripped."""
    m = re.match(r'^\s*\[([^\]]+)\]', v or '')
    return m.group(1).strip() if m else (v or '').strip()


def to_number(v):
    """'(9) Nine' -> 9, '$7,800.00' -> 7800, '8' -> 8, '' -> None"""
    s = (v or '').strip()
    if not s:
        return None
    m = re.match(r'^\((-?[\d.]+)\)', s)
    try:
        return float(m.group(1)) if m else float(re.sub(r'[^0-9.\-]', '', s))
    except ValueError:
        return None


def load_config(path=None):
    with open(path or os.path.join(ROOT, 'league.json'), encoding='utf-8') as f:
        return json.load(f)


def parse_csv_text(text):
    """CSV text -> list of dicts keyed by normalised header (blank rows skipped)."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    keys = [header_key(h) for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not any(v.strip() for v in r):
            continue
        out.append({k: (r[i].strip() if i < len(r) else '') for i, k in enumerate(keys) if k})
    return out


def fetch_tab(cfg, name, offline=False, texts=None):
    """Returns the tab as a list of dicts keyed by normalised header, or None if not configured.
    `texts` ({tab name: csv text}) supplies the data directly, e.g. when running in a browser."""
    if texts is not None:
        return parse_csv_text(texts[name]) if texts.get(name) else None
    gid = cfg['tabs'].get(name)
    if gid is None:
        return None
    cache_dir = os.path.join(ROOT, cfg.get('cache_dir', '.cache'))
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, f'{name}.csv')

    # A tab can also point at a local CSV file instead of the sheet.
    if str(gid).lower().endswith('.csv'):
        with open(os.path.join(ROOT, gid), encoding='utf-8-sig') as f:
            text = f.read()
    elif offline:
        with open(cache, encoding='utf-8') as f:
            text = f.read()
    else:
        try:
            with urllib.request.urlopen(cfg['sheet'] + str(gid), timeout=20) as res:
                text = res.read().decode('utf-8-sig')
            with open(cache, 'w', encoding='utf-8') as f:
                f.write(text)
        except OSError as err:
            if not os.path.exists(cache):
                raise RuntimeError(f"Couldn't download the {name} tab and there's no cached copy: {err}")
            print(f'warning: using cached {name} tab ({err})')
            with open(cache, encoding='utf-8') as f:
                text = f.read()

    return parse_csv_text(text)


def pick(row, *keys):
    for k in keys:
        if row.get(k):
            return row[k]
    return ''


def load_league(cfg=None, offline=False, texts=None):
    """Returns {'teams': {code: {...}}, 'players': {id: {...}}, 'schedule': [...], 'attributes': {...}, 'tactics': {...}}"""
    cfg = cfg or load_config()
    teams = {}
    for r in fetch_tab(cfg, 'teams', offline, texts) or []:
        code = pick(r, 'team_code', 'code').upper()
        if code:
            teams[code] = {
                'code': code,
                'name': pick(r, 'team_name', 'name') or code,
                'manager': pick(r, 'manager_name', 'manager'),
                'colour': pick(r, 'primary_hex_code', 'colour', 'color') or '#888888',
            }

    players = {}
    for r in fetch_tab(cfg, 'roster', offline, texts) or []:
        pid = pick(r, 'player_id', 'id')
        if not pid:
            continue
        players[pid] = {
            'id': pid,
            'name': pick(r, 'player_name', 'name'),
            'team': bracket_code(pick(r, 'assigned_team', 'team')).upper(),
            'position': bracket_code(r.get('position', '')).upper(),
            'offense': to_number(pick(r, 'offense_rating', 'offense')),
            'defense': to_number(pick(r, 'defense_rating', 'defense')),
        }

    # Optional tab of detailed attributes: PLAYER ID plus any attribute columns (1-100).
    attributes = {}
    for r in fetch_tab(cfg, 'attributes', offline, texts) or []:
        pid = pick(r, 'player_id', 'id')
        if pid:
            attributes[pid] = {k: to_number(v) for k, v in r.items() if k not in ('player_id', 'id', 'player_name', 'name') and to_number(v) is not None}

    # Optional tab of team tactics: TEAM CODE, FORMATION, PRESSING, LINE HEIGHT, TEMPO, WIDTH, DIRECTNESS.
    tactics = {}
    for r in fetch_tab(cfg, 'tactics', offline, texts) or []:
        code = pick(r, 'team_code', 'code').upper()
        if code:
            t = {k: to_number(v) for k, v in r.items() if to_number(v) is not None}
            if r.get('formation'):
                t['formation'] = r['formation'].strip()
            tactics[code] = t

    schedule = []
    for r in fetch_tab(cfg, 'schedule', offline, texts) or []:
        if r.get('home') and r.get('away'):
            schedule.append(r)

    return {'teams': teams, 'players': players, 'attributes': attributes, 'tactics': tactics, 'schedule': schedule}


def league_info(league):
    """Teams (with squad sizes) and fixtures by week, for the simulator page."""
    teams = []
    for code, t in league['teams'].items():
        n = sum(1 for p in league['players'].values() if p['team'] == code)
        teams.append(dict(t, players=n))
    weeks = {}
    for r in league['schedule']:
        w = (r.get('week') or '').strip()
        if w:
            weeks.setdefault(w, []).append({'home': r['home'], 'away': r['away'], 'date': r.get('date'), 'time': r.get('time')})
    return {'teams': teams, 'weeks': weeks, 'players': len(league['players'])}


def resolve_team(league, value):
    """Accepts a team code or full name."""
    v = bracket_code(value).upper()
    if v in league['teams']:
        return v
    for code, t in league['teams'].items():
        if t['name'].upper() == (value or '').strip().upper():
            return code
    raise KeyError(f'Unknown team: {value}')
