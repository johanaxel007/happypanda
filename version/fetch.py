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

import os
import time
import logging
import queue
import re
import random

from PyQt6.QtCore import QObject, pyqtSignal # need this for interaction with main thread
from thefuzz import fuzz

import gallerydb
import app_constants
import pewnet
import settings
import tagreaders
import utils
from formatters import title_formatter, TranslationStyle

"""This file contains functions to fetch gallery data"""

log = logging.getLogger(__name__)
log_i = log.info
log_d = log.debug
log_w = log.warning
log_e = log.error
log_c = log.critical

# Splits a "romaji title | translated title" pair. Both separator forms are accepted because
# a folder name carries the full-width one (see utils.title_parser for the same pattern).
TITLE_SEPARATOR_RE = re.compile(r'[|｜]')
# Some folder names had the separator deleted rather than substituted, leaving the two spaces
# that surrounded it as the only trace of it. Only consulted when no real separator is present,
# and only on a raw folder name, since formatting collapses runs of whitespace.
COLLAPSED_SEPARATOR_RE = re.compile(r'\s{2,}')
# A leading "[Circle (Artist)]" prefix, allowing one level of nested parentheses.
GROUP_PREFIX_RE = re.compile(r'^\s*\[[^\[\]]*(?:\([^()]*\)[^\[\]]*)*\]\s*')
# A single decorated token such as ~tag~ or *note*. Both delimiters must be the same
# character and the content may contain neither it nor whitespace, so that hyphenated words
# and underscored artist names survive and no match spans a whole title.
DECORATION_RE = re.compile(r'\s*([=~*+])(?:(?!\1)\S)+\1\s*')
# Any run of digits, used to tell a sequel or chapter apart from its siblings.
NUMBER_RE = re.compile(r'\d+')
# A roman numeral standing on its own, upper case only. Case is what separates the numeral from
# the word: 'Ii kara Watashi ni Dakarenasai' opens with the Japanese word for 'good', and the
# word boundaries keep the 'II' inside a name like 'DRII' out of it.
ROMAN_RUN_RE = re.compile(r'\b[IVX]+\b')
# Roman numerals folded to the integer each denotes, so 'II' and '2' compare equal. Two
# characters at least: a lone 'I' is the English pronoun, 'V' abbreviates versus and 'X' is the
# crossover multiplier, none of which is a volume number.
ROMAN_NUMERALS = {'II': 2, 'III': 3, 'IV': 4, 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9,
                  'XI': 11, 'XII': 12}
# The Unicode roman numeral block, which a filesystem name carries and nothing else folds:
# 'Ⅱ' is a single character, and lowercasing it moves it to a different one again. Only the
# forms of the numerals above, so the two notations are read exactly alike.
_ROMAN_CHARS = ('I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII')
ROMAN_BLOCK = str.maketrans({
    **{chr(0x2160 + i): r for i, r in enumerate(_ROMAN_CHARS) if r in ROMAN_NUMERALS},
    **{chr(0x2170 + i): r for i, r in enumerate(_ROMAN_CHARS) if r in ROMAN_NUMERALS},
})
# A trailing "-Subtitle-" or "~Subtitle~" segment, both delimiters the same. Requires four
# characters of content and none of the delimiter inside, so an ordinary hyphenated ending is
# left alone.
TRAILING_SUBTITLE_RE = re.compile(r'\s*([-~])\s*[^-~]{4,}\s*\1\s*$')
# Han, hiragana, katakana and the CJK compatibility block. Full-width punctuation is
# deliberately excluded: it is folded to ASCII before comparison and says nothing about
# which script a title is written in.
CJK_RE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')

# Any bracketed group, wherever it sits in the title.
BRACKET_GROUP_RE = re.compile(r'\[([^\[\]]+)\]')
# Shared with the better version scan, which compares the same languages coming off the api's
# own namespace rather than off a bracketed title tag. Re-exported under this name because the
# rule and the tests both refer to it here.
LANGUAGE_TAGS = tagreaders.LANGUAGE_TAGS
# The languages a work is written in rather than translated into. A local gallery in one of
# these is not evidence of anything: the app stores G_DEF_LANGUAGE for every gallery whose
# folder name never stated a language, so 'Japanese' is as often "unknown" as it is a fact.
UNTRANSLATED_LANGUAGES = frozenset(('japanese', 'chinese', 'korean'))
# The source's own default language, which it therefore does not tag: a japanese original carries
# no language tag at all, and the absence of one is what says japanese. A 'language:japanese$'
# filter consequently matches nothing on the whole site.
UNTAGGED_LANGUAGE = 'japanese'
# Ceilings on one gallery's search. The attempt cap bounds the request rate against a source that
# bans on volume, and is reached only when every variation comes back empty.
MAX_QUERY_LENGTH = 200
MAX_SEARCH_ATTEMPTS = 4


def title_languages(title):
    """The languages a title declares in its bracketed tags, lowercased.

    A tag holds one language, a comma separated list of them, or a language followed by its own
    name for itself - "[Thai \u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22]". Anything else in brackets - '[Digital]', '[Decensored]', a
    translator - contributes nothing. An empty result means the title makes no claim, which is
    the normal shape of an untranslated release.
    """
    found = set()
    # The leading "[Circle (Artist)]" group never holds a language, and a circle name can begin
    # with a word that is one.
    for group in BRACKET_GROUP_RE.findall(GROUP_PREFIX_RE.sub('', title, count=1)):
        for part in group.split(','):
            words = part.strip().lower().split()
            if not words:
                continue
            if part.strip().lower() in LANGUAGE_TAGS or words[0] in LANGUAGE_TAGS:
                found.add(words[0])
    return found


def language_is_known(gallery):
    """Whether a gallery's stored language is a fact about it or just the app's fallback.

    Every gallery whose folder name never stated a language is stored as G_DEF_LANGUAGE, so
    that value on its own cannot be told apart from "nobody knew". It counts as known when the
    folder name states it outright, or when it differs from the default nothing else could
    have set it to.
    """
    language = (gallery.language or '').strip().lower()
    if not language:
        return False
    if language != (app_constants.G_DEF_LANGUAGE or '').strip().lower():
        return True
    return language in title_languages(gallery.path_title or '')


