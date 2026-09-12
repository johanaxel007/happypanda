"""Headless smoke test for the application window's own methods.

`gui_smoke.py` drives individual widgets. This drives the real `AppWindow`, which is the only
place a menu action, a confirmation dialog, a worker thread and a notification are assembled
into one path - and nothing else covers that assembly at all. A method here can reference an
attribute that does not exist, connect a signal to a receiver on the wrong thread, or leave a
run permanently "already running", and every one of those is green under pytest and under
gui_smoke both.

    venv/Scripts/python.exe misc/app_smoke.py

Everything the window reaches is real except the network: the source's `search` and
`get_metadata` are replaced on `pewnet.EHen` itself, so the class identity every `isinstance`
check in the pipeline relies on is untouched. It runs in a temporary directory with a database
of its own, so neither the real library nor the repo's copies are opened.

`gui_smoke.py` stays the encoding gate rather than this one. Building the window loads the icon
font, and qtawesome opens its charmap without naming an encoding, so running this under
`-W error::EncodingWarning` fails inside a dependency before reaching anything of ours.
"""
import os
import sys
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'version'))
# Before importing settings: it resolves settings.ini against the working directory on import.
WORKDIR = tempfile.mkdtemp(prefix='happypanda-appsmoke-')
os.chdir(WORKDIR)


def say(msg):
    print(msg, flush=True)


from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from PyQt6.QtCore import Qt, QThread, QElapsedTimer  # noqa: E402

qapp = QApplication(sys.argv)

import database  # noqa: E402
import app  # noqa: E402
import app_constants  # noqa: E402
import betterversions  # noqa: E402
import fetch  # noqa: E402
import gallery  # noqa: E402
import gallerydb  # noqa: E402
import misc  # noqa: E402
import pewnet  # noqa: E402
import utils  # noqa: E402

utils.init_utils()
app_constants.load_icons()   # main.py does both before the window is built

# --- the network, and the two things construction would otherwise reach ---------------------

logins = []
app.AppWindow.check_site_logins = lambda self: logins.append('checked')
app.AppWindow._check_update = lambda self: logins.append('update')

# Every confirmation the window raises, and the answer it gets. A dialog nobody answers would
# block the harness forever, and which answer it got is half of what is being asserted.
dialogs = []
ANSWER = [QMessageBox.StandardButton.No]
QMessageBox.exec = lambda self: (dialogs.append(self.text()), ANSWER[0])[1]

searches = []
lookups = []
metadata_reply = [None]


def stub_search(self, query, **kwargs):
    searches.append((query, kwargs))
    return {}


def stub_get_metadata(self, urls, cookies=None):
    lookups.append(list(urls))
    return metadata_reply[0]


pewnet.EHen.search = stub_search
pewnet.EHen.get_metadata = stub_get_metadata
pewnet.EHen.check_login = classmethod(lambda cls, cookies=None: False)
pewnet.EHen.image_session = lambda self: object()

# Workers are created inside the window's own methods, so the harness has no handle on them.
# Wrapping the one function that starts them all gives it one, without the window knowing.
workers = []
_real_worker_thread = misc.worker_thread


def capturing_worker_thread(parent, worker, start_slot, finished_signal, name=''):
    workers.append((name, worker))
    return _real_worker_thread(parent, worker, start_slot, finished_signal, name)


misc.worker_thread = capturing_worker_thread
app.misc.worker_thread = capturing_worker_thread

app_constants.LOOK_NEW_GALLERY_STARTUP = False
app_constants.ENABLE_MONITOR = False
app_constants.DEFAULT_EHEN_URL = 'https://e-hentai.org/'
app_constants.GLOBAL_EHEN_LOCK = False

database.db.DBBase._DB_CONN = database.db.init_db()

# --- a library for the startup to load -----------------------------------------------------
# Without rows in `series` the startup loop never runs a single iteration, so every assertion
# about it would pass against code that never executed. Three galleries in the library and one
# in the inbox, because the batch is split by the view each gallery belongs to.
SEEDED = {app_constants.ViewType.Default: 3, app_constants.ViewType.Addition: 1}
for view_type, count in SEEDED.items():
    for n in range(count):
        seed = gallerydb.Gallery()
        seed.title = 'Seeded %s %d' % (view_type, n)
        seed.path = WORKDIR
        seed.view = view_type
        seed.profile = os.path.join(WORKDIR, 'seed.jpg')  # or add_gallery goes off to make one
        seed.chapters.create_chapter().path = WORKDIR  # a gallery with none is refused outright
        gallerydb.execute(gallerydb.GalleryDB.add_gallery, False, seed)

# The thread each insert really ran on, recorded from inside the model. Which thread mutates a
# model is the whole point of this path and is invisible to every other assertion here.
insert_threads = []
_real_insert_rows = gallery.GalleryModel.insertRows


