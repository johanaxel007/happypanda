"""Headless smoke test for the settings dialog and the gallery chooser.

Nothing else covers the GUI, and neither screen is reachable from pytest: the modules import
each other flatly and a dialog needs a QApplication. This drives the real widgets under the
offscreen platform, stubbing only the network, and asserts the things that fail silently - a
setting that does not survive Ok, a chooser that shows no cover, a signal that reaches into a
widget its own receiver has destroyed.

    venv/Scripts/python.exe misc/gui_smoke.py

It runs in a temporary directory of its own, so the settings.ini and scratch files it writes
never land beside the real ones - which also means it exercises the defaults the application
ships with rather than whichever local ini happens to be present.
"""
import os
import sys
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'version'))
# Before importing settings: it resolves settings.ini against the working directory on import.
os.chdir(tempfile.mkdtemp(prefix='happypanda-smoke-'))


def say(msg):
    print(msg, flush=True)


from PyQt5.QtWidgets import QApplication  # noqa: E402
from PyQt5.QtCore import QPoint, QEvent, Qt  # noqa: E402
from PyQt5.QtGui import QPixmap, QColor  # noqa: E402

qapp = QApplication(sys.argv)

import database  # noqa: E402,F401  (main.py imports this before app)
import app  # noqa: E402,F401      (breaks the gallery/app import cycle)
import app_constants  # noqa: E402
import gallerydb  # noqa: E402
import settings  # noqa: E402
import utils  # noqa: E402
import misc  # noqa: E402
import pewnet  # noqa: E402

utils.init_utils()  # main.py does this before any dialog is built
import settingsdialog  # noqa: E402
say('step: bootstrapped')

# --- settings round trip ------------------------------------------------------------------
d = settingsdialog.SettingsDialog()
assert d.filter_by_language.isChecked() is app_constants.FILTER_RESULTS_BY_LANGUAGE
assert d.picker_previews.isChecked() is app_constants.PICKER_PREVIEWS
assert d.better_version_language.currentText() == app_constants.BETTER_VERSION_LANGUAGE
# The shipped default, which this harness tests because it runs in a temp directory with no
# ini of its own. A near miss applied over your metadata is the failure with no undo, and the
# score distribution is bimodal enough that a high bar costs few correct matches.
assert d.fuzz_confidence_threshold.value() == 95, d.fuzz_confidence_threshold.value()
say('restore_options: filter=%s previews=%s better version=%s'
    % (d.filter_by_language.isChecked(), d.picker_previews.isChecked(),
       d.better_version_language.currentText()))

# The source tags a language only when a gallery has been translated into it, so neither of
# these can ever appear on a candidate and offering them would be a setting that finds nothing.
offered = [d.better_version_language.itemText(i) for i in range(d.better_version_language.count())]
assert 'Japanese' not in offered and 'Other' not in offered, offered
say('settings: the better version language offers only languages a candidate can carry: %s' % offered)

d.filter_by_language.setChecked(False)
d.picker_previews.setChecked(False)
d.better_version_language.setCurrentText('Chinese')
d.accept()
assert app_constants.FILTER_RESULTS_BY_LANGUAGE is False, 'filter did not survive accept()'
assert app_constants.PICKER_PREVIEWS is False, 'previews did not survive accept()'
assert app_constants.BETTER_VERSION_LANGUAGE == 'Chinese', 'language did not survive accept()'
assert settings.get(True, 'Web', 'filter results by language', bool) is False
assert settings.get(True, 'Web', 'picker previews', bool) is False
assert settings.get('English', 'Web', 'better version language', str) == 'Chinese'

d2 = settingsdialog.SettingsDialog()
assert d2.filter_by_language.isChecked() is False
assert d2.picker_previews.isChecked() is False
assert d2.better_version_language.currentText() == 'Chinese', 'the language latched to its default'
say('settings: all three round trip through accept() into a reopened dialog')

# A stored language the combo does not list still has to come back out of it, or the next Ok
# silently writes whichever entry happened to be first instead.
app_constants.BETTER_VERSION_LANGUAGE = 'Portuguese'
d3 = settingsdialog.SettingsDialog()
assert d3.better_version_language.currentText() == 'Portuguese'
d3.accept()
assert app_constants.BETTER_VERSION_LANGUAGE == 'Portuguese', 'an unlisted language was lost'
say('settings: a language the combo does not list survives a save rather than being replaced')

# --- the ini is UTF-8 whatever the system locale is -----------------------------------------
# A frozen build never enables UTF-8 mode however the environment is set, so without an
# explicit encoding the exe and a source run store a non-ASCII path differently.
JP = 'D:/\u6f2b\u753b/\u30e9\u30a4\u30d6\u30e9\u30ea'
settings.set(JP, 'General', 'smoke path')
settings.config.save()
assert JP.encode('utf-8') in open(settings.settings_path, 'rb').read(), 'ini not written as UTF-8'

reread = settings.Config()
reread.read(settings.settings_path)
assert reread['General']['smoke path'] == JP, reread['General']['smoke path']
say('ini: a non-ASCII value round trips as UTF-8 whatever the locale encoding is')

legacy = os.path.join(os.getcwd(), 'legacy.ini')
with open(legacy, 'wb') as f:
    f.write(('[General]\nsmoke path = %s\n' % JP).encode('cp932'))
