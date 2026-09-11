#"""
#This file is part of Happypanda.
#Happypanda is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 2 of the License, or
#any later version.
#Happypanda is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#You should have received a copy of the GNU General Public License
#along with Happypanda.  If not, see <http://www.gnu.org/licenses/>.
#"""
"""The review list of better versions of galleries already held, and the scan that fills it.

Nothing here writes to the gallery database or touches a file in the library. A row is a note
that the source carries a decensored or translated release of a gallery already held, which the
user downloads themselves; the rows therefore live in a database of their own, which needs no
version gate and can be deleted without losing anything a scan cannot produce again.
"""

import datetime
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass

from PyQt5.QtCore import QObject, pyqtSignal
from thefuzz import fuzz

import app_constants
import gallerydb  # noqa: F401  imported before fetch, which leaves it half initialised otherwise
import tagreaders
import fetch
import pewnet
import settings
import database

log = logging.getLogger(__name__)
log_i = log.info
log_d = log.debug
log_w = log.warning
log_e = log.error
log_c = log.critical

DB_NAME = 'better_versions.db'

KIND_DECENSORED = 'decensored'
KIND_TRANSLATED = 'translated'
KIND_REFINED = 'refined'
KIND_LABELS = {KIND_DECENSORED: 'Decensored', KIND_TRANSLATED: 'Translated',
               KIND_REFINED: 'Better translation'}

SOURCE_SCAN = 'scan'
SOURCE_PICKER = 'picker'

STATE_NEW = 'new'
STATE_DISMISSED = 'dismissed'

# How close a candidate's canonical title has to be to the held one to count as the same work.
# Far above the fetch's threshold because both sides here are the source's own title, so
# near-identity is reachable. Measured; see the scan section of the metadata-matching rule.
SAME_WORK_SCORE = 99

# Result pages one scan query follows, so a run costs exactly one request per gallery and its
# total can be stated before it starts.
SCAN_SEARCH_PAGES = 1

# How many of a gallery's rejected candidates the log names. A generic title turns up dozens,
# and the point is to make the rejections auditable rather than to record every one.
MAX_LOGGED_REJECTIONS = 5

# The tags the source itself writes for the two axes, without their namespaces: a tag the source
# wrote unqualified is stored under 'default' rather than 'Other', often enough that a
# namespace-qualified lookup misses a real 'uncensored'.
UNCENSORED_TAGS = frozenset(('uncensored',))
CENSORED_TAGS = frozenset(('mosaic censorship', 'full censorship'))
TRANSLATED_TAG = 'translated'
# What the source writes when a translation is there but poor. 'text cleaned' and 'textless
# narrative' are deliberately not here: they say the original text was removed or absent, which
# is a fact about the release rather than a caveat on its translation.
ROUGH_TAGS = frozenset(('rewrite', 'rough grammar', 'rough translation'))


@dataclass
class BetterVersion:
    """One row of the review list: a release of `series_id`'s work that improves on it."""
    series_id: int
    url: str
    title: str = ''
    native_title: str = ''
    thumb_url: str = ''
    kinds: tuple = ()
    held_title: str = ''
    source: str = SOURCE_SCAN
    found_at: str = ''
    state: str = STATE_NEW

    @property
    def kinds_label(self):
        """What this row offers, as the window shows it.

        A row noted by hand from the gallery chooser has no kinds: nothing classified it, the
        user simply recognised it. Saying so beats an empty cell that reads as a bug.
        """
        if not self.kinds:
            return 'You noted it'
        return ', '.join(KIND_LABELS.get(k, k.capitalize()) for k in self.kinds)


# --- tags ---------------------------------------------------------------------------------

# Re-exported from tagreaders, which owns the one definition of what a namespace means. Named
# here as well because the classification below reads as one vocabulary.
PARODY_NAMESPACE = tagreaders.PARODY_NAMESPACE
CREATOR_NAMESPACES = tagreaders.CREATOR_NAMESPACES
gallery_tag_values = tagreaders.gallery_tag_values
api_tag_values = tagreaders.api_tag_values
gallery_namespace_values = tagreaders.gallery_namespace_values
api_namespace_values = tagreaders.api_namespace_values
gallery_languages = tagreaders.gallery_languages
gallery_parodies = tagreaders.gallery_parodies
api_parodies = tagreaders.api_parodies
gallery_creators = tagreaders.gallery_creators
api_creators = tagreaders.api_creators
same_parody = tagreaders.same_parody
same_creator = tagreaders.same_creator


def tag_summary(values, parodies=(), creators=()):
    """What a tag set states on each axis, in the form the log shows it.

    Every axis has a third state that matters as much as the other two: a release that says
    nothing about its language, one that says nothing about its censorship, one the source has
    not placed in a series at all, and one it credits to nobody.

    The segments after the censorship carry a word in front of them - 'rough', 'by' - so that
    a summary missing an earlier one cannot be read as stating it. A release the source marked
    neither rough nor anything else says nothing, which is the ordinary case and not a claim
    that the translation is good.
    """
    languages = ', '.join(sorted(gallery_languages(values))) or 'no language'
    if values & UNCENSORED_TAGS:
        censorship = 'uncensored'
    elif values & CENSORED_TAGS:
        censorship = 'censored'
    else:
        censorship = 'censorship unstated'
    summary = f'{languages} / {censorship}'
    rough = values & ROUGH_TAGS
    if rough:
        summary += ' / rough: ' + ', '.join(sorted(rough))
    if parodies:
        summary += ' / ' + ', '.join(sorted(parodies))
    if creators:
        summary += ' / by ' + ', '.join(sorted(creators))
    return summary


