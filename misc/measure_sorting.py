#!/usr/bin/env python3
"""Time every gallery sort through the real window on a copy of a library, and compare two runs.

A sort that is slow freezes the window, and a sort that is wrong silently shows galleries out of
place, and neither is visible to pytest or to the smoke tests, whose libraries hold a handful of
galleries. This loads a whole library through the real `AppWindow` offscreen, then for both tabs
times every name in `sortkeys.KEYS` in both directions and the re-sort a cleared search sets off,
and records the order each one produced.

    venv/Scripts/python.exe misc/measure_sorting.py run --db db/happypanda.db --out after.json
    venv/Scripts/python.exe misc/measure_sorting.py compare before.json after.json

`run` copies the database into a temporary directory and opens only the copy, so it never writes
to the file it was given. `--repo` points it at another tree's `version/` - a worktree at the
previous commit, say - which is how a change is measured against the code it replaces.

`compare` checks the two runs position by position on the **value** each gallery compared as, not
on its id: galleries that compare equal keep whatever order they were shown in before, so an id
comparison reports differences that are only tie order. Values are stored as short hashes, which
keeps a run on a large library small and still tells equal from unequal exactly.

Every figure is wall time on the GUI thread, which is the thread a slow sort freezes; `--limit`
makes the exit code fail when any sort or cleared search takes longer. It defaults to the five
seconds after which Windows reports a window as not responding. Each name is sorted right after
the previous name's search was cleared, and the first sort after a cleared search costs more than
the same sort does on its own, so these figures are not interchangeable with ones taken in another
order.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Matches nothing, so the search hides every gallery and clearing it brings every one back.
NO_MATCH = 'zzqqxx-measure-sorting-matches-nothing'


def fingerprint(value):
    return hashlib.blake2b(repr(value).encode('utf-8'), digest_size=6).hexdigest()


def run(args):
    source = os.path.abspath(args.db)
    out = os.path.abspath(args.out)
    tree = os.path.abspath(args.repo)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    sys.path.insert(0, tree)
    sys.path.insert(0, os.path.join(tree, 'version'))
    # Before importing settings: it resolves settings.ini and the database against the working
    # directory on import.
    workdir = tempfile.mkdtemp(prefix='happypanda-sorting-')
    os.makedirs(os.path.join(workdir, 'db'))
    shutil.copy2(source, os.path.join(workdir, 'db', 'happypanda.db'))
    os.chdir(workdir)

    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtCore import Qt, QElapsedTimer

    qapp = QApplication(sys.argv)

    import database
    import app
    import app_constants
    import pewnet
    import sortkeys
    import utils

    utils.init_utils()
    app_constants.load_icons()
    app.AppWindow.check_site_logins = lambda self: None
    app.AppWindow._check_update = lambda self: None
    QMessageBox.exec = lambda self: QMessageBox.StandardButton.No
    pewnet.EHen.search = lambda self, query, **kwargs: {}
    pewnet.EHen.check_login = classmethod(lambda cls, cookies=None: False)
    app_constants.LOOK_NEW_GALLERY_STARTUP = False
    app_constants.ENABLE_MONITOR = False
    app_constants.SEARCHABLE_INBOX = True
    app_constants.CURRENT_SORT = 'title'  # a cheap startup sort, so the load is not what is timed
    database.db.DBBase._DB_CONN = database.db.init_db()

    def pump_until(predicate, what, timeout_ms=900_000):
        clock = QElapsedTimer()
        clock.start()
        while not predicate():
            if clock.elapsed() > timeout_ms:
                raise AssertionError('timed out waiting for %s' % what)
            qapp.processEvents()
        for _ in range(20):
            qapp.processEvents()

    done = []
    started = time.perf_counter()
    window = app.AppWindow(disable_excepthook=True)
    window.db_startup.DONE.connect(lambda: done.append(True))
    pump_until(lambda: done, 'the library to load')
    print('library loaded in %.1fs' % (time.perf_counter() - started), flush=True)

    orders = (Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder)
    result = {'db': source, 'repo': tree, 'sorts': {}, 'searches': {}}
    for tab, view in (('library', window.default_manga_view), ('inbox', window.addition_tab.view)):
        proxy, grid, model = view.sort_model, view.list_view, view.gallery_model
        result[tab + '_rows'] = proxy.rowCount()
        print('%s: %d galleries' % (tab, proxy.rowCount()), flush=True)
        for name in sortkeys.KEYS:
            for order in orders:
                descending = order == Qt.SortOrder.DescendingOrder
                began = time.perf_counter()
                grid.sort(name, order)
                took = time.perf_counter() - began
                galleries = [proxy.index(r, 0).data(Qt.ItemDataRole.UserRole + 1) for r in range(proxy.rowCount())]
                key = '%s %s/%s' % (tab, name, 'desc' if descending else 'asc')
                result['sorts'][key] = {
                    'seconds': round(took, 3),
                    'ids': [g.id for g in galleries],
                    'values': [fingerprint(sortkeys.sort_value(name, g, descending)) for g in galleries],
                }
                print('  %-26s %6.2fs' % (key, took), flush=True)

            refiltered = []
            mark = lambda: refiltered.append(time.perf_counter())
            proxy.ROWCOUNT_CHANGE.connect(mark)  # emitted by the connection after the re-filter
            try:
                grid.sort(name)
                for step, term in (('hide', NO_MATCH), ('clear', '')):
                    refiltered.clear()
                    began = time.perf_counter()
                    proxy.init_search(term)
                    pump_until(lambda: refiltered, 'the search to re-filter')
                    result['searches']['%s %s/%s' % (tab, name, step)] = round(refiltered[0] - began, 3)
            finally:
                proxy.ROWCOUNT_CHANGE.disconnect(mark)
            print('  %-26s %6.2fs' % ('%s %s/search cleared' % (tab, name),
                                      result['searches']['%s %s/clear' % (tab, name)]), flush=True)

    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f)
    print('written to %s' % out, flush=True)
    code = report_limit(result, args.limit)
    sys.stdout.flush()
    # Returning would free the window and its application while their threads still run, which
    # aborts the process and replaces the exit code --limit reports through.
    os._exit(code)


def report_limit(result, limit):
    timings = [(k, v['seconds']) for k, v in result['sorts'].items()]
    timings += [(k, v) for k, v in result['searches'].items() if k.endswith('/clear')]
    slowest = sorted(timings, key=lambda kv: -kv[1])[:5]
    print('\nslowest: ' + ', '.join('%s %.2fs' % kv for kv in slowest))
    over = [kv for kv in timings if limit and kv[1] > limit]
    for key, seconds in over:
        print('OVER %.1fs: %s %.2fs' % (limit, key, seconds))
    return 1 if over else 0


def compare(args):
    with open(args.before, 'r', encoding='utf-8') as f:
        before = json.load(f)['sorts']
    with open(args.after, 'r', encoding='utf-8') as f:
        after = json.load(f)['sorts']
    differing = 0
    for key in sorted(set(before) | set(after)):
        if key not in before or key not in after:
            print('%-26s only in %s' % (key, 'after' if key in after else 'before'))
            continue
        a, b = before[key], after[key]
        if sorted(a['ids']) != sorted(b['ids']):
            print('%-26s different galleries (%d before, %d after)' % (key, len(a['ids']), len(b['ids'])))
            differing += 1
            continue
        positions = [p for p, (x, y) in enumerate(zip(a['values'], b['values'])) if x != y]
        if positions:
            differing += 1
            first = positions[0]
            print('%-26s %d positions compare differently, first at %d (id %s before, %s after)'
                  % (key, len(positions), first, a['ids'][first], b['ids'][first]))
        else:
            print('%-26s same order   %6.2fs -> %6.2fs' % (key, a['seconds'], b['seconds']))
    print('\n%d of %d sorts differ' % (differing, len(set(before) & set(after))))
    return 1 if differing else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    measure = commands.add_parser('run', help='load a copy of a library and time every sort')
    measure.add_argument('--db', required=True, help='the database to copy and load')
    measure.add_argument('--out', required=True, help='where to write the json')
    measure.add_argument('--repo', default=REPO, help="the tree whose version/ is imported (default: this one)")
    measure.add_argument('--limit', type=float, default=5.0,
                         help='fail when a sort or cleared search takes longer, in seconds; 0 turns it off')
    check = commands.add_parser('compare', help='compare two runs by the value each position compared as')
    check.add_argument('before')
    check.add_argument('after')
    args = parser.parse_args()
    if args.command == 'compare':
        sys.exit(compare(args))
    run(args)


if __name__ == '__main__':
    main()