def split_on_separator(title):
    """Returns the part of the title before its 'romaji | translated' separator, or ''.

    Give this the raw folder name rather than a formatted one: a deleted separator survives
    only as the run of whitespace it left behind, and formatting collapses that away.
    """
    for pattern in (TITLE_SEPARATOR_RE, COLLAPSED_SEPARATOR_RE):
        parts = pattern.split(title, 1)
        if len(parts) < 2:
            continue
        head, tail = parts[0].strip(), parts[1].strip()
        # Both sides have to carry title text, otherwise the gap was just the one after a
        # "[Circle (Artist)]" prefix and splitting there yields nothing worth searching for.
        if strip_group_prefix(head) or (head and not GROUP_PREFIX_RE.match(head)):
            if tail:
                return head
    return ''


def strip_group_prefix(title):
    """Returns the title without its leading '[Circle (Artist)]' prefix, or '' when unchanged."""
    stripped = GROUP_PREFIX_RE.sub('', title).strip()
    return stripped if stripped and stripped != title else ''


def title_numbers(title):
    """The distinct numbers in a title.

    A volume, chapter or sequel number is a tiny edit distance but decides which gallery this
    actually is: 'Kaizoku Kyonyuu' and 'Kaizoku Kyonyuu 2' score 90 against each other. Compared
    as a set rather than a sequence, so a title that repeats the number in its translated half
    still matches one that does not.

    A roman numeral counts as the number it denotes, in either notation, so that 'Erohon V' and
    'Erohon II' are told apart and 'DepthSinker2' and 'DepthSinker II' are not. Japanese
    numerals are deliberately not read: 'ni', 'san' and 'go' are the particle, the honorific
    and an ordinary syllable far more often than they are numbers.
    """
    folded = title.translate(ROMAN_BLOCK)
    numbers = {int(n) for n in NUMBER_RE.findall(folded)}
    numbers.update(ROMAN_NUMERALS[run] for run in ROMAN_RUN_RE.findall(folded)
                   if run in ROMAN_NUMERALS)
    return numbers


def canonical_title(title):
    """Reduces a title to the part worth comparing between a local folder and a search hit.

    A site keeps the decorations a folder name has already lost - '[Circle (Artist)]',
    '(COMIC LO 2020-01)', '[English]', '[Digital]', translator credits - and fuzz.ratio is
    length sensitive, so those alone are enough to push an exact match below the threshold.
    Both sides get the same treatment here so that like is compared with like.
    """
    cleaned = title_formatter.format_title(title, translation_style=TranslationStyle.SEARCH)
    return strip_group_prefix(cleaned) or cleaned


def search_form(title):
    """The form a title takes inside a search query: normalised, then stripped of decorations."""
    formatted = title_formatter.format_title(title, translation_style=TranslationStyle.SEARCH)
    return DECORATION_RE.sub(' ', formatted).strip() or formatted


def match_forms(title):
    """The canonical forms of a search hit that are worth comparing against a local title.

    A site title is often the full 'romaji | translated' pair while the folder kept only one
    of the two halves, which costs an exact match around 40 points of a length sensitive
    ratio. Each half is therefore offered alongside the whole, and so is each form without a
    trailing '-Subtitle-', which a folder name drops just as readily.

    Only the candidate is broken up this way. Doing the same to the local title would reduce
    'Title -Sub A-' and 'Title -Sub B-' to the same string and score two different works a
    perfect 100 against each other.
    """
    canonical = canonical_title(title)
    forms = [canonical]
    parts = [p.strip() for p in TITLE_SEPARATOR_RE.split(canonical)]
    if len(parts) > 1:
        forms.extend(p for p in parts if p and p not in forms)
    for form in list(forms):
        without_subtitle = TRAILING_SUBTITLE_RE.sub('', form).strip()
        if without_subtitle and without_subtitle not in forms:
            forms.append(without_subtitle)
    return forms


def picker_labels(title_url_list, previews):
    """The rows a gallery chooser lists, and their cover urls, as (title_url_list, {url: thumb}).

    A search listing gives one title, usually romaji, and nothing else. A row therefore carries
    up to three lines: the listing title, the native title, and who the source credits the
    release to. Each line is left out when there is nothing to put on it.

    The creator is the line that settles two candidates for one work, because `canonical_title`
    strips the '[Circle (Artist)]' group out of both titles before they are ever scored. It is
    shown rather than compared: the other side of any such comparison is a folder name, whose
    creator disagrees with the source's own tag often and is absent from it more often still,
    so filtering on it would discard real matches. The rule file holds the measurement.

    Without previews the rows are returned unchanged, which is also the chaika case - the
    lookup is an e-hentai api call and there is nothing equivalent to read there.
    """
    if not previews:
        return list(title_url_list), {}
    labelled, thumbnails = [], {}
    for title, url in title_url_list:
        preview = previews.get(url, {})
        native = preview.get('native', '')
        if native and native != title:
            title = f'{title}\n{native}'
        creators = preview.get('creators') or ()
        if creators:
            title = f'{title}\nby {", ".join(creators)}'
        if preview.get('thumb'):
            thumbnails[url] = preview['thumb']
        labelled.append((title, url))
    return labelled, thumbnails


def build_query(title, artist, lang):
    """Builds the search query, trimming an over-long title on a word boundary."""
    # A title can carry its own quotes once the full-width ones are folded to ASCII
    # ('M＆N Ji Kaikyaku Gashuu ＂Kaikyaku Otome＂'). Left in, they close the phrase
    # early and the remainder is parsed as loose terms, which matches nothing.
    title = ' '.join(title.replace('"', ' ').split())
    filters = artist + lang
    max_title_len = MAX_QUERY_LENGTH - len(filters) - 2  # -2 for quotes
    if len(title) <= max_title_len:
        return f'"{title}"{filters}'.strip()

    # The title does not fit. Trim it on a word boundary and drop the quotes:
    # a quoted phrase that was cut mid-title can never match anything.
    trimmed = title[:max_title_len].rsplit(' ', 1)[0].strip() or title[:max_title_len].strip()
    return f'{trimmed}{filters}'.strip()


def language_filter(language):
    """The 'l:x$' filter to search a gallery of the given language with, or ''.

    Empty for a language the source leaves untagged, since filtering on one of those matches
    nothing at all rather than narrowing anything.

    The source's short form of the namespace, verified against it to return the same hits as
    'language:' - seven characters that the query cap would otherwise take off the title. Not
    to be confused with the app's own search grammar, where 'language:' is local syntax.
    """
    language = (language or '').strip().lower()
    if not language or language == UNTAGGED_LANGUAGE:
        return ''
    return f' l:{language}$'