def recording_insert_rows(self, position, rows, *args, **kwargs):
    insert_threads.append(QThread.currentThread())
    return _real_insert_rows(self, position, rows, *args, **kwargs)


gallery.GalleryModel.insertRows = recording_insert_rows

window = app.AppWindow(disable_excepthook=True)
assert logins == ['checked'], logins
say('step: the application window is up, with the network stubbed')


def pump_until(predicate, what, timeout_ms=20000):
    """Runs the event loop until `predicate` holds, so a worker thread can finish.

    The window hands its work to a QThread and reports back through signals, which only arrive
    while the loop is running - a plain sleep here would deadlock rather than wait.
    """
    clock = QElapsedTimer()
    clock.start()
    while not predicate():
        if clock.elapsed() > timeout_ms:
            raise AssertionError('timed out waiting for %s' % what)
        qapp.processEvents()
    qapp.processEvents()


# --- the startup filling the models ---------------------------------------------------------
# The library is read on a thread of its own and the models belong to the GUI thread, so each
# batch reaches them as a signal. Nothing else here reaches the startup at all: pytest builds
# no window, and gui_smoke builds no gallery model.

main_thread = QThread.currentThread()
library_view = window.default_manga_view
inbox_view = window.addition_tab.view

pump_until(lambda: library_view.gallery_model.rowCount() == SEEDED[app_constants.ViewType.Default]
           and inbox_view.gallery_model.rowCount() == SEEDED[app_constants.ViewType.Addition],
           'the startup to fill both models')

assert insert_threads, 'the startup inserted nothing at all'
assert all(t is main_thread for t in insert_threads), insert_threads
say('app: the startup reaches both views, and every insert runs on the gui thread')

# The delegate draws nothing until the phase that loaded what it draws has finished, and it
# calls update() on the view to say so, which is a widget call like any other.
assert library_view.list_view.manga_delegate._paint_level > 0, 'the grid was never told to draw'
say('app: the grid is let off its blank paint level once the galleries are in')


# --- rechecking the better version list ----------------------------------------------------
# The path with no coverage anywhere: a confirmation dialog, a worker on its own thread, a
# button that doubles as the stop control, and a notification that has to distinguish "nothing
# was wrong" from "nothing could be judged".

held = gallerydb.Gallery()
held.id, held.title, held.path = 4242, 'Pink Archive', WORKDIR
held.link = 'https://e-hentai.org/g/50/held/'
held.tags = {'Artist': ['unacchi'], 'Parody': ['blue archive'], 'Other': ['mosaic censorship']}
app_constants.GALLERY_DATA = [held]
app_constants.GALLERY_ADDITION_DATA = []

WRONG = 'https://e-hentai.org/g/90/wrong/'
RIGHT = 'https://e-hentai.org/g/91/right/'
store = betterversions.shared_store()
for url in (WRONG, RIGHT):
    store.add(betterversions.BetterVersion(
        series_id=held.id, url=url, title='Pink Archive', held_title=held.title,
        kinds=(betterversions.KIND_DECENSORED,), source=betterversions.SOURCE_SCAN))

dialogs.clear()
ANSWER[0] = QMessageBox.StandardButton.No
window.recheck_better_versions()
assert len(dialogs) == 1 and 'Re-judge the 2 row(s)' in dialogs[0], dialogs
assert '1 request(s)' in dialogs[0], dialogs[0]
assert workers == [], 'answering No still started a worker'
assert len(store.rows()) == 2, 'answering No changed the list'
say('app: the recheck asks first, states the exact request count, and No does nothing')

metadata_reply[0] = ({'gmetadata': [
    {'gid': 0, 'title_jpn': '', 'thumb': '',
     'tags': ['artist:alpha91', 'parody:blue_archive', 'other:uncensored']},
    {'gid': 1, 'title_jpn': '', 'thumb': '',
     'tags': ['artist:unacchi', 'parody:blue_archive', 'other:uncensored']},
]}, {0: WRONG, 1: RIGHT})

dialogs.clear()
lookups.clear()
ANSWER[0] = QMessageBox.StandardButton.Yes
window.recheck_better_versions()
assert window._better_version_recheck is not None, 'Yes did not start a recheck'
assert window.better_versions_window.recheck_btn.text() == 'Stop rechecking'
assert [name for name, _ in workers] == ['App.recheck_better_versions'], workers

# Connected the same way the window connects its own `done`: a plain closure, from this thread.
slot_threads = []
main_thread = QThread.currentThread()
workers[0][1].FINISHED.connect(lambda *_: slot_threads.append(QThread.currentThread()))

pump_until(lambda: window._better_version_recheck is None, 'the recheck to finish')