settings.locale.getencoding = lambda: 'cp932'  # so the case runs on a machine of any locale
migrated = settings.Config()
migrated.read(legacy)
assert migrated['General']['smoke path'] == JP, migrated['General']['smoke path']
assert migrated.legacy_encoding == 'cp932', migrated.legacy_encoding
assert JP.encode('utf-8') in open(legacy, 'rb').read(), 'the legacy ini was not rewritten'
say('ini: one left in the system locale is read and rewritten as UTF-8 rather than crashing')

# --- the picker ---------------------------------------------------------------------------
opened_paths = []
opened_links = []
misc.utils.open_path = lambda path, select='': opened_paths.append((path, select))
misc.utils.open_web_link = lambda url: opened_links.append(url)

gallery_dir = os.path.join(os.getcwd(), 'a gallery folder')
os.makedirs(gallery_dir, exist_ok=True)

g = gallerydb.Gallery()
g.title = 'Kimi to Boku no Natsu'
g.artist = 'Yamada'
g.path = gallery_dir

jp = '\u541b\u3068\u50d5\u306e\u590f'
URL_A, URL_B = 'https://e-hentai.org/g/1/a/', 'https://e-hentai.org/g/2/b/'
choices = [('[Yamada] Kimi to Boku no Natsu' + chr(10) + jp, URL_A),
           ('[Yamada] Kimi to Boku no Natsu [English]', URL_B)]
preview_session = object()
extras = {'position': (3, 27), 'thumbnails': {URL_A: 'https://ehgt.org/a.jpg'},
          'session': preview_session}

requested = []
connected_before_queueing = []


def stub_add_to_queue(item, session=None, dir=None):
    """Records what was queued, and whether its handler was connected before it was."""
    if isinstance(item, str):
        item = pewnet.DownloaderItem(item, session)
    # A worker can claim the item the moment it is queued, so a handler connected afterwards
    # can miss the signal entirely.
    connected_before_queueing.append(item.receivers(item.file_rdy) > 0)
    requested.append((item.download_url, item.session))
    return item


pewnet.Downloader.add_to_queue = staticmethod(stub_add_to_queue)
app_constants.DOWNLOAD_MANAGER = object()  # the real one is started by AppWindow

p = misc.SingleGalleryChoices(g, choices, 'Which gallery do you want to extract metadata from?',
                              None, extras)
assert p.list_w.count() == 2
labels = [w.text() for w in p.findChildren(misc.QLabel)]
assert any('Gallery 3 of 27 needing a choice.' in t for t in labels), labels
assert jp in p.list_w.item(0).text()
# A row with a tool tip of its own gets a second window over the card, on Qt's schedule.
assert not any(p.list_w.item(i).toolTip() for i in range(p.list_w.count()))
say('picker: position header and native title render, and no row carries a tool tip')

p.open_in_browser(p.list_w.item(1))
p.open_in_browser(QPoint(-5, -5))  # empty space
assert opened_links == [URL_B], opened_links
say('picker: a choice opens on the source site, empty space is a no-op')

# --- the local gallery, top left ------------------------------------------------------------
p.open_source_folder()
assert opened_paths == [(gallery_dir, '')], opened_paths
archive = os.path.join(gallery_dir, 'gallery.zip')
open(archive, 'w', encoding='utf-8').close()
g.path = archive
p.open_source_folder()
assert opened_paths[-1] == (gallery_dir, archive), opened_paths
say('picker: the local gallery opens its folder, an archive opens selected')

# --- the hover card -------------------------------------------------------------------------
p.show_preview(p.list_w.item(1))          # no thumbnail for this candidate
assert not p._preview_popup.isHidden(), 'the url and the hint are the card without a cover'
assert p._preview_url.text() == URL_B
assert p._preview_image.isHidden() and p._preview_separator.isHidden()
assert requested == [], 'must not fetch a cover it was never given'

p.show_preview(p.list_w.item(0))
assert requested == [('https://ehgt.org/a.jpg', preview_session)], requested
assert connected_before_queueing == [True], (
    'the cover handler must be connected before the item reaches the download queue')
assert p._preview_url.text() == URL_A
assert p._preview_image.isHidden(), 'no cover until the download lands'
p.show_preview(p.list_w.item(0))
assert len(requested) == 1, 'a second hover must not re-request'

cover = os.path.join(os.getcwd(), 'cover.png')
pm = QPixmap(400, 560)
pm.fill(QColor('red'))
pm.save(cover)

download = pewnet.DownloaderItem('https://ehgt.org/a.jpg')
download.file = cover
download.preview_for = URL_A
p._preview_downloaded(download)
assert not p._preview_popup.isHidden(), 'the cover should be on screen'
assert not p._preview_image.isHidden() and not p._preview_separator.isHidden()
assert p._preview_image.pixmap().width() == 200, p._preview_image.pixmap().width()
# One card, holding all three, is the whole point: no second window over the same spot.
card_text = [w.text() for w in p._preview_popup.findChildren(misc.QLabel) if w.text()]
assert URL_A in card_text and any('double click' in t for t in card_text), card_text
say('picker: one card carries the cover, the url and the hint, and the cover is scaled')

