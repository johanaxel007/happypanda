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
say('restore_options: filter=%s previews=%s' % (d.filter_by_language.isChecked(),
                                                d.picker_previews.isChecked()))

d.filter_by_language.setChecked(False)
d.picker_previews.setChecked(False)
d.accept()
assert app_constants.FILTER_RESULTS_BY_LANGUAGE is False, 'filter did not survive accept()'
assert app_constants.PICKER_PREVIEWS is False, 'previews did not survive accept()'
assert settings.get(True, 'Web', 'filter results by language', bool) is False
assert settings.get(True, 'Web', 'picker previews', bool) is False

d2 = settingsdialog.SettingsDialog()
assert d2.filter_by_language.isChecked() is False
assert d2.picker_previews.isChecked() is False
say('settings: both round trip through accept() into a reopened dialog')

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

say('')
say('GUI SMOKE OK')