#!/usr/bin/env python3
"""Reproduce the startup batch-insert workload against a model/view, on either Qt binding.

`Documentation/Design/QT6_STARTUP_REGRESSION.md` attributes a roughly fourfold startup slowdown
under PyQt6 to the model/view insert path, and its harness ladder - a queue, then a QApplication,
then a running event loop, then a QThread - stops one rung short of a model or a view, which is
why it measures the two bindings as identical. This is that rung.

It replicates what `gallerydb.DatabaseStartup.fetch_galleries` does per batch, with no database
and no application code: a table model holding plain rows, a sorted filtering proxy with a Python
`filterAcceptsRow`, an icon-mode list view and a table view both attached to that one proxy, and a
loader object on its own QThread calling `insertRows` across the thread boundary while the GUI
thread runs the event loop.

    venv/Scripts/python.exe misc/qt_modelview_bench.py PyQt6

Each element of the insert fan-out has its own switch, so the subtraction that S3 performed on the
running application can be repeated here in seconds:

    --no-view       do not attach either view to the proxy
    --no-table      attach only the list view
    --no-sort       leave the proxy unsorted
    --no-refilter   do not re-search the whole model on every insert
    --sort-role     sort on the shipped date_added role, or on the plain-string title
    --count-data    report how many times data() and filterAcceptsRow were called

The default is the application's own configuration. Comparing two bindings means running it twice
and dividing; absolute seconds depend on the machine and on the row count.
"""
import argparse
import collections
import random
import sys
import time

BINDINGS = ('PyQt5', 'PyQt6')

parser = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('binding', nargs='?', default='PyQt6', choices=BINDINGS,
                    help='which binding to import (default: PyQt6)')
parser.add_argument('--rows', type=int, default=19974,
                    help='rows to insert (default: 19974, the development library)')
parser.add_argument('--batch', type=int, default=1000,
                    help='rows per insert, as DATABASE_STARTUP_FETCH_LIMIT (default: 1000)')
parser.add_argument('--work', type=int, default=500,
                    help='passes of Python work per batch, standing in for fetchall and '
                         'gen_galleries (default: 500, a few seconds over the whole run)')
parser.add_argument('--sort-role', default='date_added', choices=('date_added', 'title'),
                    help="role the proxy sorts on. 'date_added' is the application's shipped "
                         "default and parses a QDateTime per comparison; 'title' returns a str "
                         "(default: date_added)")
parser.add_argument('--no-view', action='store_true', help='attach no view to the proxy')
parser.add_argument('--no-table', action='store_true', help='attach the list view only')
parser.add_argument('--no-sort', action='store_true', help='leave the proxy unsorted')
parser.add_argument('--no-refilter', action='store_true',
                    help='do not re-search the whole model on every insert')
parser.add_argument('--count-data', action='store_true',
                    help='report data() and filterAcceptsRow call counts (adds its own cost)')
parser.add_argument('--offscreen', action='store_true',
                    help='run under the offscreen platform (a hidden view lays out differently)')
args = parser.parse_args()

if args.offscreen:
    import os
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

if args.binding == 'PyQt5':
    from PyQt5.QtCore import (Qt, QObject, QThread, QModelIndex, QSize, QTimer,
                              QAbstractTableModel, QSortFilterProxyModel, pyqtSignal,
                              QDateTime, qInstallMessageHandler)
    from PyQt5.QtWidgets import (QApplication, QListView, QTableView, QWidget, QStackedLayout,
                                 QHeaderView)
    from PyQt5.QtCore import PYQT_VERSION_STR, qVersion
else:
    from PyQt6.QtCore import (Qt, QObject, QThread, QModelIndex, QSize, QTimer,
                              QAbstractTableModel, QSortFilterProxyModel, pyqtSignal,
                              QDateTime, qInstallMessageHandler)
    from PyQt6.QtWidgets import (QApplication, QListView, QTableView, QWidget, QStackedLayout,
                                 QHeaderView)
    from PyQt6.QtCore import PYQT_VERSION_STR, qVersion

# PyQt6 turns an unhandled exception inside a virtual reimplementation into qFatal: the process
# aborts with nothing on stderr. Installed before any widget exists, so a failure in data() or
# filterAcceptsRow says what it was.
qInstallMessageHandler(lambda mode, ctx, msg: print('QT[{}] {}'.format(mode, msg), flush=True))

GALLERY_ROLE = Qt.ItemDataRole.UserRole + 1
DATE_ADDED_ROLE = Qt.ItemDataRole.UserRole + 4
COLUMNS = range(11)  # as app_constants.COLUMNS
TITLE, ARTIST, TAGS, TYPE, FAV, CHAPTERS, LANGUAGE = 0, 1, 2, 3, 4, 5, 6

DATA_CALLS = collections.Counter()
FILTER_CALLS = collections.Counter()


