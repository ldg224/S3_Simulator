"""Builds engine teams from the league sheet."""

from . import ratings, tactics
from .models import Player, Team


def build_team(league, code):
    info = league['teams'][code]
    tac = dict(league['tactics'].get(code, {}))
    formation = tac.pop('formation', None) or '4-3-3'
    if formation not in tactics.FORMATIONS:
        print(f'warning: unknown formation {formation!r} for {code}, using 4-3-3')
        formation = '4-3-3'
    squad = [p for p in league['players'].values() if p['team'] == code]
    if len(squad) < 7:
        raise ValueError(f'{code} has only {len(squad)} players on the roster (need at least 7)')

    players = []
    for sp in squad:
        attrs = ratings.derive(sp, league['attributes'].get(sp['id']))
        players.append(Player(id=sp['id'], name=sp['name'], team=code, position=sp['position'] or 'MID', attrs=attrs))

    # Make sure somebody is in goal.
    if not any(p.position == 'GK' for p in players):
        worst = min(players, key=lambda p: p.attrs['finishing'] + p.attrs['passing'])
        worst.position = 'GK'
        print(f'warning: {code} has no goalkeeper; {worst.name} goes in goal')

    # Optional manager choices: XI by slot, set-piece takers and captain (player ids).
    chosen = tac.pop('lineup', None) or {}
    takers = {kind: str(tac.pop(key)) for kind, key in (('penalty', 'penalties'), ('free_kick', 'freekicks'), ('corner', 'corners')) if tac.get(key)}
    captain = str(tac.pop('captain', '') or '')
    lineup = tactics.assign_lineup(players, formation, chosen if isinstance(chosen, dict) else None)
    starters = []
    for p, slot in lineup:
        p.slot = slot
        p.line = tactics.FORMATIONS[formation][slot][0]
        starters.append(p)
    tac_clean = {k: v / 100 if v > 1 else v for k, v in tac.items() if isinstance(v, (int, float))}
    return Team(code=code, name=info['name'], colour=info['colour'], players=starters, formation=formation, tactics=tac_clean,
                takers=takers, captain=captain if any(str(p.id) == captain for p in starters) else '')