# --- classification -----------------------------------------------------------------------

def worth_scanning(gallery, target_language):
    """Whether searching for this gallery could turn up anything the three axes recognise.

    A gallery the source has never tagged states nothing on any of them, and one already
    holding the target translation uncensored and unmarked has nothing left to find. This
    filter is what keeps a scan to a fraction of the library: every gallery it drops is a
    request that could not have paid off.
    """
    if not getattr(gallery, 'link', '') or not getattr(gallery, 'tags', None):
        return False
    values = gallery_tag_values(gallery.tags)
    if TRANSLATED_TAG not in values and target_language not in values:
        return True
    if values & ROUGH_TAGS:
        return True
    return bool(CENSORED_TAGS & values) and not (UNCENSORED_TAGS & values)


def target_language():
    """The translation a scan counts as an improvement, as the source tags it.

    Falls back to english for a language the source never tags, since the tag is the whole
    signal and filtering on one that cannot appear would find nothing at all.
    """
    language = (app_constants.BETTER_VERSION_LANGUAGE or 'English').strip().lower()
    if language not in tagreaders.LANGUAGE_TAGS:
        log_w(f"'{language}' is not a language the source tags; using english instead")
        return 'english'
    return language


def scan_blocked_reason():
    """Why a scan cannot find anything with the settings as they stand, or '' when it can.

    Both sides of the comparison have to be the same field of the same source. With native
    titles stored, the held side is Japanese while a listing gives romaji; the two share no
    characters and score near zero, so the scan would spend hours matching nothing and leave
    no sign of why.
    """
    if app_constants.USE_JPN_TITLE:
        return ("Scanning for better versions needs Web / Metadata / 'Use japanese title' "
                "turned off: it matches the source's own title for your gallery against that "
                "source's listings, and a native title never matches a romaji one.")
    return ''


def galleries_to_scan(galleries, language=None, store=None):
    """The galleries out of the given ones that a scan would actually search for.

    The count this returns is the number of requests a run makes, so whatever asks the user to
    agree to a run has to get it from here.
    """
    language = language or target_language()
    already = (store or shared_store()).scanned_ids()
    return [g for g in galleries
            if g.id and g.id not in already and worth_scanning(g, language)]


def held_forms(held_title):
    """The forms of a held gallery's title worth comparing a candidate against.

    The whole canonical title, plus the romaji half before a 'romaji | translated' separator.
    That half is needed because a raw release of the same work carries only it, so a gallery
    stored with the full pair would otherwise never match its own decensored edition.

    Only the head, and only on a real separator. The translated tail is not offered: across the
    library, distinct works share one - 'Doubutsu no Oyome-san' and 'Kemono no Oyome-san' are
    both 'Animal Bride' - while a shared romaji head is nearly always one work someone
    translated twice. The whitespace-collapse separator and the trailing '-Subtitle-' form are
    left out for the reason `fetch.match_forms` gives: they reduce two different works to one
    string.
    """
    canonical = fetch.canonical_title(held_title or '')
    if not canonical:
        return []
    forms = [canonical]
    parts = [p.strip() for p in fetch.TITLE_SEPARATOR_RE.split(canonical, 1)]
    if len(parts) > 1 and parts[0] and parts[1] and parts[0] not in forms:
        forms.append(parts[0])
    return forms


def scan_estimate_seconds(count):
    """Roughly how long scanning `count` galleries takes.

    One paced request each, since the scan follows a single result page: `begin_lock` holds
    every request at least the configured offset apart, and that pacing rather than the
    request itself is what the run's length is made of.
    """
    return count * (max(app_constants.GLOBAL_EHEN_TIME, 3) + 2)