class Row:
    """A stand-in for gallerydb.Gallery carrying only what the model reads."""

    __slots__ = ('id', 'title', 'artist', 'tags', 'type', 'fav', 'chapters', 'language',
                 'date_added')

    def __init__(self, i, rng):
        self.id = i
        # Mixed scripts and lengths, because the proxy sorts locale-aware on the title and a
        # run of near-identical ASCII strings is not the comparison the real library performs.
        head = rng.choice(('Schoolgirl Guide', 'Erohon', 'DepthSinker', '純情ロマンチカ',
                           'Melty Limit', 'Tsundere Bitch', '恋愛暴君', 'Angel Club'))
        self.title = '[{} ({})] {} {}'.format(rng.choice(('Circle', 'Studio', 'Team')),
                                              rng.choice(('Kisaragi', 'Momoiro', 'Aoi')),
                                              head, i)
        self.artist = rng.choice(('Kisaragi', 'Momoiro', 'Aoi', 'Hanabi'))
        self.tags = 'parody:none, female:sole female, language:translated'
        self.type = 'Doujinshi'
        self.fav = 1 if i % 17 == 0 else 0
        self.chapters = i % 4 + 1
        self.language = rng.choice(('English', 'Japanese', 'Other'))
        self.date_added = '{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
            2015 + i % 11, i % 12 + 1, i % 28 + 1, i % 24, i % 60, i % 60)


class BenchModel(QAbstractTableModel):
    """GalleryModel's shape: the same columns, the same roles, the same insertRows contract."""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self._data = data
        self._to_add = []

    def rowCount(self, index=QModelIndex()):
        if index.isValid():
            return 0
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if COUNTING:
            DATA_CALLS[int(role)] += 1
        if not index.isValid():
            return None
        row = index.row()
        if row >= len(self._data) or row < 0:
            return None
        gallery = self._data[row]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == TITLE:
                return gallery.title
            elif column == ARTIST:
                return gallery.artist
            elif column == TAGS:
                return gallery.tags
            elif column == TYPE:
                return gallery.type
            elif column == FAV:
                return '★' if gallery.fav else ''
            elif column == CHAPTERS:
                return gallery.chapters
            elif column == LANGUAGE:
                return gallery.language
            return None
        elif role == GALLERY_ROLE:
            return gallery
        elif role == DATE_ADDED_ROLE:
            # GalleryModel's own branch: the stored date is re-formatted and re-parsed on every
            # comparison, so a sorted proxy builds one QDateTime per lessThan call.
            return QDateTime.fromString('{}'.format(gallery.date_added), 'yyyy-MM-dd HH:mm:ss')
        return None

    def insertRows(self, position, rows, index=QModelIndex()):
        if not self._to_add:
            return False
        self.beginInsertRows(QModelIndex(), position, position + rows - 1)
        for _ in range(rows):
            self._data.insert(position, self._to_add.pop())
        self.endInsertRows()
        return True