def search_queries(gallery, max_attempts=MAX_SEARCH_ATTEMPTS):
    """The queries to search a gallery for, in descending order of how often they pay off.

    Empty when the folder name reduces to nothing, which happens for a gallery whose path is a
    drive root or one on a drive that is not mounted - an empty query matches the whole site.
    """
    sanitized_title = search_form(gallery.path_title)
    # Split the raw folder name, not the formatted one: a deleted separator is only visible as
    # the whitespace run that formatting collapses away.
    split_raw = split_on_separator(gallery.path_title)

    # Some galleries hold a language where their artist should be, from names like "Guardian of
    # Faith II [English]" that have no artist prefix at all. An artist:english$ filter matches
    # nothing, so drop it rather than search on it.
    artist_name = (gallery.artist or '').strip()
    if artist_name.lower() in utils.known_languages():
        log_w(f"Ignoring language '{artist_name}' stored as this gallery's artist")
        artist_name = ''

    has_artist = bool(artist_name)
    artist_part = ""
    if has_artist:
        artist_name = artist_name.lower()
        # The source's short form of the namespace, verified against it to return the same
        # hits as 'artist:', quoted form included. Five characters the query cap would
        # otherwise take off the title.
        artist_part = f' a:"{artist_name}"$' if ' ' in artist_name else f' a:{artist_name}$'

    # In descending order of how often they pay off: the folder title as-is, the romaji half
    # before the '|' that a source usually indexes, then each of those without the
    # "[Circle (Artist)]" prefix the artist filter already covers.
    bases = [sanitized_title, search_form(split_raw) if split_raw else '']
    title_variants = []
    for variant in bases + [strip_group_prefix(b) for b in bases if b]:
        if variant and variant not in title_variants:
            title_variants.append(variant)

    if not title_variants:
        return []

    lang_part = language_filter(gallery.language)
    queries = []

    def add_query(title_v, artist_v, lang_v):
        query = build_query(title_v, artist_v, lang_v)
        # Duplicates collapse: a title with no separator or no prefix yields fewer variants,
        # and truncation can make two variants build the same query.
        if query not in queries:
            queries.append(query)

    # The artist filter is worth exactly one attempt: the stored artist rarely matches the
    # source's spelling, so dropping it is the most productive single variation, while pairing
    # it with a fallback title never is and gets no slot.
    add_query(title_variants[0], artist_part, lang_part)
    add_query(title_variants[0], '', lang_part)
    # The loosest form there is, and the one a source is likeliest to hold: the bare romaji
    # half, nothing filtering it. Third rather than fifth because the budget runs out at four,
    # and a gallery the source disagrees with on artist or language reaches nothing else.
    add_query(title_variants[-1], '', '')
    for title_v in title_variants[1:]:
        add_query(title_v, '', lang_part)
    if lang_part:
        add_query(title_variants[0], '', '')
    # Whatever budget is left over goes to the combinations skipped above.
    for title_v in title_variants[1:]:
        add_query(title_v, artist_part, lang_part)
    if lang_part:
        add_query(title_variants[0], artist_part, '')
        for title_v in title_variants[1:]:
            add_query(title_v, '', '')

    return queries[:max_attempts]