p.eventFilter(p.list_w.viewport(), QEvent(QEvent.Leave))
assert p._preview_popup.isHidden(), 'the card must go away when the cursor leaves the list'

p.show_preview(p.list_w.item(0))           # served from cache now
assert not p._preview_image.isHidden()
assert len(requested) == 1
say('picker: leaving the list hides the card, re-hovering reuses the cached cover')

# a cover that lands after the cursor moved on must not appear on another row's card
p.show_preview(p.list_w.item(1))
late = pewnet.DownloaderItem('https://ehgt.org/late.jpg')
late.file = cover
late.preview_for = URL_A
p._preview_downloaded(late)
assert p._preview_url.text() == URL_B, 'the card still describes the row under the cursor'
assert p._preview_image.isHidden(), 'a late cover must not appear on another row'
say('picker: a cover arriving after the cursor moved on is cached, not shown')

screen = misc.QDesktopWidget().availableGeometry(misc.QCursor.pos())
card = p._preview_popup.frameGeometry()
assert screen.contains(card), (card, screen)
say('picker: the card is placed inside the screen it is shown on')

# --- noting a better version from the picker ------------------------------------------------
# The action the whole feature came from: the chooser was already showing the better release
# with no way to say "not this one, but keep it in mind".
import betterversions  # noqa: E402

notified = []
app_constants.NOTIF_BAR = type('_Bar', (), {'add_text': lambda self, t, **kw: notified.append(t)})()

p.list_w.setCurrentRow(1)                  # the [English] release
assert g.id is None
p.note_better_version()
assert betterversions.shared_store().rows() == [], 'a gallery with no id has nothing to note for'
assert any('not in the library yet' in t for t in notified), notified
say('picker: a gallery that is not in the library yet is refused rather than stored')

g.id = 4242
notified.clear()
p.note_better_version()
rows = betterversions.shared_store().rows()
assert len(rows) == 1, rows
assert rows[0].url == URL_B and rows[0].series_id == 4242
assert rows[0].held_title == g.title
assert p.isVisible(), 'noting one must leave the dialog open: the real choice is still to make'
say('picker: noting the highlighted release stores it and leaves the choice outstanding')

notified.clear()
p.note_better_version()
assert len(betterversions.shared_store().rows()) == 1, 'noting the same one twice stored it twice'
assert any('already noted' in t for t in notified), notified

# The native title arrives appended to the label; it is the only form the owner of a Japanese
# folder name recognises, so it has to be kept apart rather than stored into the romaji field.
p.list_w.setCurrentRow(0)
p.note_better_version()
noted = {r.url: r for r in betterversions.shared_store().rows()}
assert noted[URL_A].native_title == jp, noted[URL_A]
assert chr(10) not in noted[URL_A].title, noted[URL_A].title
say('picker: a labelled choice keeps its native title in its own field')

p.close()
assert p._preview_popup.isHidden()
say('picker: closing the dialog takes the card with it')

# --- a showcase whose receiver destroys it ---------------------------------------------------
# The failed-galleries popup crashed here: mouseDoubleClickEvent touched the widget after
# emitting, and the widget carries WA_DeleteOnClose, so by then it could already be gone.
import sip  # noqa: E402
from PyQt5.QtCore import QEvent as _QEvent  # noqa: E402
from PyQt5.QtGui import QMouseEvent  # noqa: E402

showcase = misc.GalleryShowcaseWidget()
showcase.set_gallery(g, (100, 100))
showcase.double_clicked.connect(lambda _gal: sip.delete(showcase))

click = QMouseEvent(_QEvent.MouseButtonDblClick, QPoint(5, 5), Qt.LeftButton, Qt.LeftButton,
                    Qt.NoModifier)
showcase.mouseDoubleClickEvent(click)   # must not raise RuntimeError
assert sip.isdeleted(showcase), 'the receiver was supposed to delete it'
say('showcase: a double click whose receiver destroys the widget no longer crashes')

# --- switching tabs while the library is in table mode ----------------------------------------
# restore_search_term dismissed the grid view's hover window without checking which view was
# showing, so every tab switch raised AttributeError in table mode. Only the grid view has one,
# and this is the fact that guard depends on.
import gallery  # noqa: E402

assert not hasattr(gallery.MangaTableView, 'gallery_window'), (
    'MangaTableView has grown a gallery_window: the isinstance guard in '
    'app.restore_search_term is now either wrong or hiding something')
say('views: the table view still has no hover window, which is what the tab switch guard assumes')

# --- the guards in front of the bulk removal ---------------------------------------------------
# Every gallery on a drive that was not mounted at startup reads as deleted, so the two paths that
# refuse are the whole safety of the feature, and a normal run reaches neither. Nothing here
# answers Yes: the deletion itself would need the database thread.
import string  # noqa: E402
from PyQt5.QtWidgets import QMessageBox  # noqa: E402

shown = []


def record_exec(self):
    shown.append(self.text())
    return QMessageBox.No


QMessageBox.exec = record_exec
app_constants.NOTIF_BAR = type('_Bar', (), {'add_text': lambda self, t, **kw: shown.append(t)})()

missing_drive = next((l + ':' for l in reversed(string.ascii_uppercase)
                      if not os.path.exists(l + ':' + os.sep)), None)