assert lookups == [[WRONG, RIGHT]], lookups
# The window connects a plain closure, not a bound method, to a signal a worker thread emits -
# and that closure then touches widgets. A closure has no thread affinity of its own, so what
# makes it safe is where connect() was called; this pins that rather than assuming it.
assert slot_threads and all(t is main_thread for t in slot_threads), slot_threads
assert {r.url for r in store.rows()} == {RIGHT}, [r.url for r in store.rows()]
assert searches == [], 'the recheck searched for a candidate it already had'
say('app: Yes runs it on a worker thread, drops the row by another artist, keeps the other')
say('app: the closure the window connects to that worker really runs on the gui thread')

# The button has to come back, or one run disables the only way to start another.
import io_misc  # noqa: E402
assert window.better_versions_window.recheck_btn.text() == io_misc.RECHECK_LABEL, \
    window.better_versions_window.recheck_btn.text()
assert app_constants.GLOBAL_EHEN_LOCK is False, 'the recheck kept the metadata lock'
say('app: the button goes back to starting a run, and the metadata lock is given back')

# A row whose gallery is not loaded is "no evidence", not "not the same work" - judging it here
# would empty the list during a startup that is still loading the library in batches.
store.restore(held.id, WRONG)
app_constants.GALLERY_DATA = []
dialogs.clear()
workers.clear()
window.recheck_better_versions()
pump_until(lambda: window._better_version_recheck is None, 'the second recheck to finish')
assert {r.url for r in store.rows()} == {WRONG, RIGHT}, [r.url for r in store.rows()]
say('app: with the library not loaded it dismisses nothing rather than emptying the list')
app_constants.GALLERY_DATA = [held]

# Two runs at once would double the requests and race on the same rows.
store.dismiss(held.id, WRONG)
window._better_version_recheck = object()
dialogs.clear()
window.recheck_better_versions()
assert dialogs == [], 'a second recheck got as far as asking'
window._better_version_recheck = None
say('app: a recheck refuses to start while one is already running')

# A run that dies has to give the metadata lock back *before* it says it is done. The emit is
# queued to the gui thread, which may start the next run while this one is still unwinding -
# and that run's take_lock would then be cleared by this one's finally. Asserted through a
# direct connection so the slot runs at emit time on the worker thread: an auto connection
# here would be queued, and the test would pass or fail on timing rather than on ordering.
lock_at_emit = []
failing = betterversions.BetterVersionRecheck()
failing.galleries = [held]
failing.store = store
failing.FINISHED.connect(lambda *_: lock_at_emit.append(app_constants.GLOBAL_EHEN_LOCK),
                         Qt.ConnectionType.DirectConnection)
failing._recheck = lambda: (_ for _ in ()).throw(RuntimeError('forced'))
failing.take_lock()
assert app_constants.GLOBAL_EHEN_LOCK is True, 'take_lock did not claim it'
failing.recheck()
assert lock_at_emit == [False], \
    'the lock was still held when FINISHED was emitted: %s' % lock_at_emit
assert app_constants.GLOBAL_EHEN_LOCK is False
say('app: a run that fails gives the metadata lock back before it reports finished')


# --- a metadata fetch, end to end through the window ---------------------------------------
# What the queries actually look like by the time they leave the application. The filters are
# sent under the source's short namespaces, which is only safe because they were checked
# against live searches - so the form that goes out is worth pinning here.

fetched = gallerydb.Gallery()
fetched.id, fetched.title = 7, 'Coppelia Brothel'
fetched.path = os.path.join(WORKDIR, '[70 Nenshiki Yuukyuu Kikan (Ohagi-san)] Coppelia Brothel')
os.makedirs(fetched.path, exist_ok=True)
fetched.artist = '70 Nenshiki Yuukyuu Kikan (Ohagi-san)'
fetched.language = 'English'
fetched.link = ''
fetched.exed = False

searches.clear()
workers.clear()
app_constants.GLOBAL_EHEN_LOCK = False
window.get_metadata(fetched)
assert [name for name, _ in workers] == ['App.get_metadata'], workers
pump_until(lambda: app_constants.GLOBAL_EHEN_LOCK is False and searches,
           'the fetch to issue its queries')

queries = [q for q, _ in searches]
assert queries, 'the fetch issued no query at all'
assert any(' a:"70 nenshiki yuukyuu kikan (ohagi-san)"$' in q for q in queries), queries
assert any(' l:english$' in q for q in queries), queries
assert not any('artist:' in q or 'language:' in q for q in queries), \
    "the long namespaces belong to the app's own search box, not to a source query"
assert len(queries) <= fetch.MAX_SEARCH_ATTEMPTS, \
    'a gallery that matches nothing must stay inside the attempt budget: %s' % queries
say('app: a fetch sends a:/l: filters, and a gallery that matches nothing costs %d queries'
    % len(queries))

say('')
say('APP SMOKE OK')

