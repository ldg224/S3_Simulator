// Runs the Python match engine (hcl_sim) inside the browser with Pyodide.
// Used by index.html when it's served as a static site (GitHub Pages). It loads the
// real engine files from this site, so there's only one copy of the engine.

importScripts('https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.js');

const ENGINE_FILES = ['__init__', 'config', 'geometry', 'physics', 'models', 'ratings', 'tactics',
  'decisions', 'engine', 'output', 'validate', 'teams', 'sheet', 'run'];

const BRIDGE = `
import sys, json, random
sys.path.insert(0, '/home/pyodide')
import js
from hcl_sim import sheet
from hcl_sim.run import simulate, summarise_match, match_seed
from hcl_sim.validate import validate

LEAGUE = None

def set_league(texts_json):
    global LEAGUE
    LEAGUE = sheet.load_league(sheet.load_config(), texts=json.loads(texts_json))
    return json.dumps(sheet.league_info(LEAGUE))

def run_match(job, home, away, seed, info_json):
    info = json.loads(info_json)
    h = sheet.resolve_team(LEAGUE, home)
    a = sheet.resolve_team(LEAGUE, away)
    if h == a:
        raise ValueError('Pick two different teams')
    if seed in (None, ''):
        seed = match_seed(info['week'], h, a, info.get('date'), '') if info.get('week') else random.randrange(1, 2 ** 31)
    def progress(f):
        js.reportProgress(job, f)
    data = simulate(LEAGUE, h, a, seed=int(seed), info=info, on_progress=progress)
    summary = summarise_match(data, validate(data))
    return json.dumps({'summary': summary, 'data': data}, separators=(',', ':'))
`;

// Called from Python while a match runs.
self.reportProgress = (job, p) => postMessage({ type: 'progress', job, p });

let py;
const ready = (async () => {
  py = await loadPyodide();
  py.FS.mkdirTree('/home/pyodide/hcl_sim');
  await Promise.all(ENGINE_FILES.map(async f => {
    const res = await fetch(`hcl_sim/${f}.py`, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`Couldn't load engine file ${f}.py`);
    py.FS.writeFile(`/home/pyodide/hcl_sim/${f}.py`, await res.text());
  }));
  py.FS.writeFile('/home/pyodide/league.json', await (await fetch('league.json', { cache: 'no-cache' })).text());
  py.runPython(BRIDGE);
  postMessage({ type: 'ready' });
})();

function short(err) {
  const lines = String(err && err.message || err).trim().split('\n');
  return lines[lines.length - 1];
}

onmessage = async (e) => {
  const m = e.data;
  try {
    await ready;
    if (m.type === 'league') {
      const info = py.globals.get('set_league')(m.texts);
      postMessage({ type: 'league', id: m.id, info });
    } else if (m.type === 'simulate') {
      const out = py.globals.get('run_match')(m.job, m.home, m.away, m.seed ?? null, JSON.stringify(m.info || {}));
      postMessage({ type: 'result', job: m.job, payload: out });
    }
  } catch (err) {
    postMessage({ type: 'error', job: m.job, id: m.id, message: short(err) });
  }
};