def a_view(paths):
    galleries = []
    for p in paths:
        g = gallerydb.Gallery()
        g.title, g.path = os.path.basename(p), p
        galleries.append(g)
    # the table view, because the grid's delegate builds its file icons out of the database
    view = gallery.MangaTableView(app_constants.ViewType.Default)
    view.gallery_model = gallery.GalleryModel(galleries, None)
    view.sort_model = gallery.SortFilterModel(view)
    view.sort_model.change_model(view.gallery_model)
    view.setModel(view.sort_model)
    return view


here = os.getcwd()
os.mkdir(os.path.join(here, 'still-here'))
view = a_view([os.path.join(here, 'still-here')])
shown.clear()
gallery.CommonView.remove_missing_source(view)
assert len(shown) == 1 and 'No galleries' in shown[0], shown
assert view.gallery_model.rowCount() == 1
say('bulk removal: a library whose sources are all present asks nothing')

if missing_drive:
    view = a_view([os.path.join(missing_drive + os.sep, 'Manga', str(n)) for n in range(4)])
    shown.clear()
    gallery.CommonView.remove_missing_source(view)
    assert len(shown) == 1 and missing_drive in shown[0], shown
    assert view.gallery_model.rowCount() == 4, 'an unreachable drive must remove nothing'
    say('bulk removal: an unreachable drive is refused by name, not counted for deletion')

view = a_view([os.path.join(here, 'gone-%d' % n) for n in range(4)])
shown.clear()
gallery.CommonView.remove_missing_source(view)
assert len(shown) == 1 and 'Remove 4 of 4' in shown[0], shown
assert 'most of this tab' in shown[0], 'the share warning did not fire on a whole dead library'
assert view.gallery_model.rowCount() == 4, 'answering No must remove nothing'
say('bulk removal: a wholly dead library states the count and warns, and No removes nothing')

# --- the better versions review list ----------------------------------------------------------
# A window rather than a library tab, because every row is a pair and the candidate is not a
# gallery. Nothing in here writes to the library, so what has to hold is that the rows survive,
# that a dismissed one stays dismissed, and that a row whose gallery is gone disappears.
import io_misc  # noqa: E402

app_constants.GALLERY_DATA = [g]      # g.id is 4242, which the picker rows above belong to
app_constants.GALLERY_ADDITION_DATA = []

window = io_misc.BetterVersionsWindow(None)
window.reload()
assert window.better_versions_list.rowCount() == 2, window.better_versions_list.rowCount()
say('review list: %d row(s) loaded from the store' % window.better_versions_list.rowCount())

listed = window.better_versions_list
first = listed.item(0, listed.HELD).data(Qt.UserRole + 1)
listed._dismiss(listed.model().index(0, 0), first)
assert listed.rowCount() == 1, 'dismissing a row left it on screen'
window.reload()
assert listed.rowCount() == 1, 'a dismissed row came back on the next load'
say('review list: "not interested" removes a row for good, not just for this session')

opened_links.clear()
remaining = listed.item(0, listed.HELD).data(Qt.UserRole + 1)
listed._open_source(remaining)
assert opened_links == [remaining.url], opened_links
opened_paths.clear()
listed._open_folder(remaining)   # g.path is the archive the picker section left behind
assert opened_paths == [(gallery_dir, archive)], opened_paths
say('review list: a row opens the better version on the source and the held gallery on disk')

# Opening the window while the library is still loading must not be destructive. GALLERY_DATA
# is filled batch by batch, so mid-load the index is partial or empty - and a prune there would
# delete almost every row and its scan progress with no way back.
betterversions.shared_store().mark_scanned([4242])
app_constants.GALLERY_DATA = []       # as it is at the start of a real startup
window.reload()
assert len(betterversions.shared_store().rows(include_dismissed=True)) == 2, 'opening the window deleted rows'
assert betterversions.shared_store().scanned_ids() == {4242}, 'opening the window lost scan progress'
assert listed.rowCount() == 1, 'an orphan row should still render from its stored title'
say('review list: opening it against a partly loaded library deletes nothing')

assert betterversions.shared_store().prune(set()) == 0, 'an empty library must not prune'
assert len(betterversions.shared_store().rows(include_dismissed=True)) == 2
say('review list: pruning against an empty library is refused')

app_constants.GALLERY_DATA = [g]      # the load finished, and 4242 is still here
assert betterversions.shared_store().prune({g.id}) == 0
assert len(betterversions.shared_store().rows(include_dismissed=True)) == 2
app_constants.GALLERY_DATA = []
assert betterversions.shared_store().prune({9999}) == 1, 'a genuinely gone gallery was not pruned'
window.reload()
assert listed.rowCount() == 0
assert betterversions.shared_store().rows(include_dismissed=True) == []
assert betterversions.shared_store().scanned_ids() == set()
say('review list: an explicit prune against the whole library drops only what is really gone')

# --- the scan, against a stubbed source --------------------------------------------------------
# The real thing is hours of paced requests, so what is checked here is everything around them:
# which galleries are even searched for, that the expunged listing is skipped, and that a
# candidate is classified from the tags the source reports rather than from its title.
CENSORED = 'https://e-hentai.org/g/10/held/'
DECENSORED = 'https://e-hentai.org/g/11/dec/'
TRANSLATED = 'https://e-hentai.org/g/12/eng/'
SEQUEL = 'https://e-hentai.org/g/13/two/'


