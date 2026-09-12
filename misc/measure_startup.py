#!/usr/bin/env python3
"""Time the application's startup from outside it, and record how long the window is frozen.

`Documentation/Design/QT6_STARTUP_REGRESSION.md` needs two acceptance figures that no gate inside
the repository can produce. Throughput is the four `Loading ...` timings the startup writes to
`happypanda.log`, **summed** - since S7 the loader hands each batch to the GUI thread and returns,
so the work lands in whichever phase is running when the event is delivered and no single line is
comparable on its own. Responsiveness is `IsHungAppWindow`, the call Explorer itself uses to
decide whether to paint "(Not Responding)"; asking it from a second process is the only way to get
an answer, because a timer inside the application measures its own event-queue backlog instead.

    venv/Scripts/python.exe misc/measure_startup.py legacy:HP_STARTUP_INSERT=legacy shipped

Each argument is a configuration: a label, optionally followed by a colon and the environment
variables that select it, so a change gated behind one can be measured against the code it
replaces. Configurations are **alternated** rather than run in blocks, which the design doc
requires: the machine drifts enough over an afternoon to swallow the effect being measured.

Two Windows facts the script exists to get right, each of which silently produced a wrong answer
first. `venv/Scripts/python.exe` is a redirector, so the process it starts owns the window and the
pid `Popen` returns matches nothing - the window is found by title instead, and the run is ended
with `taskkill /T` so the descendant does not outlive the probe and load the database underneath
the next run.
"""
import argparse
import ctypes
import ctypes.wintypes as w
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_EXE = os.path.join(REPO, 'venv', 'Scripts', 'python.exe')
LOG = os.path.join(REPO, 'happypanda.log')
WINDOW_TITLE = 'Happypanda'
POLL = 0.25
PHASES = ('galleries', 'chapters', 'tags', 'hashes')
PHASE_RE = re.compile(r'startup \(Loading (\w+)\): ([\d.]+)s')
# The last phase to be timed, so its line is what says a startup has finished. Waiting for the
# process instead would add the ~90s of thumbnail and scan work that follows it.
LAST_PHASE = 'Loading hashes'
# Read back with no BOM handling: this is the RotatingFileHandler's own utf-8 output.
LOG_ENCODING = 'utf-8'
COMPETING = ('look new gallery startup', 'enable monitor')

if sys.platform != 'win32':
    sys.exit('measure_startup.py needs IsHungAppWindow, which is Windows only')

user32 = ctypes.windll.user32
user32.IsHungAppWindow.argtypes = [w.HWND]
user32.IsHungAppWindow.restype = w.BOOL
user32.IsWindowVisible.argtypes = [w.HWND]
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
ENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)


def app_windows():
    """Returns the handles of every visible top-level window titled exactly `Happypanda`."""
    found = []

    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 2)
            user32.GetWindowTextW(hwnd, title, length + 2)
            if title.value == WINDOW_TITLE:
                found.append(hwnd)
        return True

    user32.EnumWindows(ENUMPROC(visit), 0)
    return found


def log_since(offset):
    """Returns what the log has gained since `offset`, or all of it if it rotated meanwhile."""
    try:
        if os.path.getsize(LOG) < offset:
            offset = 0
        with open(LOG, 'r', encoding=LOG_ENCODING, errors='replace') as f:
            f.seek(offset)
            return f.read()
    except OSError:
        return ''


def warn_about_competing_settings():
    """Names any setting left on that would have the run scanning the library while it is timed."""
    ini = os.path.join(REPO, 'settings.ini')
    if not os.path.exists(ini):
        return
    with open(ini, 'r', encoding='utf-8-sig', errors='replace') as f:
        body = f.read().lower()
    on = [k for k in COMPETING if '%s = true' % k in body]
    if on:
        print('warning: %s still on in settings.ini; the run will not be comparable'
              % ' and '.join(on))


def parse_config(text):
    label, _, assignments = text.partition(':')
    env = {}
    for pair in assignments.split(',') if assignments else []:
        name, _, value = pair.partition('=')
        env[name.strip()] = value.strip()
    return label, env


def measure(label, env, timeout):
    """Runs one startup to completion and returns its phase timings and hung-window figures."""
    if app_windows():
        sys.exit('a Happypanda window is already open; the probe would poll that one')

    start = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    launched = subprocess.Popen([PY_EXE, os.path.join(REPO, 'version', 'main.py')],
                                cwd=REPO, env={**os.environ, **env},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    hung_total = hung_streak = hung_longest = 0.0
    windows = []
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        time.sleep(POLL)
        if not windows:
            windows = app_windows()
        if windows and any(user32.IsHungAppWindow(h) for h in windows):
            hung_total += POLL
            hung_streak += POLL
            hung_longest = max(hung_longest, hung_streak)
        else:
            hung_streak = 0.0
        if LAST_PHASE in log_since(start):
            break

    subprocess.run(['taskkill', '/T', '/F', '/PID', str(launched.pid)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    launched.wait()
    for _ in range(int(10 / POLL)):
        if not app_windows():
            break
        time.sleep(POLL)

    timings = {k: float(v) for k, v in PHASE_RE.findall(log_since(start))}
    return {'label': label, 'phases': timings, 'total': sum(timings.get(p, 0.0) for p in PHASES),
            'complete': len(timings) == len(PHASES), 'windows': len(windows),
            'hung_total': hung_total, 'hung_longest': hung_longest}


def report(run):
    phases = ' '.join('%s=%s' % (p, ('%.1f' % run['phases'][p]) if p in run['phases'] else '-')
                      for p in PHASES)
    print('%-12s %s total=%6.1f hung=%6.1f longest=%6.1f%s'
          % (run['label'], phases, run['total'], run['hung_total'], run['hung_longest'],
             '' if run['complete'] else '  INCOMPLETE'))
    sys.stdout.flush()


def summarise(runs):
    print('\n%-12s %5s %8s %8s %8s' % ('config', 'runs', 'total', 'hung', 'longest'))
    for label in dict.fromkeys(r['label'] for r in runs):
        got = [r for r in runs if r['label'] == label and r['complete']]
        if not got:
            print('%-12s %5d  no complete run' % (label, 0))
            continue
        print('%-12s %5d %8.1f %8.1f %8.1f'
              % (label, len(got), sum(r['total'] for r in got) / len(got),
                 sum(r['hung_total'] for r in got) / len(got),
                 sum(r['hung_longest'] for r in got) / len(got)))
    print('\nCompare the totals as a ratio; seconds depend on the machine and on the library.')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('config', nargs='*', default=['shipped'], metavar='LABEL[:VAR=VAL,...]',
                        help='a configuration to measure; repeat it to compare two')
    parser.add_argument('--runs', type=int, default=3,
                        help='runs per configuration (default 3, the design doc minimum)')
    parser.add_argument('--timeout', type=float, default=420,
                        help='seconds to wait for one startup to reach its last phase')
    args = parser.parse_args()

    if not os.path.exists(PY_EXE):
        sys.exit('no interpreter at %s' % PY_EXE)
    warn_about_competing_settings()

    configs = [parse_config(c) for c in args.config]
    runs = []
    for _ in range(args.runs):
        for label, env in configs:
            runs.append(measure(label, env, args.timeout))
            report(runs[-1])
    summarise(runs)


if __name__ == '__main__':
    main()