def scan_confirmation_text(to_scan, in_view, selected=0):
    """What to tell the user before a run, as (summary, detail).

    Quotes the language the scan will actually classify against rather than the configured one:
    the setting accepts a custom language the source never tags, and a dialog promising a
    translation nobody will look for is worse than no dialog.

    `selected` is how many galleries are highlighted but *not* what this run would cover, which
    happens when the run was started from the menu bar. Saying so beats letting someone agree to
    a library-wide scan they thought they had narrowed.
    """
    hours, minutes = divmod(int(scan_estimate_seconds(len(to_scan))) // 60, 60)
    if hours and minutes:
        duration = f'{hours}h {minutes}m'
    elif hours:
        duration = f'{hours}h'
    else:
        duration = f'{max(minutes, 1)}m'

    summary = (
        f'Search for a better version of {len(to_scan)} of the {len(in_view)} galleries in '
        f'view?\n\nThat is one search each against a source that bans by IP on request volume, '
        f'so expect around {duration}. It can be stopped from the Gallery menu and picks up '
        f'where it left off.\n\nNothing is downloaded and nothing in your library is changed: '
        f'what turns up goes on the Better versions list for you to work through.')
    if selected > 1:
        summary += (f'\n\nThis covers everything in view, not the {selected} galleries you have '
                    f'selected. To scan only those, right click them and choose '
                    f'Web / Scan selected for better versions.')

    effective = target_language()
    configured = (app_constants.BETTER_VERSION_LANGUAGE or '').strip()
    wanted = effective.capitalize()
    if configured and configured.strip().lower() != effective:
        wanted = (f'{effective.capitalize()} - the source does not tag "{configured}", so it '
                  f'cannot be searched for')

    listed = '\n'.join(g.title for g in to_scan[:200])
    if len(to_scan) > 200:
        listed += f'\n... and {len(to_scan) - 200} more'
    detail = (
        f'Looking for: a release translated into {wanted}, a decensored release of a gallery '
        f'held in its censored form, and a cleaner translation of one the source marked a '
        f'rewrite, rough grammar or a rough translation.\n\n'
        f'Skipped: galleries the source has never tagged, galleries already holding all three, '
        f'and galleries a previous scan has already searched for.\n\n{listed}')
    return summary, detail


def same_work(held_title, candidate_title):
    """Whether a search hit is another release of the gallery it was searched for.

    Both sides are the source's own title, so the cross-script case the fetch has to carry does
    not arise and a near-identical form is reachable: what differs between two releases of one
    work - '[English]', '[Decensored]', '[Digital]', the magazine - is exactly what
    canonical_title strips. Compared case-folded, since the two titles were written by
    different uploaders and capitalisation is the commonest thing they disagree on.
    """
    forms = held_forms(held_title)
    if not forms:
        return False
    # Anchored on the whole title rather than on each form: a romaji head carries none of the
    # numbers its translated half may hold, so comparing form by form would let 'Foo | Bar 2'
    # and 'Foo | Bar 3' agree on an empty set and read as one work.
    local_numbers = fetch.title_numbers(forms[0])
    candidate_forms = fetch.match_forms(candidate_title or '')
    for local in forms:
        folded = local.lower()
        for form in candidate_forms:
            if fetch.title_numbers(form) != local_numbers:
                continue  # a different volume, chapter or sequel, whatever it scores
            if fuzz.ratio(folded, form.lower()) >= SAME_WORK_SCORE:
                return True
    return False


def better_kinds(held_values, candidate_values, language):
    """Which of the three axes the candidate improves on, as a sorted tuple. Empty means none.

    Decided from the tags the source wrote rather than from the candidate's title: a release
    marks itself '[Decensored]' inconsistently, while 'uncensored' is the tag the site's own
    filters run on.

    A row has to be a strict improvement and not a trade, which is a condition on the *other*
    axes in each case. An uncensored release in a language the held gallery is not in gives a
    language away to gain the censorship, and a translation that is censored gives the
    censorship back to gain the language. Neither is worth telling anyone about.

    Two of the three read an absence as the improvement: the held gallery only has to lack the
    `uncensored` tag, and the candidate only has to lack the rough ones. That keeps a release
    nobody tagged in scope, at the cost of rows for a gallery that was already uncensored, or
    a candidate no better translated, without either saying so - so those rows are worth
    checking rather than certain.
    """
    held_langs = gallery_languages(held_values)
    candidate_langs = gallery_languages(candidate_values)
    held_uncensored = bool(held_values & UNCENSORED_TAGS)
    # Give or take the one being scanned for, which is the case where the candidate improves
    # on the language axis at the same time.
    same_languages = held_langs <= candidate_langs <= held_langs | {language}

    kinds = []
    if (candidate_values & UNCENSORED_TAGS) and not held_uncensored and same_languages:
        kinds.append(KIND_DECENSORED)
    if language in candidate_langs and language not in held_langs \
            and TRANSLATED_TAG not in held_values \
            and not (held_uncensored and (candidate_values & CENSORED_TAGS)):
        kinds.append(KIND_TRANSLATED)
    # The same translation done better. `held_langs` has to be non-empty for there to be a
    # translation to improve at all: the source will write a rough tag with no language beside
    # it, and without this every untagged candidate reads as a cleaner version of nothing.
    if held_langs and (held_values & ROUGH_TAGS) and not (candidate_values & ROUGH_TAGS) \
            and same_languages \
            and not (held_uncensored and (candidate_values & CENSORED_TAGS)):
        kinds.append(KIND_REFINED)
    return tuple(sorted(kinds))


def make_hen():
    """The source to work against: exhentai when its login works, e-hentai otherwise.

    The same choice auto_web_metadata makes, and for the same reason - exhentai lists galleries
    e-hentai does not, and those are exactly the releases worth being told about.
    """
    if 'exhentai' in app_constants.DEFAULT_EHEN_URL:
        try:
            exprops = settings.ExProperties()
            hen = pewnet.ExHen(exprops.cookies)
            if hen.check_login(exprops.cookies):
                log_i('Working against exhentai')
                return hen
        except ValueError:
            pass
    log_i('Working against e-hentai')
    return pewnet.EHen()


def scan_query(gallery):
    """The one query a gallery is scanned with, or '' when its title yields nothing.

    The romaji half alone, quoted, with no artist and no language filter. Quoting the whole
    'romaji | translated' pair would exclude the untranslated original, which carries only
    that half, and a language filter would exclude the very translations the scan looks for.

    Split on the separator itself rather than through fetch.split_on_separator: that function
    also treats a run of whitespace as a deleted separator, which is a filesystem artefact of
    a folder name and would cut a source's own title short.
    """
    title = gallery.title or ''
    head = fetch.TITLE_SEPARATOR_RE.split(title, 1)[0]
    form = fetch.search_form(head.strip() or title)
    if not form:
        return ''
    return fetch.build_query(form, '', '')


# --- the store ----------------------------------------------------------------------------

class BetterVersionStore:
    """The review list, in a database of its own beside the gallery one.

    Separate because the rows are derived and disposable: a table in the gallery database
    would only reach an existing one through `add_db_revisions`, which means bumping the
    accepted version and putting every user through the incompatible-database prompt for data
    a rescan reproduces. It also means nothing here can damage the library index.

    Safe to call from any thread: one connection, guarded by one lock.
    """

    def __init__(self, path=None):
        self.path = path or os.path.join(database.db_constants.DB_ROOT, DB_NAME)
        self._lock = threading.Lock()
        self._conn = None

    def _connection(self):
        "The connection, opened and laid out on first use. Assumes the lock is held."
        if self._conn is None:
            os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS candidates(
                    series_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    native_title TEXT NOT NULL DEFAULT '',
                    thumb_url TEXT NOT NULL DEFAULT '',
                    kinds TEXT NOT NULL DEFAULT '',
                    held_title TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'scan',
                    found_at TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'new',
                    PRIMARY KEY(series_id, url)
                );
                CREATE TABLE IF NOT EXISTS scanned(
                    series_id INTEGER PRIMARY KEY,
                    scanned_at TEXT NOT NULL DEFAULT ''
                );
            """)
            self._conn.commit()
        return self._conn

    def add(self, row):
        """Stores a row, returning the state it already had, or None when it is new.

        Three columns survive a re-add rather than being overwritten, because each records
        something about the row's history that the incoming copy cannot know:

        - `state`, so a candidate the user has already dismissed does not come back as new.
        - `source`, which records how the row was found. Hand-noted wins whichever side
          arrives second: a user who picked a row while looking at the alternatives knows
          something the tags do not, and a re-find cannot take that back.
        - `found_at`, which orders the list; refreshing it would move an old row to the top.

        Everything else is taken from the incoming row, since a fresh classification of the
        same candidate is the better one.

        The previous state is returned rather than a plain "was it new", because a run that
        turned up only rows already on the list has to be able to say so instead of reporting
        that it found nothing.
        """
        row.found_at = row.found_at or datetime.datetime.now().replace(microsecond=0).isoformat(' ')
        with self._lock:
            conn = self._connection()
            existing = conn.execute(
                'SELECT state, source, found_at FROM candidates WHERE series_id=? AND url=?',
                (row.series_id, row.url)).fetchone()
            state = existing['state'] if existing else row.state
            source = row.source
            found_at = row.found_at
            if existing:
                found_at = existing['found_at'] or row.found_at
                source = (SOURCE_PICKER if SOURCE_PICKER in (existing['source'], row.source)
                          else row.source)
            conn.execute(
                'INSERT OR REPLACE INTO candidates(series_id, url, title, native_title, '
                'thumb_url, kinds, held_title, source, found_at, state) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                (row.series_id, row.url, row.title, row.native_title, row.thumb_url,
                 ','.join(row.kinds), row.held_title, source, found_at, state))
            conn.commit()
        return existing['state'] if existing else None

    def rows(self, include_dismissed=False):
        """The stored rows, newest first. Reads only - see `prune` for dropping stale ones.

        Reading and pruning are separate because the caller that wants the rows is not always
        in a position to say which galleries still exist.
        """
        with self._lock:
            conn = self._connection()
            sql = 'SELECT * FROM candidates'
            if not include_dismissed:
                sql += f" WHERE state != '{STATE_DISMISSED}'"
            sql += ' ORDER BY found_at DESC, series_id DESC'
            found = conn.execute(sql).fetchall()
        return [BetterVersion(series_id=r['series_id'], url=r['url'], title=r['title'],
                              native_title=r['native_title'], thumb_url=r['thumb_url'],
                              kinds=tuple(k for k in r['kinds'].split(',') if k),
                              held_title=r['held_title'], source=r['source'],
                              found_at=r['found_at'], state=r['state'])
                for r in found]

    def prune(self, live_series_ids):
        """Drops the rows and the scan progress of galleries no longer in the library.

        There is no foreign key to the gallery database to do this - that is the price of
        keeping the two apart - so it has to be asked for. Only ever call it with the *whole*
        library: the ids are treated as the complete set of what exists, so a partial one
        deletes rows for galleries that are merely not loaded yet. An empty set is refused for
        the same reason.
        """
        ids = set(live_series_ids)
        if not ids:
            log_w('Refusing to prune the better version list against an empty library')
            return 0
        with self._lock:
            conn = self._connection()
            stored = {r['series_id'] for r in conn.execute('SELECT DISTINCT series_id FROM candidates')}
            stored |= {r['series_id'] for r in conn.execute('SELECT series_id FROM scanned')}
            orphans = stored - ids
            if orphans:
                log_i(f'Dropping {len(orphans)} better version row(s) whose gallery is gone')
                conn.executemany('DELETE FROM candidates WHERE series_id=?', [(i,) for i in orphans])
                conn.executemany('DELETE FROM scanned WHERE series_id=?', [(i,) for i in orphans])
                conn.commit()
        return len(orphans)

    def dismiss(self, series_id, url):
        "Marks a row dismissed, so neither the window nor a later scan offers it again."
        with self._lock:
            conn = self._connection()
            conn.execute('UPDATE candidates SET state=? WHERE series_id=? AND url=?',
                         (STATE_DISMISSED, series_id, url))
            conn.commit()

    def restore(self, series_id, url):
        """Puts a dismissed row back on the list.

        The counterpart to `dismiss` rather than a delete, because a row can be dismissed by a
        rule as well as by hand: a recheck judges against the held gallery's tags as they stand,
        and a metadata fetch may have rewritten those since the row was stored. Without this
        there is no way back from a rule that was wrong about a row.
        """
        with self._lock:
            conn = self._connection()
            conn.execute('UPDATE candidates SET state=? WHERE series_id=? AND url=?',
                         (STATE_NEW, series_id, url))
            conn.commit()

    def mark_scanned(self, series_ids):
        "Records that these galleries have been searched, so a resumed scan skips them."
        stamp = datetime.datetime.now().replace(microsecond=0).isoformat(' ')
        with self._lock:
            conn = self._connection()
            conn.executemany('INSERT OR REPLACE INTO scanned(series_id, scanned_at) VALUES(?,?)',
                             [(i, stamp) for i in series_ids if i])
            conn.commit()

    def scanned_ids(self):
        "The galleries a previous scan already searched for."
        with self._lock:
            conn = self._connection()
            return {r['series_id'] for r in conn.execute('SELECT series_id FROM scanned')}

    def forget_scanned(self):
        "Clears the scan progress, so the next scan covers everything again."
        with self._lock:
            conn = self._connection()
            conn.execute('DELETE FROM scanned')
            conn.commit()

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


_shared_store = None


def shared_store():
    "The one store the window, the picker and the scan all write to."
    global _shared_store
    if _shared_store is None:
        _shared_store = BetterVersionStore()
    return _shared_store


def note_candidate(gallery, title, url, native_title='', source=SOURCE_PICKER, kinds=()):
    """Files a candidate the user picked out by hand, returning whether it was new.

    Nothing is classified here. The user chose this row while looking at the alternatives,
    which is better evidence than the tags would be, and the search that produced it has
    already been paid for.
    """
    row = BetterVersion(series_id=gallery.id, url=url, title=title or '',
                        native_title=native_title or '',
                        kinds=tuple(kinds), held_title=gallery.title or gallery.path_title,
                        source=source)
    added = shared_store().add(row) is None
    log_i('Noted a better version of {}: {}'.format(row.held_title, url))
    return added


# --- the scan -----------------------------------------------------------------------------

class BetterVersionScan(QObject):
    """Searches the given galleries for releases of the same work that improve on them.

    One query per gallery, and one batched metadata lookup per MAX_GDATA_URLS candidates that
    survive it. Runs on a worker thread and reaches the gui only through its signals.
    """

    PROGRESS = pyqtSignal(str)
    FOUND = pyqtSignal(object)     # a BetterVersion, as soon as it is classified
    FINISHED = pyqtSignal(object)  # how many rows were found, or False when the scan never ran

    def __init__(self, parent=None):
        super().__init__(parent)
        self.galleries = []
        self.store = None
        # Whether the run stopped early. A partial pass is fine - the store records how far it
        # got - but it must not be reported as a finished one.
        self.aborted = False
        # What the run turned up, split by whether the user has seen it before. A scan that
        # re-finds only rows already on the list has to say that rather than report nothing.
        self.found_new = 0
        self.already_listed = 0
        self.already_dismissed = 0
        self._stop = False
        self._took_lock = False

    def take_lock(self):
        """Claims the metadata lock so a fetch started meanwhile refuses instead of doubling up.

        Meant to be called from the gui thread before the worker starts. Every other check of
        this flag happens there, so claiming it anywhere else leaves a window in which a fetch
        and a scan both pass their own check and run together.
        """
        if app_constants.USE_GLOBAL_EHEN_LOCK and not self._took_lock:
            app_constants.GLOBAL_EHEN_LOCK = True
            self._took_lock = True

    def cancel(self):
        """Asks the scan to stop after the gallery it is working on.

        A temporary ban is waited out inside the request itself, so a cancel during one only
        takes effect once that wait is over.
        """
        log_i('Better version scan was asked to stop')
        self._stop = True

    def _release_lock(self):
        """Clears the metadata lock, but only if this scan is what claimed it.

        With the lock setting off it was never ours, and clearing it regardless would release
        one something else is holding.
        """
        if self._took_lock:
            app_constants.GLOBAL_EHEN_LOCK = False
            self._took_lock = False

    def _cannot_run(self, reason):
        "Reports why the scan will not run, gives the lock back, and finishes."
        log_e(reason)
        self._release_lock()
        self.PROGRESS.emit(reason)
        self.FINISHED.emit(False)

    def scan(self):
        "Entry point for the worker thread."
        blocked = scan_blocked_reason()
        if blocked:
            self._cannot_run(blocked)
            return
        if app_constants.GLOBAL_EHEN_LOCK and not self._took_lock:
            self._cannot_run('A metadata fetch is already running!')
            return
        self.take_lock()  # for a direct call; the gui thread normally claimed it already
        try:
            found = self._scan()
        # The lock goes back before FINISHED on every path, not in the finally after it: the
        # emit is queued to the gui thread, which may start the next run while this one is
        # still unwinding, and that run's take_lock would then be undone by this one.
        except app_constants.MetadataFetchFail as err:
            log_e(f'Better version scan could not reach the source: {err}')
            self._release_lock()
            self.PROGRESS.emit(f'Scan for better versions cancelled: {err}')
            self.FINISHED.emit(False)
            return
        except Exception:
            log.exception('Better version scan failed')
            self._release_lock()
            self.PROGRESS.emit('Scan for better versions failed, see happypanda.log')
            self.FINISHED.emit(False)
            return
        finally:
            self._release_lock()
        self.FINISHED.emit(found)

    def _make_hen(self):
        "The source this run works against, as an override point for a run that supplies its own."
        return make_hen()

    def _scan(self):
        target = target_language()
        store = self.store or shared_store()
        galleries = galleries_to_scan(self.galleries, target, store)
        log_i(f'Scanning {len(galleries)} of {len(self.galleries)} galleries for better versions '
              f'(target language: {target})')
        if not galleries:
            self.PROGRESS.emit('No galleries left to scan for better versions.')
            return 0

        hen = self._make_hen()
        pending = []       # [(gallery, [(title, url), ...])] awaiting their metadata lookup
        pending_urls = 0
        found = 0

        try:
            for x, gallery in enumerate(galleries, 1):
                if self._stop:
                    log_i('Better version scan stopped after {} of {} galleries'.format(x - 1, len(galleries)))
                    self.aborted = True
                    break
                log_i(f'--- Scanning gallery {x}/{len(galleries)}: {gallery.title} ---')
                self.PROGRESS.emit(f'({x}/{len(galleries)}) Looking for a better version of: {gallery.title}')

                query = scan_query(gallery)
                if not query:
                    log_w('Gallery has no searchable title, skipping')
                    store.mark_scanned([gallery.id])
                    continue

                log_i(f'Scanning with query: {query}')
                # The expunged listing is a separate search holding deleted galleries, which cannot
                # be a better version of anything.
                results = hen.search(query, expunged=False, max_pages=SCAN_SEARCH_PAGES)
                if results == 'error':
                    log_e('Source refused the search, stopping the scan')
                    self.aborted = True
                    # The searches behind these are already spent, so classify them rather than
                    # pay for them again next run.
                    if pending:
                        found += self._classify(hen, store, pending, target)
                    pending = []
                    return found

                hits = results.get(query, []) if results else []
                candidates = [(t, u) for t, u in hits
                              if not self._is_held_gallery(gallery, u)
                              and same_work(gallery.title, t)]
                log_i(f'{len(hits)} hit(s), {len(candidates)} of them the same work')
                for title, _ in candidates[:5]:
                    log_i(f"  - '{title}'")

                if not candidates:
                    store.mark_scanned([gallery.id])
                    continue

                pending.append((gallery, candidates))
                pending_urls += len(candidates)
                if pending_urls >= pewnet.EHen.MAX_GDATA_URLS:
                    found += self._classify(hen, store, pending, target)
                    pending, pending_urls = [], 0

            if pending:
                found += self._classify(hen, store, pending, target)
                pending = []
        finally:
            # The searches behind these are spent whatever went wrong, and the source bans on
            # request volume, so one lookup costs less than searching again. Guarded, so a
            # failure here cannot replace the one that got us here.
            if pending:
                try:
                    self._classify(hen, store, pending, target)
                except Exception:
                    log_w(f'Could not classify {len(pending)} gallery(s) whose search was '
                          f'already spent; they will be searched for again')
        return found

    @staticmethod
    def _log_rejections(gallery, held_summary, rejected):
        """Records the same-title candidates that were turned down, and what each one carried.

        This is the stage that discards nearly everything a scan finds, and without the tags
        each candidate turned out to hold there is no way to tell a correct rejection from a
        classification that has stopped working.
        """
        log_i(f'{len(rejected)} same-title candidate(s) rejected for {gallery.title} '
              f'(held: {held_summary}):')
        for title, summary in rejected[:MAX_LOGGED_REJECTIONS]:
            log_i(f"  - {summary}: '{title}'")
        if len(rejected) > MAX_LOGGED_REJECTIONS:
            log_i(f'  - ... and {len(rejected) - MAX_LOGGED_REJECTIONS} more')

    @staticmethod
    def _is_held_gallery(gallery, url):
        """Whether a hit is the gallery being searched for rather than another release of it.

        Compared on the gallery id, not the url: e-hentai and exhentai serve the same gallery
        under different hosts, so a stored e-hentai link and an exhentai listing of the same
        gallery are two strings for one thing.
        """
        link = gallery.link or ''
        if '/g/' not in link or '/g/' not in url:
            return False
        held, hit = pewnet.EHen.parse_url(link), pewnet.EHen.parse_url(url)
        return bool(held and hit and held[0] == hit[0])

    def _classify(self, hen, store, pending, target):
        """Looks the collected candidates up in batches and stores the ones that improve.

        The api takes MAX_GDATA_URLS galleries per request, so a batch costs a handful of
        requests rather than one per candidate. Only the raw gmetadata is read: routing it
        through parse_metadata would put it one call away from apply_metadata, which writes to
        a gallery.
        """
        urls = []
        for _, candidates in pending:
            for _, url in candidates:
                if url not in urls:
                    urls.append(url)

        chunk = pewnet.EHen.MAX_GDATA_URLS
        entries = {}
        # Urls whose lookup never happened, as opposed to ones the api answered for: only the
        # first kind may hold a gallery back from being marked scanned.
        unresolved = set()
        for i in range(0, len(urls), chunk):
            batch = urls[i:i + chunk]
            result = hen.get_metadata(batch)
            if not result or result == 'error':
                log_w(f'Could not look up {len(batch)} candidate(s); leaving them for a later run')
                unresolved.update(batch)
                continue
            metadata_json, gid_to_url = result
            for entry in metadata_json.get('gmetadata', []):
                url = gid_to_url.get(entry.get('gid'))
                if url and 'error' not in entry:
                    entries[url] = entry
        requests_made = (len(urls) + chunk - 1) // chunk
        log_i(f'Classified {len(entries)}/{len(urls)} candidate(s) in {requests_made} request(s)')

        found = 0
        for gallery, candidates in pending:
            held_values = gallery_tag_values(gallery.tags)
            held_parodies = gallery_parodies(gallery.tags)
            held_creators = gallery_creators(gallery.tags)
            rejected = []
            for title, url in candidates:
                entry = entries.get(url)
                if not entry:
                    continue
                candidate_values = api_tag_values(entry)
                candidate_parodies = api_parodies(entry)
                candidate_creators = api_creators(entry)
                summary = tag_summary(candidate_values, candidate_parodies, candidate_creators)
                # The titles already matched, so a different series means the title was too
                # short to tell the two works apart.
                if not same_parody(held_parodies, candidate_parodies):
                    rejected.append((title, summary + ' - a different series'))
                    continue
                # Two doujins of one franchise share the series as readily as the title, so
                # this is what separates them.
                if not same_creator(held_creators, candidate_creators):
                    rejected.append((title, summary + ' - a different creator'))
                    continue
                kinds = better_kinds(held_values, candidate_values, target)
                if not kinds:
                    rejected.append((title, summary))
                    continue
                row = BetterVersion(
                    series_id=gallery.id, url=url, title=title,
                    native_title=entry.get('title_jpn', '') or '',
                    thumb_url=entry.get('thumb', '') or '',
                    kinds=kinds, held_title=gallery.title or gallery.path_title,
                    source=SOURCE_SCAN)
                previous = store.add(row)
                if previous is None:
                    found += 1
                    self.found_new += 1
                    log_i(f'{row.kinds_label} version of {row.held_title}: {url}')
                    self.FOUND.emit(row)
                elif previous == STATE_DISMISSED:
                    self.already_dismissed += 1
                    log_i(f'{row.kinds_label} version of {row.held_title} was dismissed '
                          f'earlier, so it is not offered again: {url}')
                else:
                    self.already_listed += 1
                    log_i(f'{row.kinds_label} version of {row.held_title} is already on the '
                          f'list: {url}')
            if rejected:
                self._log_rejections(
                    gallery, tag_summary(held_values, held_parodies, held_creators), rejected)
            # A gallery counts as scanned once every candidate of its own has been looked up.
            # One left unresolved by a failed request means the search has to happen again, or
            # its candidates would be dropped with nothing recording that they were missed.
            if any(url in unresolved for _, url in candidates):
                log_w(f'Leaving {gallery.title} unscanned: a candidate lookup did not complete')
            else:
                store.mark_scanned([gallery.id])
        return found


def recheck_confirmation_text(rows):
    """What to tell the user before a recheck, as (summary, detail).

    The request count is stated because it is the only cost: the candidates are already on the
    list, so nothing is searched for again and the figure is exact rather than a ceiling.
    """
    requests = (len(rows) + pewnet.EHen.MAX_GDATA_URLS - 1) // pewnet.EHen.MAX_GDATA_URLS
    summary = (
        f'Re-judge the {len(rows)} row(s) on the list against the current rules?\n\n'
        f'That is {requests} request(s) - the releases are already known, so none of them is '
        f'searched for again. A row that turns out to be a different work is dismissed rather '
        f'than deleted, so nothing here is lost.\n\nYour library is not touched.')
    detail = (
        'Each row is checked the way a scan checks a fresh candidate: the series the source '
        'tags it with, and who the source credits it to. A row you noted by hand from the '
        'gallery chooser is left alone - you picked it while looking at the alternatives, '
        'which is better evidence than the tags are.\n\n'
        'Whether a row still improves on your gallery is deliberately not rechecked: that '
        "reads your own gallery's tags, which a metadata fetch may have rewritten since, and "
        'dismissing a row over that is not what this offers to do.')
    return summary, detail


class BetterVersionRecheck(QObject):
    """Re-judges the rows already on the list against the current classification rules.

    A scan records every gallery it searched, so a rule added afterwards would reach the
    library only through `forget_scanned` and a second full pass - one request per gallery,
    hours of them. The candidates on the list are already known, so re-judging them costs one
    request per MAX_GDATA_URLS rows and no searching at all.

    Only the two same-work guards are applied, and a row that fails one is dismissed rather
    than deleted: that keeps it out of the window and out of a later scan while leaving it in
    the database for a rule that turns out to be wrong.
    """

    PROGRESS = pyqtSignal(str)
    FINISHED = pyqtSignal(object)  # how many rows were dismissed, or False when it never ran

    def __init__(self, parent=None):
        super().__init__(parent)
        self.galleries = []
        self.store = None
        # Rows no evidence arrived for, as opposed to rows that were judged and kept.
        self.unresolved = 0
        # Whether the run stopped early. The rows it reached are judged and their dismissals
        # stand, but a partial pass must not be reported as having cleared the whole list.
        self.aborted = False
        self._stop = False
        self._took_lock = False

    def cancel(self):
        """Asks the recheck to stop after the batch it is waiting on.

        A temporary ban is waited out inside the request itself, so a cancel during one only
        takes effect once that wait is over.
        """
        log_i('Better version recheck was asked to stop')
        self._stop = True

    def take_lock(self):
        "Claims the metadata lock, from the gui thread, as BetterVersionScan.take_lock is."
        if app_constants.USE_GLOBAL_EHEN_LOCK and not self._took_lock:
            app_constants.GLOBAL_EHEN_LOCK = True
            self._took_lock = True

    def _release_lock(self):
        "Clears the lock, but only if this recheck is what claimed it."
        if self._took_lock:
            app_constants.GLOBAL_EHEN_LOCK = False
            self._took_lock = False

    def recheck(self):
        "Entry point for the worker thread."
        if app_constants.GLOBAL_EHEN_LOCK and not self._took_lock:
            log_e('A metadata fetch is already running!')
            self.PROGRESS.emit('A metadata fetch is already running!')
            self.FINISHED.emit(False)
            return
        self.take_lock()  # for a direct call; the gui thread normally claimed it already
        try:
            dismissed = self._recheck()
        # Released before FINISHED on every path, for the reason BetterVersionScan.scan gives.
        except app_constants.MetadataFetchFail as err:
            log_e(f'Better version recheck could not reach the source: {err}')
            self._release_lock()
            self.PROGRESS.emit(f'Recheck cancelled: {err}')
            self.FINISHED.emit(False)
            return
        except Exception:
            log.exception('Better version recheck failed')
            self._release_lock()
            self.PROGRESS.emit('Recheck of the better version list failed, see happypanda.log')
            self.FINISHED.emit(False)
            return
        finally:
            self._release_lock()
        self.FINISHED.emit(dismissed)

    def _recheck(self):
        store = self.store or shared_store()
        rows = recheckable_rows(store)
        held = {g.id: g for g in self.galleries if g.id}
        log_i(f'Rechecking {len(rows)} better version row(s) against the current rules')
        if not rows:
            self.PROGRESS.emit('No rows on the better version list to recheck.')
            return 0

        hen = make_hen()
        chunk = pewnet.EHen.MAX_GDATA_URLS
        urls = []
        for row in rows:
            if row.url not in urls:
                urls.append(row.url)

        entries = {}
        for i in range(0, len(urls), chunk):
            if self._stop:
                log_i('Better version recheck stopped after {} of {} row(s)'.format(
                    i, len(urls)))
                self.aborted = True
                break
            batch = urls[i:i + chunk]
            self.PROGRESS.emit('Rechecking the better version list ({}/{})'.format(
                min(i + chunk, len(urls)), len(urls)))
            result = hen.get_metadata(batch)
            if not result or result == 'error':
                log_w(f'Could not look up {len(batch)} row(s); leaving them as they are')
                continue
            metadata_json, gid_to_url = result
            for entry in metadata_json.get('gmetadata', []):
                url = gid_to_url.get(entry.get('gid'))
                if url and 'error' not in entry:
                    entries[url] = entry

        dismissed = 0
        for row in rows:
            entry = entries.get(row.url)
            gallery = held.get(row.series_id)
            # A row the lookup never answered for, and one whose gallery is not loaded, are
            # both "no evidence" rather than "not the same work". `prune` owns the second case.
            if entry is None or gallery is None:
                self.unresolved += 1
                continue
            reason = row_rejection(gallery, entry)
            if not reason:
                continue
            # Both sides, for the reason _log_rejections gives: a dismissal is only auditable
            # if the log says what each side actually carried when it was made.
            held_summary = tag_summary(gallery_tag_values(gallery.tags),
                                       gallery_parodies(gallery.tags),
                                       gallery_creators(gallery.tags))
            summary = tag_summary(api_tag_values(entry), api_parodies(entry), api_creators(entry))
            log_i(f'Dismissing a better version of {row.held_title} ({held_summary}): '
                  f'{reason} ({summary}): {row.url}')
            store.dismiss(row.series_id, row.url)
            dismissed += 1
        log_i(f'Recheck dismissed {dismissed} row(s); {self.unresolved} could not be judged')
        return dismissed


def recheckable_rows(store=None):
    """The rows a recheck would re-judge.

    A row noted from the gallery chooser is left out: the user picked it while looking at the
    alternatives, which is better evidence than the tags are, and the tags were never what put
    it on the list.
    """
    return [r for r in (store or shared_store()).rows() if r.source != SOURCE_PICKER]


def row_rejection(gallery, entry):
    """Why a stored row is not another release of its gallery after all, or '' when it is.

    The two same-work guards only. Whether the release still improves on the gallery is
    deliberately left alone: that reads the gallery's own tags, which a metadata fetch may have
    rewritten since the row was stored, and a row dismissed over that would be dismissed for a
    change in the library rather than for being wrong.
    """
    if not same_parody(gallery_parodies(gallery.tags), api_parodies(entry)):
        return 'a different series'
    if not same_creator(gallery_creators(gallery.tags), api_creators(entry)):
        return 'a different creator'
    return ''


if __name__ == '__main__':
    raise NotImplementedError("Unit testing not yet implemented")
