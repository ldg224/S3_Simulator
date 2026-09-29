"""Local web app:  python -m hcl_sim app

Serves a page at http://localhost:8000 for simulating matches and weeks, watching
replays and downloading match files. Everything runs on this computer; matches are
saved in the matches/ folder.
"""

import csv
import gzip
import io
import json
import os
import random
import threading
import time
import traceback
import uuid
import webbrowser
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from multiprocessing import Manager
from urllib.parse import parse_qs, urlparse

from . import sheet
from .run import match_seed, results_rows, simulate, summarise_match, write_match
from .validate import validate

MATCH_DIR = os.path.join(sheet.ROOT, 'matches')
PAGE = os.path.join(sheet.ROOT, 'index.html')   # the same page GitHub Pages serves


# ---------- work done in background processes ----------

def _run_match(league, home, away, seed, info, fname, progress, key):
    try:
        def cb(f):
            progress[key] = f
        data = simulate(league, home, away, seed=seed, info=info, on_progress=cb)
        rep = validate(data)
        path = os.path.join(MATCH_DIR, fname)
        size = write_match(data, path)
        summ = summarise_match(data, rep, fname, size)
        with open(path[:-len('.json.gz')] + '.summary.json', 'w', encoding='utf-8') as f:
            json.dump(summ, f)
        progress[key] = 1.0
        return summ
    except Exception:
        progress[key] = -1.0
        raise


# ---------- app state ----------