class Fetch(QObject):
    """
    A class containing methods to fetch gallery data.
    Should be executed in a new thread.
    Contains following methods:
    local -> runs a local search in the given series_path
    auto_web_metadata -> does a search online for the given galleries and returns their metadata
    """

    # local signals
    LOCAL_EMITTER = pyqtSignal(gallerydb.Gallery)
    FINISHED = pyqtSignal(object)
    DATA_COUNT = pyqtSignal(int)
    PROGRESS = pyqtSignal(int)
    SKIPPED = pyqtSignal(list)

    # WEB signals
    GALLERY_EMITTER = pyqtSignal(gallerydb.Gallery, object, object)
    AUTO_METADATA_PROGRESS = pyqtSignal(str)
    GALLERY_PICKER = pyqtSignal(object, list, queue.Queue, object)
    GALLERY_PICKER_QUEUE = queue.Queue()
    

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series_path = ""
        self._data = []
        self._curr_gallery = '' # for debugging purposes
        self.skipped_paths = []

        # web
        self._default_ehen_url = app_constants.DEFAULT_EHEN_URL
        self.galleries = []
        self.galleries_in_queue = []
        self.error_galleries = []
        self._hen_list = []

        #filter
        self.galleries_from_db = []
        self._refresh_filter_list()

        #download
        self._to_queue_container = False
        self._galleries_queue = queue.Queue()

    def _refresh_filter_list(self):
            gallery_data = app_constants.GALLERY_DATA + app_constants.GALLERY_ADDITION_DATA
            filter_list = []
            for g in gallery_data:
                filter_list.append(os.path.normcase(g.path))
            self.galleries_from_db = sorted(filter_list)

    def create_gallery(self, path, folder_name, do_chapters=True, archive=None):
        is_archive = True if archive else False
        temp_p = archive if is_archive else path
        folder_name = folder_name or path if folder_name or path else os.path.split(archive)[1]

        if utils.check_ignore_list(temp_p) and not gallerydb.GalleryDB.check_exists(temp_p, self.galleries_from_db, False):
            log_i('Creating gallery: {}'.format(folder_name))
            new_gallery = gallerydb.Gallery()
            metafile = utils.GMetafile()
            if os.path.isdir(temp_p):
                con = os.scandir(temp_p) #all of content in the gallery folder
                log_i('Gallery source is a directory')
                chapters = sorted([sub.path for sub in con if sub.is_dir() or sub.name.endswith(utils.ARCHIVE_FILES)])\
                    if do_chapters else [] #subfolders
                # if gallery has chapters divided into sub folders
                if len(chapters) != 0:
                    log_i('Gallery has {} chapters'.format(len(chapters)))
                    for ch in chapters:
                        chap = new_gallery.chapters.create_chapter()
                        chap.title = utils.title_parser(ch)['title']
                        chap.path = os.path.join(path, ch)
                        chap.pages = len([x for x in os.scandir(chap.path) if x.name.lower().endswith(utils.IMG_FILES)])
                        metafile.update(utils.GMetafile(chap.path))

                else: #else assume that all images are in gallery folder
                    chap = new_gallery.chapters.create_chapter()
                    chap.title = utils.title_parser(os.path.split(path)[1])['title']
                    chap.path = path
                    metafile.update(utils.GMetafile(chap.path))
                    chap.pages = len(list(os.scandir(path)))
                
                parsed = utils.title_parser(folder_name)
            else:
                try:
                    if is_archive or temp_p.endswith(utils.ARCHIVE_FILES):
                        log_i('Gallery source is an archive')
                        contents = utils.check_archive(temp_p)
                        if contents:
                            new_gallery.is_archive = 1
                            new_gallery.path_in_archive = '' if not is_archive else path
                            if folder_name.endswith('/'):
                                folder_name = folder_name[:-1]
                                fn = os.path.split(folder_name)
                                folder_name = fn[1] or fn[2]
                            folder_name = folder_name.replace('/','')
                            if folder_name.endswith(utils.ARCHIVE_FILES):
                                n = folder_name
                                for ext in utils.ARCHIVE_FILES:
                                    n = n.replace(ext, '')
                                parsed = utils.title_parser(n)
                            else:
                                parsed = utils.title_parser(folder_name)
                                                
                            if do_chapters:
                                archive_g = sorted(contents)
                                if not archive_g:
                                    log_w('No chapters found for {}'.format(temp_p))
                                    raise ValueError
                                for g in archive_g:
                                    chap = new_gallery.chapters.create_chapter()
                                    chap.in_archive = 1
                                    chap.title = parsed['title'] if not g else utils.title_parser(g.replace('/', ''))['title']
                                    chap.path = g
                                    metafile.update(utils.GMetafile(g, temp_p))
                                    with utils.ArchiveFile(temp_p) as arch:
                                        chap.pages = len([x for x in arch.dir_contents(g) if x.lower().endswith(utils.IMG_FILES)])
                            else:
                                chap = new_gallery.chapters.create_chapter()
                                chap.title = utils.title_parser(os.path.split(path)[1])['title']
                                chap.in_archive = 1
                                chap.path = path
                                metafile.update(utils.GMetafile(path, temp_p))
                                with utils.ArchiveFile(temp_p) as arch:
                                    chap.pages = len(arch.dir_contents(''))
                        else:
                            raise ValueError
                    else:
                        raise ValueError
                except ValueError:
                    log_w('Skipped {} in local search'.format(path))
                    self.skipped_paths.append((temp_p, 'Empty archive',))
                    return
                except app_constants.CreateArchiveFail:
                    log_w('Skipped {} in local search'.format(path))
                    self.skipped_paths.append((temp_p, 'Error creating archive',))
                    return
                except app_constants.TitleParsingError:
                    log_w('Skipped {} in local search'.format(path))
                    self.skipped_paths.append((temp_p, 'Error while parsing folder/archive name',))
                    return

            new_gallery.title = parsed['title']
            new_gallery.path = temp_p
            new_gallery.artist = parsed['artist']
            new_gallery.language = parsed['language']
            new_gallery.info = ""
            new_gallery.view = app_constants.ViewType.Addition
            metafile.apply_gallery(new_gallery)

            if app_constants.MOVE_IMPORTED_GALLERIES and not app_constants.OVERRIDE_MOVE_IMPORTED_IN_FETCH:
                new_gallery.move_gallery()

            self.LOCAL_EMITTER.emit(new_gallery)
            self._data.append(new_gallery)
            log_i('Gallery successful created: {}'.format(folder_name))
            return True
        else:
            log_i('Gallery already exists or ignored: {}'.format(folder_name))
            self.skipped_paths.append((temp_p, 'Already exists or ignored'))
            return False

    def local(self, s_path=None):
        """
        Do a local search in the given series_path.
        """
        self._data.clear()
        if s_path:
            self.series_path = s_path
        try:
            gallery_l = sorted([p.name for p in os.scandir(self.series_path)]) #list of folders in the "Gallery" folder
            mixed = False
        except TypeError:
            gallery_l = self.series_path
            mixed = True
        if len(gallery_l) != 0: # if gallery path list is not empty
            log_i('Gallery folder is not empty')
            if len(self.galleries_from_db) != len(app_constants.GALLERY_DATA):
                self._refresh_filter_list()
            self.DATA_COUNT.emit(len(gallery_l)) #tell model how many items are going to be added
            log_i('Received {} paths'.format(len(gallery_l)))
            progress = 0

            for folder_name in gallery_l: # folder_name = gallery folder title
                self._curr_gallery = folder_name
                if mixed:
                    path = folder_name
                    folder_name = os.path.split(path)[1]
                else:
                    path = os.path.join(self.series_path, folder_name)
                if app_constants.SUBFOLDER_AS_GALLERY or app_constants.OVERRIDE_SUBFOLDER_AS_GALLERY:
                    if app_constants.OVERRIDE_SUBFOLDER_AS_GALLERY:
                        app_constants.OVERRIDE_SUBFOLDER_AS_GALLERY = False
                    log_i("Treating each subfolder as gallery")
                    if os.path.isdir(path):
                        gallery_folders, gallery_archives = utils.recursive_gallery_check(path)
                        for gs in gallery_folders:
                            self.create_gallery(gs, os.path.split(gs)[1], False)
                        p_saving = {}
                        for gs in gallery_archives:
                            self.create_gallery(gs[0], os.path.split(gs[0])[1], False, archive=gs[1])
                    elif path.endswith(utils.ARCHIVE_FILES):
                        for g in utils.check_archive(path):
                            self.create_gallery(g, os.path.split(g)[1], False, archive=path)
                else:
                    try:
                        if os.path.isdir(path):
                            if not list(os.scandir(path)):
                                raise ValueError
                        elif not path.endswith(utils.ARCHIVE_FILES):
                            raise NotADirectoryError

                        log_i("Treating each subfolder as chapter")
                        self.create_gallery(path, folder_name, do_chapters=True)

                    except ValueError:
                        self.skipped_paths.append((path, 'Empty directory'))
                        log_w('Directory is empty: {}'.format(path))
                    except NotADirectoryError:
                        self.skipped_paths.append((path, 'Unsupported file'))
                        log_w('Unsupported file: {}'.format(path))

                progress += 1 # update the progress bar
                self.PROGRESS.emit(progress)
        else: # if gallery folder is empty
            log_e('Local search error: Invalid directory')
            log_e('Gallery folder is empty')
            app_constants.OVERRIDE_MOVE_IMPORTED_IN_FETCH = True # sanity check
            self.FINISHED.emit(False)
            # might want to include an error message
        app_constants.OVERRIDE_MOVE_IMPORTED_IN_FETCH = False
        # everything went well
        log_i('Local search: OK')
        log_i('Created {} items'.format(len(self._data)))
        if self._to_queue_container:
            for x in self._data:
                self._galleries_queue.put(x)
        else:
            self.FINISHED.emit(self._data)
        if self.skipped_paths:
            self.SKIPPED.emit(self.skipped_paths)

    def _return_gallery_metadata(self, gallery):
        "Emits galleries"
        assert isinstance(gallery, gallerydb.Gallery)
        if gallery:
            gallery.exed = 1
            self.GALLERY_EMITTER.emit(gallery, None, False)
            log_d('Emitted gallery: {}'.format(gallery.title))

    def fetch_metadata(self, gallery=None, hen=None, proc=False):
        """
        Puts gallery in queue for metadata fetching. Applies received galleries and sends
        them to gallery model.
        Set proc to true if you want to process the queue immediately
        """
        if gallery:
            log_i("Fetching metadata for gallery: {}".format(gallery.title))
            log_i("Adding to queue: {}".format(gallery.title))
            if proc:
                metadata = hen.add_to_queue(gallery.temp_url, True)
            else:
                metadata = hen.add_to_queue(gallery.temp_url)
            self.galleries_in_queue.append(gallery)
        else:
            metadata = hen.add_to_queue(proc=True)

        if metadata == 1: # Gallery is now put in queue
            return None
        # We received something from get_metadata
        if not metadata: # metadata fetching failed
            if gallery:
                self.error_galleries.append((gallery, "No metadata found for gallery"))
                log_i("An error occured while fetching metadata with gallery: {}".format(
                    gallery.title))
            return None
        self.AUTO_METADATA_PROGRESS.emit("Applying metadata...")

        for x, g in enumerate(self.galleries_in_queue, 1):
            try:
                data = metadata[g.temp_url]
            except KeyError:
                self.AUTO_METADATA_PROGRESS.emit("No metadata found for gallery: {}".format(g.title))
                self.error_galleries.append((g, "No metadata found for gallery"))
                log_w("No metadata found for gallery: {}".format(g.title))
                continue
            log_i('({}/{}) Applying metadata for gallery: {}'.format(x, len(self.galleries_in_queue),
                                                            g.title))
            g = hen.apply_metadata(g, data, append = not app_constants.REPLACE_METADATA)
            self._return_gallery_metadata(g)
            log_i('Successfully applied metadata to gallery: {}'.format(g.title))
        self.galleries_in_queue.clear()
        self.AUTO_METADATA_PROGRESS.emit('Finished applying metadata')
        log_i('Finished applying metadata')

    def _auto_metadata_process(self, galleries, hen, valid_url, **kwargs):
        FUZZ_CONFIDENCE_THRESHOLD = app_constants.FUZZ_CONFIDENCE_THRESHOLD
        RETRY_DELAY_SECONDS = 3
        RETRY_FALLBACK_DELAY_SECONDS = max(RETRY_DELAY_SECONDS - 2, 1)
        # A short or generic title can clear the threshold dozens of times over. Logging every
        # one of those buries the run, so only the head of the ranking is written out.
        MAX_LOGGED_CANDIDATES = 10

        hen.LAST_USED = time.time()
        self.AUTO_METADATA_PROGRESS.emit("Checking gallery urls...")
        if len(galleries) == 1: log_d('Fetching metadata for 1 gallery')
        else:                   log_d(f'Fetching metadata for {len(galleries)} galleries')

        checked_pre_url_galleries = []
        multiple_hit_galleries = []

        def process_and_filter_results(results, query, local_title, local_language, language_known):
            """Uses thefuzz to filter, sort, and verify search results. Returns an empty list on failure.

            A result carrying no title cannot be verified against the local one. Such a result is
            kept with a score of None ("unverified") rather than being scored 0, because some
            sources (panda.chaika.moe) resolve a gallery without ever reporting its title.
            """
            if not results or query not in results:
                return [], False

            title_url_list = results[query]
            log_d(f"Initial search returned {len(title_url_list)} result(s). Filtering with thefuzz...")

            # 1. Score each result, or mark it unverified when the source gave us no title.
            #    Both sides are canonicalised so the site's extra decorations don't drag an
            #    otherwise exact match below the threshold.
            local_numbers = title_numbers(local_title)
            local_is_cjk = bool(CJK_RE.search(local_title))
            local_language = (local_language or '').strip().lower()
            dropped_for_language = False
            filtered = []
            number_mismatches = []
            for title, url in title_url_list:
                if not title:
                    filtered.append((title, url, None))
                    continue

                scores = []
                cross_script = False
                for form in match_forms(title):
                    if title_numbers(form) != local_numbers:
                        # Different volume, chapter or sequel. Disqualifying whatever it
                        # scores, since these sit close enough to be picked by mistake.
                        continue
                    if bool(CJK_RE.search(form)) != local_is_cjk:
                        # A Japanese folder name and a romaji site title share no characters,
                        # so a ratio between them reads as 0 however right the hit is. Unverified
                        # rather than wrong: the search matched it on the site's own title.
                        cross_script = True
                        continue
                    scores.append(fuzz.ratio(local_title, form))

                if scores:
                    filtered.append((title, url, max(scores)))
                elif cross_script:
                    filtered.append((title, url, None))
                else:
                    number_mismatches.append(title)

            if number_mismatches:
                log_i(f"Discarded {len(number_mismatches)} result(s) with different numbering (local: {sorted(local_numbers) or 'none'}):")
                for title in number_mismatches[:3]:
                    log_i(f"  - '{title}'")

            # 2. Keep results that meet the confidence threshold, plus the unverified ones
            confident_results_with_scores = [
                (title, url, score) for title, url, score in filtered
                if score is None or score >= FUZZ_CONFIDENCE_THRESHOLD
            ]

            # 2b. A release translated into another language is a different release. Needs the
            #      local language to be known rather than defaulted, and to be a translation:
            #      an untranslated listing states no language for this to disagree with.
            if (app_constants.FILTER_RESULTS_BY_LANGUAGE and language_known
                    and local_language in LANGUAGE_TAGS
                    and local_language not in UNTRANSLATED_LANGUAGES):
                kept, wrong_language = [], []
                for result in confident_results_with_scores:
                    languages = title_languages(result[0] or '')
                    (wrong_language if languages and local_language not in languages else kept).append(result)
                if wrong_language:
                    log_i(f"Discarded {len(wrong_language)} result(s) not in {local_language}:")
                    for title, _, _ in wrong_language[:3]:
                        log_i(f"  - '{title}'")
                confident_results_with_scores = kept
                dropped_for_language = bool(wrong_language)

            # 3. Best score first, with a same-language hit ahead of an equally good one in
            #    another language. Ties are common, and the source lists newest first, which
            #    floats a recent translation above the release actually held locally.
            def rank(item):
                title, _, score = item
                languages = title_languages(title or '')
                same_language = (local_language in UNTRANSLATED_LANGUAGES if not languages
                                 else local_language in languages)
                return (-1 if score is None else score, same_language)

            sorted_confident_results = sorted(confident_results_with_scores, key=rank, reverse=True)

            # At info rather than debug: this ranking is the only record of why one candidate
            # was offered ahead of another, and it is needed from logs collected without debug.
            log_i(f"Found {len(sorted_confident_results)} confident result(s) (threshold: {FUZZ_CONFIDENCE_THRESHOLD}). Sorting them:")
            for title, _, score in sorted_confident_results[:MAX_LOGGED_CANDIDATES]:
                log_i(f"  - Score: {'unverified' if score is None else score} for '{title}'")
            if len(sorted_confident_results) > MAX_LOGGED_CANDIDATES:
                log_i(f"  - ... and {len(sorted_confident_results) - MAX_LOGGED_CANDIDATES} more")

            # Nothing cleared the bar, so report the closest misses. Without these the log
            # cannot distinguish "the source returned nothing" from "the threshold is too high".
            if not sorted_confident_results and filtered:
                near_misses = sorted(filtered, key=lambda item: item[2] or 0, reverse=True)[:3]
                log_i(f"Best of {len(filtered)} rejected result(s):")
                for title, _, score in near_misses:
                    log_i(f"  - Score: {score} for '{title}'")

            # 4. Return the results, and whether anything was dropped for its language: a lone
            #    survivor of that is the least verified candidate, not the most.
            return sorted_confident_results, dropped_for_language

        # Helper function to reduce code duplication
        def _try_search(query, local_title, local_language, language_known):
            """Performs a search and returns the confident results."""
            found_results = hen.search(query)
            if found_results == 'error':
                return 'error'
            return process_and_filter_results(found_results, query, local_title, local_language,
                                              language_known)

        def _select_match(gallery_obj, confident_results, kind, dropped_for_language=False):
            """Takes the URL from an unambiguous hit, or queues the gallery for the picker.

            Only called with a non-empty result list, so it always resolves to something and
            returns True to mark the search as successful.
            """
            if dropped_for_language and len(confident_results) == 1:
                # Nothing weighed this against the alternatives, because the filter removed
                # them - and a tag shape the parser cannot read survives that as "states no
                # language". Ask, rather than apply a language nobody checked.
                log_i(f"One {kind} match survived the language filter; asking rather than applying.")
                multiple_hit_galleries.append([gallery_obj, [(t, u) for t, u, _ in confident_results]])
                return True

            perfect_matches = [res for res in confident_results if res[2] == 100]

            if len(perfect_matches) == 1:
                log_i(f"Single perfect {kind} match (score 100) found. Selecting automatically.")
                gallery_obj.temp_url = perfect_matches[0][1]
            elif len(confident_results) == 1:
                log_i(f"Single confident {kind} match found and verified.")
                gallery_obj.temp_url = confident_results[0][1]
            else:
                choices_to_present = perfect_matches if perfect_matches else confident_results
                log_i(f"Multiple ({len(choices_to_present)}) confident {kind} matches found.")
                multiple_hit_galleries.append([gallery_obj, [(t, u) for t, u, _ in choices_to_present]])
            return True

        for x, gallery in enumerate(galleries, 1):
            search_successful = False
            log_i(f"--- Processing gallery {x}/{len(galleries)}: {gallery.title} ---")
            self.AUTO_METADATA_PROGRESS.emit(f"({x}/{len(galleries)}) Searching for: {gallery.title}")

            # --- Stage 0: Pre-flight checks ---
            # coming from GalleryDialog
            if hasattr(gallery, "_g_dialog_url") and gallery._g_dialog_url:
                if self._hen_supports(gallery._g_dialog_url, hen):
                    gallery.temp_url = gallery._g_dialog_url
                    checked_pre_url_galleries.append(gallery)
                else:
                    # The url belongs to another source. Hand the gallery to the fallback pass
                    # that can read it, rather than to an api that cannot parse it.
                    log_i("Gallery url belongs to a different source, deferring to the fallback")
                    self.error_galleries.append((gallery, "Gallery url is not supported by this source"))
                # to process even if this gallery is last and fails
                if x == len(galleries): self.fetch_metadata(hen=hen)
                continue

            # A gallery imported before its metadata file was understood carries no link,
            # while the file beside it names the exact gallery. Reading it turns a search that
            # has already failed into a direct fetch.
            if not gallery.link and app_constants.USE_GALLERY_LINK:
                gallery.link = self._metafile_link(gallery)

            if gallery.link and app_constants.USE_GALLERY_LINK:
                log_i("Using existing gallery url")
                if self._hen_supports(gallery.link, hen):
                    # convert g.e-h to e-h
                    gallery.link = pewnet.HenManager.gtoEh(gallery.link)
                    gallery.temp_url = gallery.link
                    checked_pre_url_galleries.append(gallery)
                    if x == len(galleries): self.fetch_metadata(hen=hen)
                    continue

                # The url is usable, just not by this source. Hand the gallery straight to the
                # fallback pass that owns it: searching for a gallery we already have the url
                # for only burns requests against an api that will never match it.
                if any(self._hen_supports(gallery.link, h) for h in self._hen_list):
                    log_i("Gallery url belongs to a fallback source, skipping search")
                    self.error_galleries.append((gallery, "Gallery url is not supported by this source"))
                    if x == len(galleries): self.fetch_metadata(hen=hen)
                    continue
                # Otherwise no configured source can read it, so fall through to searching.

            # Sorting uses the language whatever its provenance, since ordering the choices
            # differently cannot lose anything; only discarding needs it to be a fact.
            gallery_language_known = language_is_known(gallery)

            # --- Common: the title every search hit is verified against ---
            # path_title is the raw folder name, still carrying the full-width stand-ins a
            # filesystem forces onto forbidden characters. canonical_title folds both sides back.
            compare_title = canonical_title(gallery.path_title)

            # --- Stage 1: Image Hash Search (opt-in) ---
            # Off by default: it only matches when the local files are byte-identical to the ones
            # the source hashed, which recompressing or converting a gallery breaks.
            if app_constants.USE_HASH_SEARCH:
                log_i("Attempt 1: Image Hash Search")
                g_hash = None
                try:
                    if gallery.hashes:
                        g_hash = gallery.hashes[random.randint(0, len(gallery.hashes)-1)]
                    else:
                        hash_dict = gallerydb.execute(gallerydb.HashDB.gen_gallery_hash, False, gallery, 0, 'mid', False)
                        if hash_dict: g_hash = hash_dict['mid']
                except (app_constants.CreateArchiveFail, ValueError):
                    log_w("Could not get a valid hash for gallery.")
                    g_hash = None

                if g_hash:
                    search_result = _try_search(g_hash, compare_title, gallery.language,
                                                gallery_language_known)
                    if search_result == 'error':
                        app_constants.GLOBAL_EHEN_LOCK = False; self.FINISHED.emit(True); return

                    confident_results_with_scores, dropped_for_language = search_result
                    if confident_results_with_scores:
                        search_successful = _select_match(gallery, confident_results_with_scores,
                                                          'hash', dropped_for_language)
                else:
                    log_w("No hash available for gallery.")

                if not search_successful:
                    log_i(f"Hash search failed. Waiting {RETRY_DELAY_SECONDS}s before falling back to title search.")
                    time.sleep(RETRY_DELAY_SECONDS)

            # --- Stage 2: Title Search ---
            if not search_successful:
                queries = search_queries(gallery)
                if not queries:
                    log_w('Gallery has no searchable title, skipping')
                    self.error_galleries.append((gallery, "Gallery has no searchable title"))
                    if x == len(galleries): self.fetch_metadata(hen=hen)
                    continue

                log_i(f"--- Title Search ({len(queries)} query variation(s)) ---")
                for i, query in enumerate(queries):
                    log_i(f"Attempt 2.{chr(97+i)}: Searching with query: {query}")
                    search_result = _try_search(query, compare_title, gallery.language,
                                                gallery_language_known)

                    if search_result == 'error':
                        app_constants.GLOBAL_EHEN_LOCK = False; self.FINISHED.emit(True); return

                    confident_results_with_scores, dropped_for_language = search_result
                    if confident_results_with_scores:
                        search_successful = _select_match(gallery, confident_results_with_scores,
                                                          'title', dropped_for_language)
                        break

                    if i < len(queries) - 1:  # Don't sleep after the last attempt
                        time.sleep(RETRY_FALLBACK_DELAY_SECONDS)

            # --- Process Final Results ---
            if search_successful:
                if gallery.temp_url:
                    self.AUTO_METADATA_PROGRESS.emit(f"({x}/{len(galleries)}) Adding to queue: {gallery.title}")
                    self.fetch_metadata(gallery, hen, x == len(galleries))
            else:
                self.error_galleries.append((gallery, "Could not find a confident URL match for gallery"))
                self.AUTO_METADATA_PROGRESS.emit(f"Could not find url for gallery: {gallery.title}")
                log_e(f'All search attempts failed for gallery: {gallery.title}')
                if x == len(galleries): self.fetch_metadata(hen=hen)

        if checked_pre_url_galleries:
            for x, gallery in enumerate(checked_pre_url_galleries, 1):
                self.AUTO_METADATA_PROGRESS.emit("({}/{}) Adding to queue: {}".format(
                    x, len(checked_pre_url_galleries), gallery.title))
                self.fetch_metadata(gallery, hen, x == len(checked_pre_url_galleries))

        if multiple_hit_galleries:
            previews = self._candidate_previews(multiple_hit_galleries, hen)
            # Cover urls point at the source's own image host, which serves a logged in user
            # only. One session is built here and reused for every cover in the run.
            preview_session = hen.image_session() if previews else None
            skip_all = False
            multiple_hit_g_queue = []
            for x, g_data in enumerate(multiple_hit_galleries, 1):
                gallery = g_data[0]
                log_w("Multiple galleries found for gallery: {}".format(gallery.title))
                if skip_all:
                    log_w("Skipping gallery")
                    continue
                title_url_list, thumbnails = picker_labels(g_data[1], previews)

                self.AUTO_METADATA_PROGRESS.emit("({}/{}) Multiple galleries found for gallery: {}".format(
                    x, len(multiple_hit_galleries), gallery.title))
                app_constants.SYSTEM_TRAY.showMessage('Happypanda', 'Multiple galleries found for gallery:\n{}'.format(gallery.title),
                                    minimized=True)
                self.GALLERY_PICKER.emit(gallery, title_url_list, self.GALLERY_PICKER_QUEUE,
                                         {'position': (x, len(multiple_hit_galleries)),
                                          'thumbnails': thumbnails,
                                          # So that noting a candidate reads its native title
                                          # from the api's own field rather than re-deriving it
                                          # from the row it is displayed on.
                                          'previews': previews,
                                          'session': preview_session})
                user_choice = self.GALLERY_PICKER_QUEUE.get()

                if user_choice == None:
                    skip_all = True
                if not user_choice:
                    log_w("Skipping gallery")
                    continue

                title, url = user_choice
                gallery.temp_url = url
                if not gallery.link:
                    gallery.link = url
                    if isinstance(hen, (pewnet.EHen, pewnet.ExHen)):
                        self.GALLERY_EMITTER.emit(gallery, None, None)
                self.AUTO_METADATA_PROGRESS.emit("({}/{}) Adding to queue: {}".format(
                    x, len(multiple_hit_galleries), gallery.title))
                multiple_hit_g_queue.append(gallery)

            for x, g in enumerate(multiple_hit_g_queue, 1):
                self.fetch_metadata(g, hen, x == len(multiple_hit_g_queue))


    def _metafile_link(self, gallery):
        """The gallery url stated by a metadata file in the gallery's own folder, or ''.

        Only the url is taken. The rest of such a file is a snapshot from download time, and
        applying it here would overwrite the stored metadata with a stale copy of itself
        moments before the fetch replaces it with a current one.
        """
        try:
            if not gallery.path or not os.path.isdir(gallery.path):
                return ''
            link = utils.GMetafile(gallery.path).metadata['link']
        except Exception:
            log.exception('Could not read the metadata file beside the gallery')
            return ''
        if link:
            log_i('Found a gallery url in the metadata file beside the gallery')
        return link

    def _candidate_previews(self, multiple_hit_galleries, hen):
        """The native title and cover url of every candidate across the given galleries.

        A search listing carries one title, usually romaji, and no cover, which is not enough to
        tell two candidates for the same work apart when the local folder name is in Japanese.
        The api returns both titles and a thumbnail url and takes MAX_GDATA_URLS galleries per
        call, so candidates are deduplicated across the whole set and looked up in batches: a
        few hundred of them cost a handful of requests, made once, rather than one call each.

        Returns {url: {'native': title, 'thumb': url, 'creators': (name, ...)}}, empty when the
        lookup cannot be made. Kept whole rather than reduced to the fields a row shows, so
        that a field can be read back by name instead of re-derived from a display string.
        """
        if not app_constants.PICKER_PREVIEWS or not isinstance(hen, pewnet.EHen):
            return {}

        urls = []
        for _, title_url_list in multiple_hit_galleries:
            for _, url in title_url_list:
                if url not in urls:
                    urls.append(url)

        chunk_size = pewnet.EHen.MAX_GDATA_URLS
        chunks = [urls[i:i + chunk_size] for i in range(0, len(urls), chunk_size)]
        previews = {}
        for chunk in chunks:
            try:
                result = hen.get_metadata(chunk)
                if not result or result == 'error':
                    continue
                metadata_json, gid_to_url = result
                # The raw response rather than parse_metadata's, because none of this may reach
                # anything that writes to a gallery - it exists only to be looked at.
                for entry in metadata_json.get('gmetadata', []):
                    url = gid_to_url.get(entry.get('gid'))
                    if url and 'error' not in entry:
                        # Sorted rather than the set api_creators returns, so one candidate's
                        # label reads the same on every run.
                        creators = tuple(sorted(tagreaders.api_creators(entry)))
                        previews[url] = {'native': entry.get('title_jpn', ''),
                                         'thumb': entry.get('thumb', ''),
                                         'creators': creators}
            except Exception:
                log.exception('Could not look up previews for the gallery picker')

        log_i(f'Looked up previews for {len(previews)}/{len(urls)} candidate(s) '
              f'in {len(chunks)} request(s).')
        return previews

    def _hen_supports(self, url, hen):
        """True when the given hen can actually fetch metadata for this url.

        Accepts a hen instance or class. Looser than comparing against valid_url: e-hentai and
        exhentai share the gallery id/token url format, so either host is readable by either.
        """
        site = self._website_checker(url)
        if not site:
            return False
        hen_cls = hen if isinstance(hen, type) else type(hen)
        if issubclass(hen_cls, pewnet.ChaikaHen):
            return site == 'chaikahen'
        return site in ('ehen', 'exhen')

    def _website_checker(self, url):
        log_i("Checking if valid URL: {}".format(url))
        if not url:
            return None
        # Both the legacy g.e-hentai.org host and the current e-hentai.org one, since gtoEh
        # rewrites stored links to the latter and they have to still validate afterwards.
        if 'e-hentai.org/g/' in url:
            return 'ehen'
        elif 'exhentai.org/g/' in url:
            return 'exhen'
        elif 'panda.chaika.moe/archive/' in url or 'panda.chaika.moe/gallery/' in url:
            return 'chaikahen'
        else:
            log_e('Invalid URL')
            return None

    def auto_web_metadata(self):
        """
        Auto fetches metadata for the provided list of galleries.
        Appends or replaces metadata with the new fetched metadata.
        """
        log_i('Initiating auto metadata fetcher')
        self._hen_list = pewnet.hen_list_init()
        if self.galleries and not app_constants.GLOBAL_EHEN_LOCK:
            log_i('Auto metadata fetcher is now running')
            if app_constants.USE_GLOBAL_EHEN_LOCK:
                app_constants.GLOBAL_EHEN_LOCK = True

            def fetch_cancelled(rsn=''):
                if rsn:
                    self.AUTO_METADATA_PROGRESS.emit("Metadata fetching cancelled: {}".format(rsn))
                    app_constants.SYSTEM_TRAY.showMessage("Metadata", "Metadata fetching cancelled: {}".format(rsn), minimized=True)
                else:
                    self.AUTO_METADATA_PROGRESS.emit("Metadata fetching cancelled!")
                    app_constants.SYSTEM_TRAY.showMessage("Metadata", "Metadata fetching cancelled!", minimized=True)
                app_constants.GLOBAL_EHEN_LOCK = False
                self.FINISHED.emit(False)

            if 'exhentai' in self._default_ehen_url:
                try:
                    exprops = settings.ExProperties()
                    hen = pewnet.ExHen(exprops.cookies)
                    if hen.check_login(exprops.cookies):
                        valid_url = 'exhen'
                        log_i("using exhen")
                    else:
                        raise ValueError
                except ValueError:
                    hen = pewnet.EHen()
                    valid_url = 'ehen'
                    log_i("using ehen")
            else:
                hen = pewnet.EHen()
                valid_url = 'ehen'
                log_i("Using Exhentai")
            try:
                self._auto_metadata_process(self.galleries, hen, valid_url)
            except app_constants.MetadataFetchFail as err:
                fetch_cancelled(err)
                return
            except Exception:
                log.exception('Auto metadata fetcher failed')
                fetch_cancelled('unexpected error, see happypanda.log')
                return

            if self.error_galleries:
                if self._hen_list:
                    log_i("Using fallback source")
                    self.AUTO_METADATA_PROGRESS.emit("Using fallback source")
                    for hen in self._hen_list:
                        if not self.error_galleries:
                            break
                        galleries = [x[0] for x in self.error_galleries]
                        self.error_galleries.clear()
                        
                        valid_url = ""

                        if hen == pewnet.ChaikaHen:
                            valid_url = "chaikahen"
                            log_i("using chaika hen")
                        # CommonHen.QUEUE is shared by every hen class, so anything the previous
                        # source left behind would be fetched against this one's api.
                        pewnet.CommonHen.QUEUE.clear()
                        self.galleries_in_queue.clear()
                        try:
                            self._auto_metadata_process(galleries, hen(), valid_url)
                        except app_constants.MetadataFetchFail as err:
                            fetch_cancelled(err)
                            return
                        except Exception:
                            log.exception('Fallback metadata fetcher failed')
                            fetch_cancelled('unexpected error, see happypanda.log')
                            return

            if not self.error_galleries:
                self.AUTO_METADATA_PROGRESS.emit('Successfully fetched metadata! Went through {} galleries successfully!'.format(len(self.galleries)))
                app_constants.SYSTEM_TRAY.showMessage('Successfully fetched metadata', 'Went through {} galleries successfully!'.format(len(self.galleries)), minimized=True)
                self.FINISHED.emit(True)
            else:
                self.AUTO_METADATA_PROGRESS.emit('Finished fetching metadata! Could not fetch metadata for {} galleries. Check happypanda.log for more details!'.format(len(self.error_galleries)))
                app_constants.SYSTEM_TRAY.showMessage('Finished fetching metadata',
                                            'Could not fetch metadata for {} galleries. Check happypanda.log for more details!'.format(len(self.error_galleries)),
                                            minimized=True)
                for tup in self.error_galleries:
                    log_e("{}: {}".format(tup[1], tup[0].title))
                self.FINISHED.emit(self.error_galleries)
            log_i('Auto metadata fetcher is done')
            app_constants.GLOBAL_EHEN_LOCK = False
        else:
            log_e('Auto metadata fetcher is already running')
            self.AUTO_METADATA_PROGRESS.emit('Auto metadata fetcher is already running!')
            self.FINISHED.emit(False)