def a_gallery(gid, title, link, tags):
    gal = gallerydb.Gallery()
    gal.id, gal.title, gal.link, gal.tags = gid, title, link, tags
    gal.path = gallery_dir
    return gal


# The held gallery's own stored link is on the other host, which is the normal state for an
# exhentai account: the same gallery id served under a different domain.
held = a_gallery(1, 'Nekokan! Meshimase', 'https://exhentai.org/g/10/held/',
                 {'Other': ['mosaic censorship'], 'Female': ['schoolgirl uniform']})
done_already = a_gallery(2, 'Nothing Left To Find', 'https://e-hentai.org/g/20/x/',
                         {'Language': ['english', 'translated'], 'Other': ['uncensored']})
untagged = a_gallery(3, 'Never Fetched', 'https://e-hentai.org/g/30/y/', {})


class StubHen:
    """Answers one search with the whole family of releases, the way a real listing does."""

    def __init__(self):
        self.searches = []
        self.lookups = []

    def search(self, query, **kwargs):
        self.searches.append((query, kwargs))
        return {query: [
            ('[Awa] Nekokan! Meshimase', CENSORED),                                # itself
            ('[Awa] Nekokan! Meshimase [Decensored]', DECENSORED),
            ('[Awa] Nekokan! Meshimase | Canned Catfood! Please Try It [English]', TRANSLATED),
            ('[Awa] Nekokan! Meshimase 2 [English]', SEQUEL),                      # a sequel
        ]}

    def get_metadata(self, urls):
        self.lookups.append(list(urls))
        tags = {DECENSORED: ['other:uncensored'],
                TRANSLATED: ['language:english', 'language:translated']}
        gid_to_url = {i: u for i, u in enumerate(urls)}
        return ({'gmetadata': [{'gid': i, 'tags': tags.get(u, []), 'title_jpn': '',
                                'thumb': 'https://ehgt.org/%d.jpg' % i}
                               for i, u in enumerate(urls)]}, gid_to_url)


scan_store = betterversions.BetterVersionStore(os.path.join(os.getcwd(), 'scan-store.db'))
stub = StubHen()
app_constants.GLOBAL_EHEN_LOCK = False
app_constants.BETTER_VERSION_LANGUAGE = 'English'

scan = betterversions.BetterVersionScan()
scan.galleries = [held, done_already, untagged]
scan.store = scan_store
scan._make_hen = lambda: stub

finished = []
found_rows = []
scan.FOUND.connect(found_rows.append)
scan.FINISHED.connect(finished.append)
scan.scan()

assert len(stub.searches) == 1, 'only the gallery with something to find may cost a request'
query, kwargs = stub.searches[0]
assert query == '"Nekokan! Meshimase"', query
assert kwargs.get('expunged') is False, 'the expunged listing holds deleted galleries only'
say('scan: 1 of 3 galleries was searched for, on the romaji half alone, expunged skipped')

assert app_constants.GLOBAL_EHEN_LOCK is False, 'the scan kept the metadata lock'
assert finished == [2], finished
by_url = {r.url: r for r in found_rows}
assert set(by_url) == {DECENSORED, TRANSLATED}, sorted(by_url)
assert by_url[DECENSORED].kinds == (betterversions.KIND_DECENSORED,)
assert by_url[TRANSLATED].kinds == (betterversions.KIND_TRANSLATED,)
assert by_url[TRANSLATED].thumb_url.startswith('https://ehgt.org/')
say('scan: the held gallery, the sequel and an unclassifiable hit are all left out')

# The gallery itself has to be dropped before the batch, not just fail to classify: its
# stored link is on the other host, so only the gallery id tells the two strings apart.
looked_up = [u for batch in stub.lookups for u in batch]
assert CENSORED not in looked_up, looked_up
assert SEQUEL not in looked_up, 'the numbering guard let a sequel into the lookup'
say('scan: the gallery itself costs no lookup even though its link is on the other host')

# Only the gallery actually searched for is recorded. A gallery the tag filter skipped must
# stay unrecorded, or it could never become eligible again after a metadata re-fetch changed
# its tags or the target language changed.
assert scan_store.scanned_ids() == {1}, scan_store.scanned_ids()
say('scan: only a gallery that was really searched for is recorded as scanned')

stub.searches.clear()
again = betterversions.BetterVersionScan()
again.galleries = [held, done_already, untagged]
again.store = scan_store
again._make_hen = lambda: stub
again.scan()
assert stub.searches == [], 'a second scan re-searched galleries it had already covered'
say('scan: a re-run skips what it has already searched for, so a stopped run resumes')

# A batch whose lookup never happened must leave its galleries unscanned, or the candidates are
# dropped with nothing recording that they were missed.
class FailingLookupHen(StubHen):
    def get_metadata(self, urls):
        self.lookups.append(list(urls))
        return 'error'


