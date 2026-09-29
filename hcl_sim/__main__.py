"""Command line:  python -m hcl_sim <command> ...

  teams                          list teams and squads from the league sheet
  simulate HOME AWAY             simulate one match (codes like TUR, or full names)
  week N                         simulate every fixture in week N of the Schedule tab
  validate FILE [FILE ...]       check match files for teleports and logic errors
  calibrate [--matches N]        run many matches and compare statistics with real football
  ratings-template               write every player's full attribute profile to a CSV
"""

import argparse
import csv
import os
import sys
import time

from . import ratings, sheet
from .run import simulate, simulate_week, write_match, read_match
from .validate import validate, summarise


def _league(args):
    cfg = sheet.load_config(args.config)
    return sheet.load_league(cfg, offline=args.offline)


def cmd_teams(args):
    league = _league(args)
    for code, t in league['teams'].items():
        squad = [p for p in league['players'].values() if p['team'] == code]
        print(f"{code}  {t['name']}  ({len(squad)} players)  manager: {t['manager']}")


def _print_summary(data):
    r = data['result']
    th, ta = data['teams']['home'], data['teams']['away']
    s = data['stats']['teams']
    names = {p['id']: p['name'] for p in data['players']}
    print(f"\n  {th['name']} {r['home']} - {r['away']} {ta['name']}")
    for g in r['goals']:
        extra = ' (OG)' if g['own_goal'] else (f", assist {names.get(g['assist'])}" if g['assist'] else '')
        print(f"    {g['minute']:>5}'  {g['team']}  {names.get(g['scorer'], g['scorer'])}{extra}")
    rows = [('Possession %', 'possession'), ('xG', 'xg'), ('Shots', 'shots'), ('On target', 'shots_on_target'),
            ('Passes', 'passes'), ('Pass accuracy %', 'pass_accuracy'), ('Tackles won', 'tackles_won'),
            ('Interceptions', 'interceptions'), ('Saves', 'saves'), ('Fouls', 'fouls'), ('Yellow cards', 'yellow_cards'),
            ('Red cards', 'red_cards'), ('Corners', 'corners'), ('Offsides', 'offsides')]
    print()
    for label, k in rows:
        print(f"    {label:<18}{s['home'][k]:>8}  {s['away'][k]:>8}")
    print(f"    Ball in play: {data['stats']['ball_in_play_minutes']} min")


def cmd_simulate(args):
    league = _league(args)
    h = sheet.resolve_team(league, args.home)
    a = sheet.resolve_team(league, args.away)
    t0 = time.time()
    data = simulate(league, h, a, seed=args.seed, fps=args.fps)
    took = time.time() - t0
    out = args.out or os.path.join('matches', f"{h}_v_{a}_seed{data['engine']['seed']}.json.gz")
    size = write_match(data, out)
    _print_summary(data)
    print(f'\n  Simulated in {took:.1f}s, seed {data["engine"]["seed"]} -> {out} ({size / 1e6:.1f} MB)')
    print('  ' + summarise(validate(data)).replace('\n', '\n  '))


def cmd_week(args):
    league = _league(args)
    done, csv_path = simulate_week(league, args.week, args.out, fps=args.fps)
    for fx, data, path, size, rep in done:
        r = data['result']
        print(f"  {fx['home']} {r['home']} - {r['away']} {fx['away']}   {'valid' if rep['ok'] else 'INVALID'}   {path}")
    print(f'\n  Results in the sheet format: {csv_path}')


def cmd_validate(args):
    bad = 0
    for path in args.files:
        rep = validate(read_match(path))
        print(f'{path}\n  ' + summarise(rep).replace('\n', '\n  '))
        bad += 0 if rep['ok'] else 1
    sys.exit(1 if bad else 0)


def cmd_ratings_template(args):
    league = _league(args)
    out = args.out
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['PLAYER ID', 'PLAYER NAME', 'TEAM', 'POSITION'] + [a.upper().replace('_', ' ') for a in ratings.ATTRIBUTES])
        for p in sorted(league['players'].values(), key=lambda p: (p['team'], p['id'])):
            attrs = ratings.derive(p, league['attributes'].get(p['id']))
            w.writerow([p['id'], p['name'], p['team'], p['position']] + [round(attrs[a]) for a in ratings.ATTRIBUTES])
    print(f'Wrote {len(league["players"])} players to {out}')


def cmd_calibrate(args):
    from .calibrate import run_calibration
    run_calibration(_league(args), args.matches, args.workers)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m hcl_sim', description='HCL Season 3 match simulator')
    ap.add_argument('--config', help='league config JSON (default: league.json)')
    ap.add_argument('--offline', action='store_true', help='use the cached copy of the sheet')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('teams').set_defaults(fn=cmd_teams)

    s = sub.add_parser('simulate')
    s.add_argument('home')
    s.add_argument('away')
    s.add_argument('--seed', type=int)
    s.add_argument('--fps', type=int, default=5)
    s.add_argument('--out')
    s.set_defaults(fn=cmd_simulate)

    w = sub.add_parser('week')
    w.add_argument('week')
    w.add_argument('--fps', type=int, default=5)
    w.add_argument('--out', default='matches')
    w.set_defaults(fn=cmd_week)

    v = sub.add_parser('validate')
    v.add_argument('files', nargs='+')
    v.set_defaults(fn=cmd_validate)

    c = sub.add_parser('calibrate')
    c.add_argument('--matches', type=int, default=24)
    c.add_argument('--workers', type=int, default=0)
    c.set_defaults(fn=cmd_calibrate)

    r = sub.add_parser('ratings-template')
    r.add_argument('--out', default='attributes.csv')
    r.set_defaults(fn=cmd_ratings_template)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == '__main__':
    main()