class BenchProxy(QSortFilterProxyModel):
    """SortFilterModel's shape: a Python filterAcceptsRow over a result dict built off-thread."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = {}
        self._ready = False
        self.setDynamicSortFilter(True)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setSortLocaleAware(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def filterAcceptsRow(self, source_row, parent_index):
        if COUNTING:
            FILTER_CALLS['filterAcceptsRow'] += 1
        if not self.sourceModel():
            return None
        index = self.sourceModel().index(source_row, 0, parent_index)
        if not index.isValid():
            return False
        if not self._ready:
            return False
        gallery = index.data(GALLERY_ROLE)
        return self.result.get(gallery.id, True)


class Search(QObject):
    """GallerySearch's shape: a full walk of the model's data on a second worker thread."""

    FINISHED = pyqtSignal()

    def __init__(self, data):
        super().__init__()
        self._data = data
        self.result = {}

    def search(self):
        self.result.clear()
        for gallery in self._data:
            self.result[gallery.id] = True
        self.FINISHED.emit()


class Loader(QObject):
    """DatabaseStartup's shape: batched inserts issued from a thread that is not the GUI's.

    The measurement that matters is the `work` accumulator, not `insert`. In the application the
    only Qt call in the loop costs 0.01s under both bindings and the fourfold difference lands in
    `fetchall` and `gen_galleries` - plain Python on this thread, slowed because the GUI thread is
    busy with what the insert scheduled. So the loop carries a binding-independent Python
    workload, and its own time is what the two bindings are compared on.
    """

    DONE = pyqtSignal(float, float, float)

    def __init__(self, model, rows, batch, work):
        super().__init__()
        self._model = model
        self._rows = rows
        self._batch = batch
        self._work = work

    def _python_work(self, batch):
        """Stands in for fetchall and gen_galleries: pure Python, no Qt, no I/O."""
        seen = {}
        for _ in range(self._work):
            for row in batch:
                key = row.title.rsplit(' ', 1)[0].strip('[]').lower()
                seen[key] = seen.get(key, 0) + row.chapters
        return seen

    def startup(self):
        rng = random.Random(20260910)
        work_time = 0.0
        insert_time = 0.0
        started = time.perf_counter()
        offset = 0
        while offset < self._rows:
            limit = min(self._batch, self._rows - offset)
            batch = [Row(offset + i, rng) for i in range(limit)]

            t = time.perf_counter()
            self._python_work(batch)
            work_time += time.perf_counter() - t

            t = time.perf_counter()
            self._model._to_add = batch
            self._model.insertRows(self._model.rowCount(), len(batch))
            insert_time += time.perf_counter() - t

            offset += limit
        self.DONE.emit(work_time, insert_time, time.perf_counter() - started)


def main():
    global COUNTING
    COUNTING = args.count_data

    qapp = QApplication(sys.argv)

    data = []
    model = BenchModel(data)
    proxy = BenchProxy()
    proxy.setSourceModel(model)

    search = Search(data)
    search_thread = QThread()
    search.moveToThread(search_thread)
    search.FINISHED.connect(proxy.invalidateFilter)
    search_thread.start()

    def refresh():
        # Queued across the thread boundary, as SortFilterModel.refresh reaches GallerySearch.
        search.result = proxy.result
        search.search()

    proxy.result = search.result
    proxy._ready = True
    if not args.no_refilter:
        model.rowsInserted.connect(refresh)

    window = QWidget()
    layout = QStackedLayout(window)
    if not args.no_view:
        list_view = QListView()
        list_view.setViewMode(list_view.ViewMode.IconMode)
        list_view.setResizeMode(list_view.ResizeMode.Adjust)
        list_view.setWrapping(True)
        list_view.setUniformItemSizes(True)
        list_view.setLayoutMode(list_view.LayoutMode.Batched)
        list_view.setVerticalScrollMode(list_view.ScrollMode.ScrollPerPixel)
        list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_view.setIconSize(QSize(200, 300))
        list_view.setSpacing(10)
        list_view.setModel(proxy)
        layout.addWidget(list_view)

        if not args.no_table:
            table_view = QTableView()
            table_view.setSortingEnabled(True)
            table_view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            table_view.verticalHeader().setDefaultSectionSize(24)
            table_view.verticalHeader().hide()
            table_view.setIconSize(QSize(0, 0))
            table_view.setModel(proxy)
            layout.addWidget(table_view)

    if not args.no_sort:
        if args.sort_role == 'date_added':
            proxy.setSortRole(DATE_ADDED_ROLE)
            proxy.sort(0, Qt.SortOrder.DescendingOrder)
        else:
            proxy.setSortRole(Qt.ItemDataRole.DisplayRole)
            proxy.sort(0, Qt.SortOrder.AscendingOrder)

    window.resize(1200, 800)
    window.show()

    loader = Loader(model, args.rows, args.batch, args.work)
    loader_thread = QThread()
    loader.moveToThread(loader_thread)
    loader_thread.started.connect(loader.startup)

    class Reporter(QObject):
        """Lives on the GUI thread, so DONE arrives queued and `settle` is measured after the
        event loop has drained everything the last insert scheduled."""

        def report(self, work, insert, elapsed):
            settle_from = time.perf_counter()

            def finish():
                settle = time.perf_counter() - settle_from
                # Read after the timing, never before it. With no view, no sort and no
                # re-filter there is nothing left to consume the proxy, so it has never built
                # its row mapping and rowCount() answers from stale internal state.
                proxy.invalidate()
                print('TIMING {} rows in batches of {}: work {:.2f}s | insert {:.2f}s | '
                      'loop {:.2f}s | settle {:.2f}s'.format(
                          args.rows, args.batch, work, insert, elapsed, settle), flush=True)
                print('        model rows {}  proxy rows {}'.format(
                    model.rowCount(), proxy.rowCount()), flush=True)
                if args.count_data:
                    print('        filterAcceptsRow: {:>9}'.format(
                        FILTER_CALLS['filterAcceptsRow']), flush=True)
                    for role, count in sorted(DATA_CALLS.items(), key=lambda kv: -kv[1]):
                        print('        data() role {:>6}: {:>9}'.format(role, count), flush=True)
                    print('        data() total : {:>9}'.format(sum(DATA_CALLS.values())),
                          flush=True)
                loader_thread.quit()
                search_thread.quit()
                qapp.quit()

            QTimer.singleShot(0, finish)

    reporter = Reporter()
    loader.DONE.connect(reporter.report)

    config = [args.binding]
    if args.no_view:
        config.append('no-view')
    if args.no_table:
        config.append('no-table')
    if args.no_sort:
        config.append('no-sort')
    if args.no_refilter:
        config.append('no-refilter')
    config.append('sort=' + args.sort_role)
    print('{} (Qt {} runtime, binding {}) | {}'.format(
        args.binding, qVersion(), PYQT_VERSION_STR, ' '.join(config[1:]) or 'full'), flush=True)

    loader_thread.start()
    rc = qapp.exec() if hasattr(qapp, 'exec') else qapp.exec_()
    loader_thread.wait()
    search_thread.wait()
    return rc


# Off by default: counting runs in the two hottest callbacks and would tax the thing measured.
COUNTING = False

if __name__ == '__main__':
    sys.exit(main())