failing_store = betterversions.BetterVersionStore(os.path.join(os.getcwd(), 'failing.db'))
failing = betterversions.BetterVersionScan()
failing.galleries = [held]
failing.store = failing_store
failing._make_hen = lambda: FailingLookupHen()
app_constants.GLOBAL_EHEN_LOCK = False
failing.scan()
assert failing_store.scanned_ids() == set(), 'a gallery whose lookup failed was marked scanned'
assert failing_store.rows() == []
say('scan: a failed candidate lookup leaves the gallery to be searched again')


# But a candidate the api answers for with an error is a removed gallery, not a failed request:
# waiting for it to resolve would re-search its holder on every run forever.
class GoneCandidateHen(StubHen):
    def get_metadata(self, urls):
        self.lookups.append(list(urls))
        entries = []
        for i, u in enumerate(urls):
            if u == DECENSORED:
                entries.append({'gid': i, 'error': 'Key mismatch'})
            else:
                entries.append({'gid': i, 'tags': ['language:english', 'language:translated'],
                                'title_jpn': '', 'thumb': ''})
        return ({'gmetadata': entries}, {i: u for i, u in enumerate(urls)})


gone_store = betterversions.BetterVersionStore(os.path.join(os.getcwd(), 'gone.db'))
gone = betterversions.BetterVersionScan()
gone.galleries = [held]
gone.store = gone_store
gone._make_hen = lambda: GoneCandidateHen()
app_constants.GLOBAL_EHEN_LOCK = False
gone.scan()
assert gone_store.scanned_ids() == {held.id}, 'a removed candidate must not block the gallery forever'
assert [r.url for r in gone_store.rows()] == [TRANSLATED]
say('scan: a candidate the source reports as gone still counts as looked up')
failing_store.close()
gone_store.close()