class App:
    def __init__(self, offline=False, workers=None):
        self.offline = offline
        self.lock = threading.Lock()
        self.jobs = {}
        self.manager = Manager()
        self.progress = self.manager.dict()
        self.pool = ProcessPoolExecutor(max_workers=workers or max(1, min(6, (os.cpu_count() or 2) - 1)))
        self.league = None
        self.loaded_at = None
        self.load_error = None
        os.makedirs(MATCH_DIR, exist_ok=True)
        self.reload()

    def reload(self):
        try:
            self.league = sheet.load_league(sheet.load_config(), offline=self.offline)
            self.load_error = None
        except Exception as err:
            try:
                self.league = sheet.load_league(sheet.load_config(), offline=True)
                self.load_error = f'Using cached sheet ({err})'
            except Exception as err2:
                self.load_error = str(err2)
        self.loaded_at = datetime.now().isoformat(timespec='seconds')

    def league_info(self):
        info = sheet.league_info(self.league or {'teams': {}, 'players': {}, 'schedule': []})
        info.update(loaded_at=self.loaded_at, error=self.load_error, mode='server')
        return info

    def _new_job(self, kind, tasks, extra=None):
        job_id = uuid.uuid4().hex[:10]
        job = {'id': job_id, 'kind': kind, 'created': time.time(), 'tasks': tasks, 'results': [None] * len(tasks),
               'errors': [None] * len(tasks), 'done': 0, 'csv': None}
        job.update(extra or {})
        with self.lock:
            self.jobs[job_id] = job
        for i, t in enumerate(tasks):
            self.progress[t['key']] = 0.0
            fut = self.pool.submit(_run_match, self.league, t['home'], t['away'], t['seed'], t['info'], t['file'],
                                   self.progress, t['key'])
            fut.add_done_callback(lambda f, i=i, job=job: self._task_done(job, i, f))
        return job

    def _task_done(self, job, i, fut):
        with self.lock:
            try:
                job['results'][i] = fut.result()
            except Exception as err:
                job['errors'][i] = ''.join(traceback.format_exception_only(type(err), err)).strip()
            job['done'] += 1
            if job['kind'] == 'week' and job['done'] == len(job['tasks']) and all(job['results']):
                rows = results_rows([(t['fixture'], r) for t, r in zip(job['tasks'], job['results'])])
                name = f"week{job['week']}_results.csv"
                with open(os.path.join(MATCH_DIR, name), 'w', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerows(rows)
                job['csv'] = name

    def start_match(self, home, away, seed=None):
        L = self.league
        home = sheet.resolve_team(L, home)
        away = sheet.resolve_team(L, away)
        if home == away:
            raise ValueError('Pick two different teams')
        seed = int(seed) if seed not in (None, '') else random.randrange(1, 2 ** 31)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        task = {'key': uuid.uuid4().hex, 'home': home, 'away': away, 'seed': seed, 'info': {},
                'file': f'{stamp}_{home}_v_{away}_seed{seed}.json.gz', 'label': f'{home} v {away}'}
        return self._new_job('match', [task])

    def start_week(self, week):
        L = self.league
        fixtures = [r for r in L['schedule'] if (r.get('week') or '').strip() == str(week)]
        if not fixtures:
            raise ValueError(f'No fixtures for week {week}')
        tasks = []
        for fx in fixtures:
            h = sheet.resolve_team(L, fx['home'])
            a = sheet.resolve_team(L, fx['away'])
            seed = match_seed(week, h, a, fx.get('date'), '')
            tasks.append({'key': uuid.uuid4().hex, 'home': h, 'away': a, 'seed': seed, 'fixture': fx,
                          'info': {'week': week, 'date': fx.get('date'), 'time': fx.get('time')},
                          'file': f'week{week}_{h}_v_{a}.json.gz', 'label': f'{h} v {a}'})
        return self._new_job('week', tasks, {'week': week})

    def job_status(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            return {
                'id': job['id'], 'kind': job['kind'], 'week': job.get('week'), 'csv': job['csv'],
                'finished': job['done'] == len(job['tasks']),
                'tasks': [{'label': t['label'], 'progress': self.progress.get(t['key'], 0.0),
                           'result': r, 'error': e} for t, r, e in zip(job['tasks'], job['results'], job['errors'])],
            }

    def list_matches(self):
        out = []
        for name in os.listdir(MATCH_DIR):
            if name.endswith('.summary.json'):
                try:
                    with open(os.path.join(MATCH_DIR, name), encoding='utf-8') as f:
                        s = json.load(f)
                    if os.path.exists(os.path.join(MATCH_DIR, s['file'])):
                        out.append(s)
                except (OSError, ValueError, KeyError):
                    pass
        out.sort(key=lambda s: s.get('created', ''), reverse=True)
        csvs = sorted((n for n in os.listdir(MATCH_DIR) if n.endswith('_results.csv')), reverse=True)
        return {'matches': out, 'csv': csvs}


# ---------- HTTP ----------

def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype='application/json', headers=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get('Content-Length') or 0)
            return json.loads(self.rfile.read(n) or b'{}')

        def _safe_file(self, name):
            name = os.path.basename(name)
            path = os.path.join(MATCH_DIR, name)
            return path if os.path.isfile(path) else None

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            p = url.path
            if p in ('/', '/index.html'):
                with open(PAGE, 'rb') as f:
                    return self._send(200, f.read(), 'text/html; charset=utf-8')
            if p == '/api/league':
                return self._send(200, app.league_info())
            if p == '/api/matches':
                return self._send(200, app.list_matches())
            if p.startswith('/api/jobs/'):
                st = app.job_status(p.rsplit('/', 1)[1])
                return self._send(200, st) if st else self._send(404, {'error': 'no such job'})
            if p.startswith('/files/'):
                path = self._safe_file(p[len('/files/'):])
                if not path:
                    return self._send(404, {'error': 'not found'})
                name = os.path.basename(path)
                download = 'download' in q
                if name.endswith('.json.gz') and q.get('format') == ['json']:
                    with gzip.open(path, 'rb') as f:
                        body = f.read()
                    hdr = {'Content-Disposition': f'attachment; filename="{name[:-3]}"'} if download else {}
                    return self._send(200, body, 'application/json', hdr)
                with open(path, 'rb') as f:
                    body = f.read()
                ctype = 'text/csv' if name.endswith('.csv') else 'application/gzip'
                return self._send(200, body, ctype, {'Content-Disposition': f'attachment; filename="{name}"'})
            return self._send(404, {'error': 'not found'})

        def do_POST(self):
            p = urlparse(self.path).path
            try:
                data = self._body()
                if p == '/api/simulate':
                    job = app.start_match(data.get('home'), data.get('away'), data.get('seed'))
                    return self._send(200, {'job': job['id']})
                if p == '/api/week':
                    job = app.start_week(data.get('week'))
                    return self._send(200, {'job': job['id']})
                if p == '/api/reload':
                    app.reload()
                    return self._send(200, app.league_info())
                if p == '/api/delete':
                    path = self._safe_file(data.get('file', ''))
                    if path and path.endswith('.json.gz'):
                        os.remove(path)
                        side = path[:-len('.json.gz')] + '.summary.json'
                        if os.path.exists(side):
                            os.remove(side)
                    return self._send(200, {'ok': True})
            except (ValueError, KeyError) as err:
                return self._send(400, {'error': str(err).strip("'")})
            return self._send(404, {'error': 'not found'})

    return Handler


def serve(port=8000, offline=False, open_browser=True):
    app = App(offline=offline)
    server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(app))
    url = f'http://localhost:{port}/'
    print(f'HCL Simulator running at {url}  (Ctrl+C to stop)')
    if app.load_error:
        print(f'  note: {app.load_error}')
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping.')
    finally:
        server.server_close()
        app.pool.shutdown(cancel_futures=True)