# A refused search stops the run, but the searches already paid for must still be classified,
# and the run must not report itself as a finished one.
class RefusingHen(StubHen):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def search(self, query, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return super().search(query, **kwargs)
        self.searches.append((query, kwargs))
        return 'error'


abort_store = betterversions.BetterVersionStore(os.path.join(os.getcwd(), 'abort.db'))
second = a_gallery(9, 'Nekokan! Meshimase', 'https://exhentai.org/g/90/second/',
                   {'Other': ['mosaic censorship']})
refusing = betterversions.BetterVersionScan()
refusing.galleries = [held, second]
refusing.store = abort_store
refusing._make_hen = lambda: RefusingHen()
app_constants.GLOBAL_EHEN_LOCK = False
refusing.scan()
assert refusing.aborted is True, 'a refused search must mark the run as stopped early'
assert [r.url for r in abort_store.rows()], (
    'the first gallery was searched before the refusal, so its candidates must be classified '
    'rather than paid for again next run')
assert abort_store.scanned_ids() == {held.id}, abort_store.scanned_ids()
say('scan: a refused search still classifies what was already searched, and reports as stopped')
abort_store.close()

# The row a real run got wrong, end to end: an English gallery held censored, offered an
# uncensored release in Spanish. Nothing may be stored, and the log has to say what the
# candidate carried - that stage discards most of what a scan finds and is otherwise silent.
import logging  # noqa: E402

logged = []


class _Capture(logging.Handler):
    def emit(self, record):
        logged.append(record.getMessage())


_bv_log = logging.getLogger('betterversions')
_bv_log.addHandler(_Capture())
_bv_log.setLevel(logging.INFO)

SPANISH = 'https://exhentai.org/g/1166121/ebce29107f/'


class SpanishUncensoredHen(StubHen):
    def search(self, query, **kwargs):
        self.searches.append((query, kwargs))
        return {query: [('[WICKEDHEART (ZOOTAN)] Vanessa Customize | La Transformacion de '
                         'Vanessa (Danball Senki) [Spanish]', SPANISH)]}

    def get_metadata(self, urls):
        self.lookups.append(list(urls))
        return ({'gmetadata': [{'gid': 0, 'tags': ['language:spanish', 'language:translated',
                                                   'other:uncensored'],
                                'title_jpn': '', 'thumb': ''}]}, {0: urls[0]})


vanessa_store = betterversions.BetterVersionStore(os.path.join(os.getcwd(), 'vanessa.db'))
vanessa = a_gallery(77, 'Vanessa Customize (Danball Senki) {doujin-moe.us}',
                    'https://exhentai.org/g/770/held/',
                    {'Language': ['english', 'translated'], 'Other': ['full censorship']})
trade = betterversions.BetterVersionScan()
trade.galleries = [vanessa]
trade.store = vanessa_store
trade._make_hen = lambda: SpanishUncensoredHen()
app_constants.GLOBAL_EHEN_LOCK = False
logged.clear()
trade.scan()

assert vanessa_store.rows() == [], 'an uncensored release in another language is a trade'
rejections = [m for m in logged if 'candidate(s) rejected' in m]
assert rejections, logged[-6:]
assert any('spanish / uncensored' in m for m in logged), [m for m in logged if ' - ' in m]
assert any('english / censored' in m for m in rejections), rejections
say('scan: a decensored release in another language is rejected, and the log says what it held')
vanessa_store.close()

# The other row a real run got wrong: two unrelated works whose titles both reduce to
# 'Seishoku'. Only the parody tag separates them, and it is read qualified so an unqualified
# tag of the same name cannot stand in for it.
FGO = 'https://exhentai.org/g/4095569/b304277144/'


class OtherSeriesHen(StubHen):
    def search(self, query, **kwargs):
        self.searches.append((query, kwargs))
        return {query: [('[Ikameshi Shokudou (Ikameshi)] Seishoku (Fate/Grand Order) '
                         '[English] [Kuraudo] [Digital]', FGO)]}

    def get_metadata(self, urls):
        self.lookups.append(list(urls))
        return ({'gmetadata': [{'gid': 0, 'tags': ['parody:fate grand order',
                                                   'language:english', 'language:translated'],
                                'title_jpn': '', 'thumb': ''}]}, {0: urls[0]})


series_store = betterversions.BetterVersionStore(os.path.join(os.getcwd(), 'series.db'))
seishoku = a_gallery(88, 'Seishoku (Phantasy Star Online 2)',
                     'https://exhentai.org/g/880/held/',
                     {'Parody': ['phantasy star online 2'], 'Language': ['chinese'],
                      'Other': ['uncensored']})
wrong_series = betterversions.BetterVersionScan()
wrong_series.galleries = [seishoku]
wrong_series.store = series_store
wrong_series._make_hen = lambda: OtherSeriesHen()
app_constants.GLOBAL_EHEN_LOCK = False
logged.clear()
wrong_series.scan()

assert series_store.rows() == [], 'a different series is a different work'
assert wrong_series.found_new == 0
assert any('a different series' in m for m in logged), [m for m in logged if ' - ' in m]
assert any('phantasy star online 2' in m for m in logged), 'the held series must be named'
assert any('fate grand order' in m for m in logged), "the candidate's series must be named"
say('scan: two works sharing a short title are separated by their parody tag, and logged as such')
series_store.close()

# A run that turns up only rows already on the list must say so rather than report nothing:
# reporting on new rows alone made a re-scan look as though the earlier hits had gone away.
again_store = betterversions.BetterVersionStore(os.path.join(os.getcwd(), 'again.db'))
for _pass in range(2):
    repeat = betterversions.BetterVersionScan()
    repeat.galleries = [held]
    repeat.store = again_store
    repeat._make_hen = lambda: StubHen()
    app_constants.GLOBAL_EHEN_LOCK = False
    repeat.scan()
    if _pass == 0:
        assert (repeat.found_new, repeat.already_listed) == (2, 0), (
            repeat.found_new, repeat.already_listed)
        again_store.forget_scanned()      # as the window's button does, keeping the rows

assert (repeat.found_new, repeat.already_listed, repeat.already_dismissed) == (0, 2, 0), (
    repeat.found_new, repeat.already_listed, repeat.already_dismissed)
again_store.dismiss(held.id, DECENSORED)
again_store.forget_scanned()
third = betterversions.BetterVersionScan()
third.galleries = [held]
third.store = again_store
third._make_hen = lambda: StubHen()
app_constants.GLOBAL_EHEN_LOCK = False
third.scan()
assert (third.found_new, third.already_listed, third.already_dismissed) == (0, 1, 1), (
    third.found_new, third.already_listed, third.already_dismissed)
say('scan: a re-run reports what was already listed and dismissed instead of finding nothing')
again_store.close()
_bv_log.removeHandler(_bv_log.handlers[-1])

# The lock is claimed on the gui thread before the worker starts, so a fetch checking it in
# between refuses instead of running alongside.
lock_scan = betterversions.BetterVersionScan()
app_constants.GLOBAL_EHEN_LOCK = False
app_constants.USE_GLOBAL_EHEN_LOCK = True
lock_scan.take_lock()
assert app_constants.GLOBAL_EHEN_LOCK is True, 'the lock was not claimed before the thread started'
lock_scan.galleries = []
lock_scan.store = scan_store
lock_scan._make_hen = lambda: stub
lock_scan.scan()
assert app_constants.GLOBAL_EHEN_LOCK is False, 'the scan kept the lock it claimed'

untaken = betterversions.BetterVersionScan()
app_constants.USE_GLOBAL_EHEN_LOCK = False
app_constants.GLOBAL_EHEN_LOCK = True          # something else holds it
untaken.galleries = []
untaken.store = scan_store
untaken._make_hen = lambda: stub
untaken.scan()
assert app_constants.GLOBAL_EHEN_LOCK is True, 'the scan released a lock it never took'
app_constants.GLOBAL_EHEN_LOCK = False
say('scan: it releases only the metadata lock it claimed itself')

scan_store.forget_scanned()
cancelled = betterversions.BetterVersionScan()
cancelled.galleries = [held]
cancelled.store = scan_store
cancelled._make_hen = lambda: stub
cancelled.cancel()
cancelled.scan()
assert stub.searches == [], 'a cancelled scan still issued requests'
say('scan: a cancel before the first gallery issues no requests at all')
scan_store.close()

# --- the gallery context menu passes a selection to the scan -----------------------------------
# Starting the scan from the menu bar covers the whole tab, which is not what highlighting
# galleries first suggests. The context menu is the path that acts on exactly the selection, so
# what has to hold is that those galleries and no others reach the call.
scanned_with = []


class _StubAppWindow(misc.QWidget):     # GalleryMenu parents its QMenu to this
    def scan_better_versions(self, galleries=None):
        scanned_with.append(galleries)

    def get_metadata(self, gal=None):
        pass


menu_galleries = []
for n in range(3):
    mg = gallerydb.Gallery()
    mg.id, mg.title, mg.path = 100 + n, 'Menu gallery %d' % n, gallery_dir
    menu_galleries.append(mg)

menu_view = a_view([gallery_dir] * 3)
menu_view.gallery_model = gallery.GalleryModel(menu_galleries, None)
menu_view.sort_model.change_model(menu_view.gallery_model)
model = menu_view.gallery_model
picked = [model.index(r, 0) for r in (0, 2)]

app_constants.GALLERY_LISTS = set()
menu = misc.GalleryMenu(menu_view, model.index(0, 0), menu_view.sort_model,
                        _StubAppWindow(), picked)
labels = [a.text() for a in menu.findChildren(misc.QAction)]
assert 'Scan selected for better versions' in labels, labels

scan_act = next(a for a in menu.findChildren(misc.QAction)
                if a.text() == 'Scan selected for better versions')
scan_act.trigger()
assert len(scanned_with) == 1, scanned_with
assert [g.id for g in scanned_with[0]] == [100, 102], (
    'the context menu must hand over exactly the selected galleries')
say('context menu: "Scan selected for better versions" passes the selection and nothing else')

# How a selection is counted for the "that is not what this will scan" note. The grid view is
# the default and selects items rather than rows, which leaves selectedRows() empty however
# much is highlighted - so counting through it would silence the note exactly where it is
# needed. The grid view itself cannot be built here (its delegate reads the database), so the
# semantics are pinned on the widgets they come from.
from PyQt5.QtWidgets import QAbstractItemView, QListView, QTableView  # noqa: E402
from PyQt5.QtCore import QAbstractTableModel, QItemSelectionModel  # noqa: E402


class _Cols(QAbstractTableModel):
    def rowCount(self, p=None): return 3
    def columnCount(self, p=None): return 8
    def data(self, i, role=Qt.DisplayRole): return 'x' if role == Qt.DisplayRole else None


for _view_name, _cls, _behaviour in (('grid', QListView, QAbstractItemView.SelectItems),
                                     ('table', QTableView, QAbstractItemView.SelectRows)):
    _v = _cls()
    _v.setModel(_Cols())
    _v.setSelectionMode(QAbstractItemView.ExtendedSelection)
    _v.setSelectionBehavior(_behaviour)
    for _r in (0, 2):
        _v.selectionModel().select(_v.model().index(_r, 0), QItemSelectionModel.Select)
    assert len({i.row() for i in _v.selectedIndexes()}) == 2, _view_name
    if _behaviour == QAbstractItemView.SelectItems:
        assert not _v.selectionModel().selectedRows(), (
            'selectedRows() is empty under SelectItems, which is what the grid view uses')
say('selection: counted through selectedIndexes, which is the only form both views agree on')

scanned_with.clear()
single = misc.GalleryMenu(menu_view, model.index(1, 0), menu_view.sort_model, _StubAppWindow())
single_act = next(a for a in single.findChildren(misc.QAction)
                  if a.text() == 'Scan for a better version')
single_act.trigger()
assert [g.id for g in scanned_with[0]] == [101], scanned_with
say('context menu: the single-gallery entry scans just the gallery under the cursor')


# --- worker threads end when their work does ---------------------------------------------------
# Every repeatable background action used to leave its thread running for the life of the
# process: a QThread's event loop exits only on quit(), and the finished -> deleteLater every
# call site connects is caused by quit(), so neither ever happened.
from PyQt5.QtCore import QObject, QThread, pyqtSignal  # noqa: E402


class _Worker(QObject):
    DONE = pyqtSignal(object)

    def work(self):
        self.DONE.emit('ok')


w = _Worker()
seen = []
w.DONE.connect(seen.append)
t = misc.worker_thread(None, w, w.work, w.DONE, 'smoke.worker')
assert isinstance(t, QThread)
assert t.objectName() == 'smoke.worker'
assert not t.isRunning(), 'the helper must return the thread unstarted, so slots can be wired'
t.start()

for _ in range(200):                      # the worker emits, the loop quits, finished fires
    qapp.processEvents()
    if t.isFinished():
        break
    QThread.msleep(5)

assert seen == ['ok'], seen
assert t.isFinished(), 'the thread never ended: quit() was not wired to the finished signal'
assert not t.isRunning()
t.wait()
say('threads: a worker thread quits when its work signals done, so finished actually fires')

# Nothing may quit the two session-long threads, and no call site may hand-roll its own again.
import app as _app  # noqa: E402

src = open(_app.__file__, encoding='utf-8').read()
gallerydialog_src = os.path.join(os.path.dirname(_app.__file__), 'gallerydialog.py')
assert 'GENERAL_THREAD.quit' not in src, 'the long-lived shared thread must never be quit'
assert src.count('QThread(') == 2, (
    'every per-invocation thread should go through misc.worker_thread now; the only two that '
    'build their own are GENERAL_THREAD and the database startup thread, which are started '
    'once and live for the whole session')
assert 'QThread(' not in open(gallerydialog_src, encoding='utf-8').read(), (
    'the gallery dialog builds a thread per metadata fetch, one of them inside a loop')
say('threads: only the two session-long threads still build their own')

say('')
say('GUI SMOKE OK')