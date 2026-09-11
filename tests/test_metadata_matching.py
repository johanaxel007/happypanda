"""Regression tests for online metadata matching.

Every case here is taken from a gallery that actually failed to fetch metadata against a
real source, not from an invented example. The title strings are the ones that appeared in
happypanda.log, so a failure means a specific, previously observed bug is back.

The application modules import each other flatly, and app_constants refers to
gallerydb.Gallery while gallerydb imports app_constants, so the import order below is
load bearing: importing fetch first leaves gallerydb half initialised.
"""

import pytest

import app_constants  # noqa: F401  (must precede gallerydb)
import gallerydb
import fetch
import pewnet
import settings
import utils
from formatters import title_formatter, TranslationStyle
from thefuzz import fuzz


# --- Title normalisation ---------------------------------------------------------------

@pytest.mark.parametrize('raw, expected', [
    # The full-width bar is what a filesystem leaves behind for the JP|EN separator. Folding
    # it to ASCII is what lets the separator be found at all.
    ('Itsumo Watashi de Shikotte Kurete Arigatou ｜ Thanks for Always Using Me',
     'Itsumo Watashi de Shikotte Kurete Arigatou | Thanks for Always Using Me'),
    ('Gouzentaru Ichigura Kitsune Tachi to no Chigiri ＜Kaga Hen＞',
     'Gouzentaru Ichigura Kitsune Tachi to no Chigiri <Kaga Hen>'),
    ('Kabeshiri Usagi Boukensha, Kusuri de Kyousei Hatsujou!？',
     'Kabeshiri Usagi Boukensha, Kusuri de Kyousei Hatsujou!?'),
])
def test_search_style_folds_full_width_to_ascii(raw, expected):
    assert title_formatter.format_title(raw, translation_style=TranslationStyle.SEARCH) == expected


def test_search_style_is_the_inverse_of_the_default_style():
    """The default style writes ASCII out as full width; SEARCH has to bring it back."""
    ascii_title = 'A<B>C:D"E/F|G?H*I'
    stored = title_formatter.format_title(ascii_title, translation_style=TranslationStyle.DEFAULT)
    assert stored != ascii_title
    assert title_formatter.format_title(stored, translation_style=TranslationStyle.SEARCH) == ascii_title


# --- Separator handling ----------------------------------------------------------------

@pytest.mark.parametrize('raw, expected', [
    # A real separator, full width as stored on disk.
    ('[Toneri Dan (Yoshio Ereki)] Itsumo Watashi de Shikotte Kurete Arigatou ｜ Thanks',
     '[Toneri Dan (Yoshio Ereki)] Itsumo Watashi de Shikotte Kurete Arigatou'),
    # Separator deleted rather than substituted: the two spaces around it are all that is left.
    ('[Riku no Kotoutei (Shayo)] Inaka ni wa Kore kurai Goraku ga Nai 1  '
     'Not Much Else to Do in the Countryside 1 [English]',
     '[Riku no Kotoutei (Shayo)] Inaka ni wa Kore kurai Goraku ga Nai 1'),
    # No separator at all.
    ('[Shouwa Saishuu Sense (Hanauna)] Big Boobs JK Toilet Girl Debut [English]', ''),
    ('No separator anywhere here', ''),
    # The gap after a group prefix is not a separator; splitting there yields no title.
    ('[Circle (Artist)]  Title After A Gap', ''),
])
def test_split_on_separator(raw, expected):
    assert fetch.split_on_separator(raw) == expected


@pytest.mark.parametrize('raw, expected', [
    ('[Circle (Artist)] Some Title', 'Some Title'),
    ('[Aruma] Taisetsu na Kimi', 'Taisetsu na Kimi'),
    ('No prefix at all', ''),          # unchanged -> nothing to offer
    ('[OnlyAPrefix]', ''),             # nothing would be left
])
def test_strip_group_prefix(raw, expected):
    assert fetch.strip_group_prefix(raw) == expected


def test_match_forms_offers_each_half_of_a_pair():
    """A site title is often the whole JP|EN pair while the folder kept only one half."""
    forms = fetch.match_forms(
        "[TSF no F (Hiiragi Popura)] Yuusha Aku ni Ochiru | A Hero's Fall from Grace [English]")
    assert 'Yuusha Aku ni Ochiru' in forms
    assert "A Hero's Fall from Grace" in forms


def test_match_forms_offers_the_title_without_its_trailing_subtitle():
    """Doujin titles carry a '-Subtitle-' that a folder name routinely drops."""
    forms = fetch.match_forms(
        '(C103) [Aratoya (Arato Asato)] DaviGaki WakaraSex 3 '
        '-Ero Trap Dungeon wa Kiken ga Ippai- (Davi Artman)')
    assert 'DaviGaki WakaraSex 3' in forms
    assert fuzz.ratio(fetch.canonical_title('(C103) DaviGaki WakaraSex 3'),
                      'DaviGaki WakaraSex 3') == 100


def test_two_works_sharing_a_base_title_are_not_reduced_to_a_match():
    """Stripping the subtitle from the local title too would score these a perfect 100."""
    local = fetch.canonical_title('Title -Sub A-')
    best = max(fuzz.ratio(local, form)
               for form in fetch.match_forms('[X] Title -Sub B- [English]'))
    assert best < 100


def test_an_ordinary_hyphenated_ending_is_not_a_subtitle():
    assert fetch.match_forms('[X] Kaizoku Kyonyuu - Utage [English]') == ['Kaizoku Kyonyuu - Utage']


# --- Decoration stripping --------------------------------------------------------------

@pytest.mark.parametrize('raw, expected', [
    # A hyphenated word is not a decoration: '-' as a delimiter ate 'Guy-Turned-Girl'.
    ('My Slightly (Debauched) Life as a Guy-Turned-Girl',
     'My Slightly (Debauched) Life as a Guy-Turned-Girl'),
    # '_' as a delimiter ate the artist out of '[ma_shika (A_shika)]'.
    ('[ma_shika (A_shika)] Tenshi Hirotta kara Haramaseru ~Ojii-san Senyou Botebara~',
     '[ma_shika (A_shika)] Tenshi Hirotta kara Haramaseru ~Ojii-san Senyou Botebara~'),
    # A single decorated token still goes.
    ('Chouhatsu *Matenshi* Tenma-chan', 'Chouhatsu Tenma-chan'),
])
def test_search_form_only_strips_single_decorated_tokens(raw, expected):
    assert fetch.search_form(raw) == expected


# --- Scoring ---------------------------------------------------------------------------

def test_canonical_title_rescues_an_exact_match_from_its_decorations():
    """The site keeps [Artist], (Magazine), [English], [Digital]; the folder does not.

    fuzz.ratio is length sensitive, so this exact match used to score 63 and be discarded.
    """
    local = 'Taisetsu na Kimi to no Amai Koi ｜ Our Precious Sweet Love (COMIC LO 2020-01) {Mistvern}'
    site = ('[Aruma] Taisetsu na Kimi to no Amai Koi | Our Precious Sweet Love '
            '(COMIC LO 2020-01) [English] [Mistvern + Bigk40k] [Digital]')
    assert fuzz.ratio(fetch.canonical_title(local), fetch.canonical_title(site)) == 100


@pytest.mark.parametrize('local, site', [
    ('Kaizoku Kyonyuu ｜ The Big Breasted Pirate',
     '[BRAVE HEART petit (KOJIROU!)] Kaizoku Kyonyuu 2 | Big Breasted Pirate 2 [English]'),
    ('Schoolgirl Guide', '[Yumoteliuce] Schoolgirl Guide 2 (COMIC Bavel 2020-04) [English]'),
])
def test_a_sequel_never_reaches_a_perfect_score(local, site):
    """token_set_ratio and partial_ratio both score these 100, which auto-selects them."""
    assert fuzz.ratio(fetch.canonical_title(local), fetch.canonical_title(site)) < 100


@pytest.mark.parametrize('title, expected', [
    ('Gensou Kyonyuu 2 | Big Breasted Fantasy 2', {2}),   # a set, so a repeat does not matter
    ('Gensou Kyonyuu 2 | Big Breasted Fantasy', {2}),
    ('Kaizoku Kyonyuu | The Big Breasted Pirate', set()),
    ('Gessha 20-man ... 200 Thousand Yen per Month', {20, 200}),
    # A roman numeral is the number it denotes, in either notation, so the two forms of one
    # volume number agree instead of reading as two different works.
    ('DepthSinker II', {2}),
    ('DepthSinker2', {2}),
    ('Nana no Itazura Ⅱ', {2}),                          # the unicode roman numeral block
    ('Touhou Chitei Yousai VI', {6}),
    # A lone I, V or X is not a volume number: the pronoun, 'versus', and the crossover
    # multiplier respectively. The unicode forms of those three are left out to match.
    ('Nana no Itazura I', set()),
    ('Nana no Itazura Ⅰ', set()),
    ('Kino no Tabi no Erohon V - the Erotic World', set()),
    ('SuPE x FRO', set()),
    ('Sword Art Online X Fate', set()),
    # Case and word boundaries separate the numeral from the word: 'Ii' is Japanese for 'good',
    # and 'DRII' is a name rather than a numbered volume.
    ('Ii kara Watashi ni Dakarenasai!!', set()),
    ('DRII ~Katatsumuri Shoukougun~', set()),
])
def test_title_numbers(title, expected):
    assert fetch.title_numbers(title) == expected


# --- Chaika query cleaning -------------------------------------------------------------

@pytest.mark.parametrize('query, expected', [
    ('"Kaizoku Kyonyuu | Big Breasted Pirate" a:"brave heart petit"$ l:english$',
     'Kaizoku Kyonyuu | Big Breasted Pirate'),
    ('Some Truncated Title a:foo$ l:english$', 'Some Truncated Title'),
    ('Bare title no filters', 'Bare title no filters'),
])
def test_chaika_reduces_an_ehentai_query_to_a_bare_title(query, expected):
    """chaika has no filter syntax, so the e-hentai one has to come off before sending."""
    assert pewnet.ChaikaHen._plain_title(query) == expected


# --- Local title parsing ---------------------------------------------------------------

@pytest.mark.parametrize('folder, artist, language', [
    # No artist prefix: the trailing language tag must not be adopted as the artist.
    ('Guardian of Faith II [English]', '', 'English'),
    ('Fucked Into Submission 3 [English] [Digital]', '', 'English'),
    ('[English] Weird Leading Language Tag', '', 'English'),
    # Real prefixes still parse, including behind an event tag.
    ('[Shouwa Saishuu Sense (Hanauna)] Big Boobs JK Toilet Girl Debut [English]',
     'Shouwa Saishuu Sense (Hanauna)', 'English'),
    ('(Bokura no Love Live! 41) [Kitaku Jikan (Kitaku)] Oshiri 100% [English]',
     'Kitaku Jikan (Kitaku)', 'English'),
])
def test_title_parser_only_takes_a_leading_group_as_the_artist(folder, artist, language):
    utils.init_utils()
    parsed = utils.title_parser(folder)
    assert parsed['artist'] == artist
    assert parsed['language'] == language


# The language pickers offer four names and whatever the user has added, where the source tags
# dozens. A folder stating any of the rest has to keep its own language: reducing it to the
# default sends the wrong 'l:' filter on every search for it. Folder names taken from a library.

@pytest.mark.parametrize('folder, artist, language', [
    ('[BU-NONG] Closers - Seo Yuri to J no [Korean]', 'BU-NONG', 'Korean'),
    ('(COMIC1☆6) [Clesta (Cle Masahiro)] CL-orz 22 [Dutch] {Dutchguys} [Decensored]',
     'Clesta (Cle Masahiro)', 'Dutch'),
    # A language the pickers do not offer must not be adopted as the artist either.
    ('Some Title [Vietnamese]', '', 'Vietnamese'),
    # A tag in the same namespace that names what was done rather than what language it is in
    # is not one, so the gallery keeps the default.
    ('[Yamada] Some Title [Text cleaned]', 'Yamada', 'English'),
])
def test_title_parser_reads_a_language_the_pickers_do_not_offer(folder, artist, language,
                                                                monkeypatch):
    # The suite reads G_DEF_LANGUAGE from an untracked settings.ini, and an ambient value equal
    # to the one under test would let an unrecognised tag pass as a recognised one.
    monkeypatch.setattr(app_constants, 'G_DEF_LANGUAGE', 'English')
    monkeypatch.setattr(app_constants, 'G_CUSTOM_LANGUAGES', [])
    utils.init_utils()
    parsed = utils.title_parser(folder)
    assert parsed['artist'] == artist
    assert parsed['language'] == language


# --- End to end through _auto_metadata_process -----------------------------------------

class _StubHen(pewnet.EHen):
    """A source that returns a fixed result list and swallows the metadata fetch."""

    def __init__(self, results):
        self.results = results

    def search(self, query, **kwargs):
        return {query: self.results}

    def add_to_queue(self, url='', proc=False, parse=True):
        return 1


@pytest.fixture
def match_gallery(tmp_path, monkeypatch):
    """Runs one gallery through the real matching pipeline against a stub source.

    Returns the chosen url, or 'picker:<n>' when the gallery was sent to the chooser, or
    None when nothing matched.
    """
    class _Tray:
        def showMessage(self, *args, **kwargs):
            pass

    monkeypatch.setattr(app_constants, 'SYSTEM_TRAY', _Tray(), raising=False)
    # Pinned rather than ambient: the confidence threshold is a user setting read from an
    # untracked settings.ini, so a checkout would otherwise run these cases against whatever
    # configuration happens to be local - and against a changed default.
    monkeypatch.setattr(app_constants, 'FUZZ_CONFIDENCE_THRESHOLD', 70)

    def run(folder_name, results, artist='', language='English', threshold=None):
        if threshold is not None:
            monkeypatch.setattr(app_constants, 'FUZZ_CONFIDENCE_THRESHOLD', threshold)
        path = tmp_path / folder_name.replace('/', '_')[:120]
        path.mkdir(parents=True, exist_ok=True)

        gallery = gallerydb.Gallery()
        gallery.path = str(path)
        gallery.artist = artist
        gallery.language = language
        gallery.link = ''
        gallery.hashes = []
        gallery.title = folder_name

        fetcher = fetch.Fetch()
        fetcher._hen_list = []
        offered = []
        fetcher.GALLERY_PICKER.connect(
            lambda gal, choices, queue, extras: (offered.append((choices, extras)),
                                                 queue.put(None)))
        fetcher._auto_metadata_process([gallery], _StubHen(results), 'ehen')

        run.choices = [t for t, _ in offered[0][0]] if offered else []
        run.extras = offered[0][1] if offered else {}
        run.position = run.extras.get('position')

        if getattr(gallery, 'temp_url', ''):
            return gallery.temp_url
        if offered:
            return 'picker:{}'.format(len(offered[0][0]))
        return None

    return run


URL_A = 'https://e-hentai.org/g/1/a/'
URL_B = 'https://e-hentai.org/g/2/b/'
URL_C = 'https://e-hentai.org/g/3/c/'


def test_exact_match_buried_in_decorations_is_selected(match_gallery):
    site = ('[Aruma] Taisetsu na Kimi to no Amai Koi | Our Precious Sweet Love '
            '(COMIC LO 2020-01) [English] [Mistvern + Bigk40k] [Digital]')
    assert match_gallery(
        'Taisetsu na Kimi to no Amai Koi ｜ Our Precious Sweet Love (COMIC LO 2020-01)',
        [(site, URL_A)]) == URL_A


def test_the_exact_match_wins_over_a_sequel_returned_beside_it(match_gallery):
    exact = ('[Aruma] Taisetsu na Kimi to no Amai Koi | Our Precious Sweet Love '
             '(COMIC LO 2020-01) [English]')
    sequel = ('[Aruma] Taisetsu na Kimi to no Amai Koi 2 | Our Precious Sweet Love 2 '
              '(COMIC LO 2021-01) [English]')
    assert match_gallery(
        'Taisetsu na Kimi to no Amai Koi ｜ Our Precious Sweet Love (COMIC LO 2020-01)',
        [(sequel, URL_B), (exact, URL_A)]) == URL_A


def test_a_lone_sequel_is_rejected_rather_than_applied(match_gallery):
    """Better to leave the gallery unmatched than to write a sibling's metadata onto it."""
    sequel = ('[Aruma] Taisetsu na Kimi to no Amai Koi 2 | Our Precious Sweet Love 2 '
              '(COMIC LO 2021-01) [English]')
    assert match_gallery(
        'Taisetsu na Kimi to no Amai Koi ｜ Our Precious Sweet Love (COMIC LO 2020-01)',
        [(sequel, URL_B)]) is None


def test_wrong_chapter_number_is_rejected(match_gallery):
    assert match_gallery(
        'Showbiz Comes After Yuri Sex Ch. 3',
        [('[Chorimokki] Geinou Katsudou wa Yuri Ecchi no Ato de | '
          'Showbiz Comes After Yuri Sex Ch. 5 [English]', URL_A)]) is None


def test_a_roman_numeral_sequel_is_rejected_rather_than_applied(match_gallery):
    """The guard used to read arabic digits only, so neither side carried a number at all.

    These two score 97 against each other and the sequel was the only hit, which is the path
    that applies a match without it ever having to be perfect.
    """
    assert match_gallery(
        'Kino no Tabi no Erohon V - the Erotic World',
        [('[Circle] Kino no Tabi no Erohon II - the Erotic World [English]', URL_A)]) is None


def test_the_same_volume_written_in_the_other_notation_is_no_longer_rejected(match_gallery):
    """The other half of reading roman numerals: II and 2 must not read as different volumes.

    What changed is the guard. The score is the limiting factor now: these two spellings only
    reach 85 against each other, so at the shipped default threshold this pair goes to the
    chooser rather than being applied.
    """
    folder = 'DepthSinker2'
    site = '[ElAne WorkShop (Ipuu)] DepthSinker II (Kantai Collection -KanColle-)'
    assert fetch.title_numbers(fetch.canonical_title(folder)) == \
        fetch.title_numbers(fetch.canonical_title(site))
    assert match_gallery(folder, [(site, URL_A)], threshold=70) == URL_A


@pytest.mark.parametrize('folder, site, why', [
    ('DRII ~Katatsumuri Shoukougun~', '[Behind Moon (Q)] DR:II ~Katatsumuri Shoukougun~',
     'the folder dropped the colon, so DRII is one word and its II is not a numeral'),
    # The translator credit after the parody is what keeps canonical_title from stripping the
    # parody group, so its numeral survives into the comparison. Without the credit the group
    # is trailing, is stripped, and this pair matches perfectly well.
    ('Lucrecia VI', 'Lucrecia VI (Final Fantasy VII: Dirge of Cerberus) =SNP=',
     'the parody name carries a numeral of its own, which the title does not'),
])
def test_the_accepted_cost_of_reading_roman_numerals(match_gallery, folder, site, why):
    """Two shapes this rejects that it should ideally match. Asserted so they stay known.

    The trade was measured against a whole library before it was taken, and it comes out ahead;
    the figures are in the metadata-matching rule. Both shapes need something other than the
    numbering guard to fix, and a rejection is the safe direction.
    """
    assert match_gallery(folder, [(site, URL_A)]) is None, why


def test_unrelated_gallery_is_rejected(match_gallery):
    assert match_gallery(
        'Big Boobs JK Toilet Girl Debut',
        [('[Someone] Totally Unrelated Doujin | Another Thing Entirely [English]', URL_A)]) is None


@pytest.mark.parametrize('folder, site', [
    # The folder kept the English half, the site has the whole pair.
    ("A Hero's Fall from Grace Dragon Princess",
     "[TSF no F (Hiiragi Popura, Yotsuba Chika)] Yuusha Aku ni Ochiru ~Ryu Hime Meifa no "
     "Kakusei~ | A Hero's Fall from Grace Dragon Princess [English] [Decensored]"),
    # The folder kept the romaji half.
    ('Tenshi Hirotta kara Haramaseru ~Ojii-san Senyou Botebara Onaho ni Naru made no Kiroku~',
     '[ma_shika (A_shika)] Tenshi Hirotta kara Haramaseru ~Ojii-san Senyou Botebara Onaho ni '
     'Naru made no Kiroku~ | I Met an Angel, and then I Knocked Her Up [English] [Xzosk]'),
    # The separator was deleted from the folder name, leaving a double space.
    ('[Riku no Kotoutei (Shayo)] Inaka ni wa Kore kurai Goraku ga Nai 1  '
     'Not Much Else to Do in the Countryside 1 [English]',
     '[Riku no Kotoutei (Shayo)] Inaka ni wa Kore kurai Goraku ga Nai 1 | '
     'Not Much Else to Do in the Countryside 1 [English] [Digital]'),
])
def test_a_half_of_the_site_title_still_matches(match_gallery, folder, site):
    assert match_gallery(folder, [(site, URL_A)]) == URL_A


def test_a_japanese_folder_title_matches_a_romaji_hit(match_gallery):
    """No shared characters, so the ratio reads 0 however right the hit is.

    The search reached this result by matching the site's own Japanese title, so the pair is
    treated as unverifiable rather than as a mismatch.
    """
    assert match_gallery(
        '王国敗北 (ドクターストーン)',
        [('[Kouguti] Oukoku Haiboku | The Defeat of the Kingdom (Dr. STONE) [English]', URL_A)],
        language='Japanese') == URL_A


def test_several_unverifiable_hits_go_to_the_chooser(match_gallery):
    assert match_gallery(
        '王国敗北 (ドクターストーン)',
        [('[Kouguti] Oukoku Haiboku (Dr. STONE)', URL_A),
         ('[Kouguti] Oukoku Haiboku | The Defeat of the Kingdom [English]', URL_B),
         ('[kouguti] Oukoku Haiboku | Reino Derrotado [Spanish]', URL_C)],
        language='Japanese') == 'picker:3'


def test_cross_script_does_not_bypass_the_numbering_guard(match_gallery):
    assert match_gallery(
        '王国敗北 2 (ドクターストーン)',
        [('[Kouguti] Oukoku Haiboku 3 | The Defeat of the Kingdom [English]', URL_A)],
        language='Japanese') is None


def test_a_result_without_a_title_is_still_usable(match_gallery):
    """panda.chaika.moe resolves a gallery by hash without reporting its title."""
    assert match_gallery(
        'Taisetsu na Kimi to no Amai Koi',
        [('', 'https://panda.chaika.moe/archive/1/')]) == 'https://panda.chaika.moe/archive/1/'


# --- Search request budget --------------------------------------------------------------

RESULTS_PAGE = (
    '<html><body><div class="itg">'
    '<div class="gl1t"><a href="https://e-hentai.org/g/1/aaa/">'
    '<div class="glink">Some Gallery Title</div></a></div>'
    '</div></body></html>'
)
NO_HITS_PAGE = '<html><body><p>No hits found</p></body></html>'


class _FakeResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = url
        self.headers = {'content-type': 'text/html'}


@pytest.fixture
def counting_search(monkeypatch):
    """Runs EHen.search against canned pages, returning (result, urls requested)."""
    monkeypatch.setattr(pewnet.EHen, 'begin_lock', lambda self: None)
    monkeypatch.setattr(pewnet.EHen, 'end_lock', lambda self: None)
    monkeypatch.setattr(pewnet.time, 'sleep', lambda *a: None)

    def run(page_text, include_expunged):
        requested = []

        def fake_get(url, params=None, **kwargs):
            full = url + ('?' + '&'.join(f'{k}={v}' for k, v in (params or {}).items()) if params else '')
            requested.append(full)
            # the expunged listing is a different listing, and here it is always empty
            body = NO_HITS_PAGE if 'f_sh=on' in full else page_text
            return _FakeResponse(body, full)

        monkeypatch.setattr(pewnet.requests, 'get', fake_get)
        monkeypatch.setattr(app_constants, 'INCLUDE_EH_EXPUNGED', include_expunged)
        return pewnet.EHen().search('"Some Gallery Title"'), requested

    return run


def test_a_matching_search_costs_one_request_even_with_expunged_enabled(counting_search):
    """The expunged listing is disjoint, so reaching it means searching twice.

    That second search must never land on the common path: the sources ban by IP on volume,
    and a gallery that already matched has nothing to gain from it.
    """
    result, requested = counting_search(RESULTS_PAGE, include_expunged=True)
    assert result and len(requested) == 1
    assert 'f_sh=on' not in requested[0]


def test_a_failing_search_does_not_retry_when_expunged_is_disabled(counting_search):
    result, requested = counting_search(NO_HITS_PAGE, include_expunged=False)
    assert result == {}
    assert len(requested) == 1


def test_a_failing_search_retries_the_expunged_listing_when_enabled(counting_search):
    result, requested = counting_search(NO_HITS_PAGE, include_expunged=True)
    assert result == {}
    assert len(requested) == 2
    assert 'f_sh=on' not in requested[0] and 'f_sh=on' in requested[1]


# --- Publication date parsing (#2) -------------------------------------------------------

@pytest.mark.parametrize('posted, expected_none', [
    (-3600, True),      # chaika's "date unknown" placeholder, and pre-epoch on Windows
    (0, True),
    (None, True),
    ('', True),
    ('abc', True),
    (99999999999999, True),
    (1406565688, False),
])
def test_parse_pub_date_never_raises(posted, expected_none):
    """A non-positive 'posted' crashed a whole run partway through, mid-library.

    datetime.fromtimestamp raises OSError on Windows for anything before the epoch, and the
    exception escaped far enough to abort the fetch and lose every gallery still queued.
    """
    result = pewnet.EHen.parse_pub_date(posted)
    assert (result is None) is expected_none


def test_parse_pub_date_keeps_a_real_timestamp_intact():
    import datetime
    assert pewnet.EHen.parse_pub_date(1406565688) == datetime.datetime.fromtimestamp(1406565688)


# The source files 'translated', 'rewrite' and 'text cleaned' under the same `language:`
# namespace as a real language. Taking whichever came first filed galleries under a language of
# "Text cleaned", which then read as a language nothing could ever match.

def _applied(language_tags, append=False):
    gallery = gallerydb.Gallery()
    gallery.artist = 'Yamada'
    data = {
        'title': {'def': '[Yamada] Some Title', 'jpn': ''},
        'tags': {'Language': list(language_tags), 'Artist': ['yamada']},
        'type': 'Manga', 'pub_date': None, 'url': 'https://e-hentai.org/g/1/a/',
    }
    return pewnet.EHen.apply_metadata(gallery, data, append=append).language


@pytest.mark.parametrize('tags, expected', [
    (['english'], 'English'),
    # A real language wins wherever the meta tag happens to sit in the list.
    (['text cleaned', 'english'], 'English'),
    (['translated', 'english'], 'English'),
    (['rewrite', 'korean'], 'Korean'),
    # Nothing here is a language, so the tag the source did write is kept rather than dropped.
    (['text cleaned'], 'Text cleaned'),
    # 'translated' alone says only that a translation happened, so the folder name decides and
    # a folder that stated nothing leaves the default.
    (['translated'], 'English'),
])
def test_a_real_language_is_preferred_over_a_tag_that_only_shares_its_namespace(tags, expected,
                                                                               monkeypatch):
    # The suite reads G_DEF_LANGUAGE from an untracked settings.ini, and the fallback case lands
    # on exactly that value.
    monkeypatch.setattr(app_constants, 'G_DEF_LANGUAGE', 'English')
    monkeypatch.setattr(app_constants, 'G_CUSTOM_LANGUAGES', [])
    utils.init_utils()
    assert _applied(tags) == expected


def _gmetadata(posted):
    return {'gmetadata': [{
        'gid': 1, 'token': 't', 'title': 'A Title', 'title_jpn': 'JP', 'category': 'Manga',
        'posted': posted, 'tags': ['language:english'], 'filecount': '1', 'filesize': 1,
        'rating': '4.0', 'uploader': 'u', 'expunged': False,
    }]}


@pytest.mark.parametrize('posted', [-3600, 0, None, 'abc'])
def test_parsing_a_response_survives_an_unusable_pub_date(posted):
    """The crash was in parse_metadata, so guarding the helper alone does not cover it.

    A single gallery with no usable date aborted the whole run, losing every gallery still
    queued behind it.
    """
    url = 'https://e-hentai.org/g/1/a/'
    parsed = pewnet.EHen.parse_metadata(_gmetadata(posted), {1: url})
    assert parsed[url]['pub_date'] is None
    assert parsed[url]['title']['def'] == 'A Title'


def test_parsing_a_response_keeps_a_real_pub_date():
    import datetime
    url = 'https://e-hentai.org/g/1/a/'
    parsed = pewnet.EHen.parse_metadata(_gmetadata(1406565688), {1: url})
    assert parsed[url]['pub_date'] == datetime.datetime.fromtimestamp(1406565688)


# --- Source routing for an existing gallery url (#3) -------------------------------------

@pytest.mark.parametrize('url, site', [
    ('https://e-hentai.org/g/723440/ef3b7c7753/', 'ehen'),
    ('https://g.e-hentai.org/g/1/a/', 'ehen'),          # the legacy host still resolves
    ('https://exhentai.org/g/123/abc/', 'exhen'),
    ('https://panda.chaika.moe/archive/44797/', 'chaikahen'),
    ('https://panda.chaika.moe/gallery/17967/', 'chaikahen'),
    ('https://example.com/x', None),
    ('', None),
])
def test_website_checker(url, site):
    assert fetch.Fetch()._website_checker(url) == site


@pytest.mark.parametrize('url, hen, supported', [
    # e-hentai and exhentai share the gallery id/token url format, so either reads either.
    ('https://e-hentai.org/g/1/a/', pewnet.EHen, True),
    ('https://exhentai.org/g/1/a/', pewnet.EHen, True),
    ('https://e-hentai.org/g/1/a/', pewnet.ChaikaHen, False),
    ('https://panda.chaika.moe/archive/1/', pewnet.ChaikaHen, True),
    ('https://panda.chaika.moe/archive/1/', pewnet.EHen, False),
    ('https://example.com/x', pewnet.EHen, False),
])
def test_hen_supports(url, hen, supported):
    """Decides whether a stored gallery url is used directly or the gallery is searched for.

    Getting this wrong sends a gallery whose url is already known through a full search
    against a source that cannot read that url.
    """
    assert fetch.Fetch()._hen_supports(url, hen) is supported


# --- Settings round-trip (#4) ------------------------------------------------------------

@pytest.mark.parametrize('stored, expected', [
    ('', ['chaikahen']),                    # blank means never configured -> the default wins
    ('none', []),                           # explicitly emptied, and it stays empty
    ('chaikahen', ['chaikahen']),
    ('ehen>|<chaikahen', ['ehen', 'chaikahen']),
])
def test_a_blank_list_setting_falls_back_to_its_default(stored, expected):
    """A blank value silently returned an empty list, which disabled the fallback source.

    Nothing errored and the default could never take effect again, because the emptied value
    read back as a deliberate choice.
    """
    settings.config['TestSection'] = {'hen list': stored}
    try:
        assert (settings.get(['chaikahen'], 'TestSection', 'hen list', list) or []) == expected
    finally:
        del settings.config['TestSection']


def test_an_emptied_list_setting_round_trips_through_the_ini():
    """What accept() writes for an empty list has to read back as empty, not as the default."""
    settings.config['TestSection'] = {}
    try:
        for value in ([], ['chaikahen']):
            settings.set(value if value else 'none', 'TestSection', 'hen list')
            loaded = settings.get(['chaikahen'], 'TestSection', 'hen list', list) or []
            assert loaded == value
    finally:
        del settings.config['TestSection']

# --- Candidate language ------------------------------------------------------------------
# A search that had to drop its language filter to find anything at all brings back every
# translation of the work. Reading the language off the candidate's own title costs nothing,
# and decides both which candidates survive and which of them the picker shows first.

@pytest.mark.parametrize('title, expected', [
    ('[Yamada] Some Title [Russian]', {'russian'}),
    ('[Yamada] Some Title [English, Japanese, Chinese]', {'english', 'japanese', 'chinese'}),
    ('[MUK]  Hiyake tokushuu Tan# 6 [ru gari o-hen] [English, Japanese, Chinese]',
     {'english', 'japanese', 'chinese'}),
    # An untranslated release states nothing, which is not the same as stating Japanese.
    ('[Yamada] Some Title', set()),
    # Neither a circle name that reads like a language nor a non-language tag is one.
    ('[English Muffin (Yamada)] Some Title [Digital] [Decensored]', set()),
])
def test_title_languages_reads_only_real_language_tags(title, expected):
    assert fetch.title_languages(title) == expected


# The two families below are the ones a real run actually offered, taken from the log. The
# yumoteliuce set is the one that went wrong: with Chinese, Spanish and Korean discarded, the
# Thai release was the only survivor and was applied to an English gallery unseen.
CAR_SEX_LOCAL = 'car sex instructor (COMIC BAVEL 2021-12)'
CAR_SEX_THAI = ('[yumoteliuce] car sex instructor (COMIC BAVEL 2021-12) '
                '[Thai \u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22] [T@NUKI] [Digital]')
CAR_SEX_CHINESE = ('[yumoteliuce] Car Sex instructor (COMIC BAVEL 2021-12) '
                   '[Chinese] [\u5bae\u697d\u500b\u4eba\u7ffb\u8b6f] [Digital]')
CAR_SEX_SPANISH = ('[yumoteliuce] car sex instructor (COMIC BAVEL 2021-12) '
                   '[Spanish] [Anamnesis Scanlation] [Digital]')
CAR_SEX_ENGLISH = '[yumoteliuce] car sex instructor (COMIC BAVEL 2021-12) [English] [Digital]'

DOUBLE_LIVE_LOCAL = 'Double\u2605Live (COMIC BAVEL 2022-12)'
DOUBLE_LIVE_ITALIAN = ('[Puyocha] Double\u2605Live | Doppia Vita (COMIC BAVEL 2022-12) '
                       '[Italian] [Digital]')
DOUBLE_LIVE_RUSSIAN = ('[Puyocha] Double\u2605Live | \u0414\u0432\u043e\u0439\u043d\u0430\u044f \u0436\u0438\u0437\u043d\u044c (COMIC BAVEL 2022-12) '
                       '[Russian] [Mr_As] [Digital]')


def test_a_language_stated_with_its_own_name_is_still_a_language(match_gallery):
    """The wrong match that actually happened: '[Thai \u0e20\u0e32\u0e29\u0e32\u0e44\u0e17\u0e22]' read as no language at all,
    so it survived a filter that removed every other translation and was applied unseen.
    """
    assert match_gallery(CAR_SEX_LOCAL,
                         [(CAR_SEX_THAI, URL_A), (CAR_SEX_CHINESE, URL_B),
                          (CAR_SEX_SPANISH, URL_C)]) is None


def test_a_lone_survivor_of_the_language_filter_is_offered_not_applied(match_gallery):
    """A tag shape the parser still does not know would otherwise be applied on its own."""
    unknown_tag = '[yumoteliuce] car sex instructor (COMIC BAVEL 2021-12) [Tagalog-ish] [Digital]'
    assert match_gallery(CAR_SEX_LOCAL,
                         [(unknown_tag, URL_A), (CAR_SEX_CHINESE, URL_B)]) == 'picker:1'


def test_a_translation_into_another_language_is_dropped(match_gallery):
    """An English gallery and a Russian one are different releases, whatever they score."""
    assert match_gallery(DOUBLE_LIVE_LOCAL,
                         [(DOUBLE_LIVE_RUSSIAN, URL_B), (DOUBLE_LIVE_ITALIAN, URL_C)]) is None


def test_dropping_the_wrong_languages_can_leave_nothing(match_gallery):
    """Failing to match beats applying an Italian release's metadata to an English gallery."""
    assert match_gallery(CAR_SEX_LOCAL,
                         [(CAR_SEX_SPANISH, URL_B), (CAR_SEX_CHINESE, URL_C)]) is None


def test_a_result_that_states_no_language_is_kept(match_gallery):
    """No tag is the normal shape of an untranslated listing, so it is not evidence of a clash."""
    untagged = '[yumoteliuce] car sex instructor (COMIC BAVEL 2021-12) [Digital]'
    assert match_gallery(CAR_SEX_LOCAL, [(untagged, URL_A)]) == URL_A


def test_an_untranslated_gallery_is_never_filtered(match_gallery):
    """Its stored language is G_DEF_LANGUAGE for anything the folder name did not state."""
    assert match_gallery(CAR_SEX_LOCAL, [(CAR_SEX_ENGLISH, URL_A)], language='Japanese') == URL_A


def test_the_language_filter_can_be_turned_off(match_gallery, monkeypatch):
    """The same two candidates the filter rejects above, now both offered."""
    monkeypatch.setattr(app_constants, 'FILTER_RESULTS_BY_LANGUAGE', False)
    assert match_gallery(DOUBLE_LIVE_LOCAL,
                         [(DOUBLE_LIVE_RUSSIAN, URL_B),
                          (DOUBLE_LIVE_ITALIAN, URL_C)]) == 'picker:2'


def test_the_untranslated_release_is_offered_first_to_an_untranslated_gallery(match_gallery):
    """The source lists newest first, which put recent translations above the original."""
    translation = '[Yamada] Kimi to Boku no Natsu | Our Summer [English]'
    original = '[Yamada] Kimi to Boku no Natsu | Our Summer'
    assert match_gallery('Kimi to Boku no Natsu ｜ Our Summer',
                         [(translation, URL_A), (original, URL_B)],
                         language='Japanese') == 'picker:2'
    assert match_gallery.choices[0] == original


def test_the_picker_is_told_its_place_in_the_queue(match_gallery):
    """A long unattended run ends in a queue of these, with nothing else showing its length."""
    translation = '[Yamada] Kimi to Boku no Natsu | Our Summer [English]'
    original = '[Yamada] Kimi to Boku no Natsu | Our Summer'
    match_gallery('Kimi to Boku no Natsu ｜ Our Summer',
                  [(translation, URL_A), (original, URL_B)], language='Japanese')
    assert match_gallery.position == (1, 1)


class _RecordingHen(pewnet.EHen):
    """Stands in for the api, recording how the candidate lookup was batched."""

    def __init__(self, entries=()):
        self.calls = []
        self._entries = {url: entry for url, entry in entries}

    def get_metadata(self, list_of_urls, cookies=None):
        assert len(list_of_urls) <= self.MAX_GDATA_URLS, 'the api rejects a longer call outright'
        self.calls.append(list(list_of_urls))
        gid_to_url = {i: url for i, url in enumerate(list_of_urls)}
        gmetadata = [dict(self._entries.get(url, {}), gid=i)
                     for i, url in enumerate(list_of_urls) if url in self._entries]
        return {'gmetadata': gmetadata}, gid_to_url


def test_previews_are_not_looked_up_unless_asked_for(monkeypatch):
    """The lookup costs requests against a source that bans on volume."""
    monkeypatch.setattr(app_constants, 'PICKER_PREVIEWS', False)

    class _Exploding(pewnet.EHen):
        def __init__(self):
            pass

        def get_metadata(self, *args, **kwargs):
            raise AssertionError('the api must not be called with the setting off')

    galleries = [[None, [('[Yamada] Kimi to Boku no Natsu', URL_A)]]]
    assert fetch.Fetch()._candidate_previews(galleries, _Exploding()) == {}


def test_previews_for_the_whole_run_are_looked_up_in_one_batch(monkeypatch):
    """One call per dialog would be a request each; the run's candidates go together instead.

    The same url turning up under two galleries is looked up once, not twice.
    """
    monkeypatch.setattr(app_constants, 'PICKER_PREVIEWS', True)
    hen = _RecordingHen([
        (URL_A, {'title_jpn': '\u541b\u3068\u50d5\u306e\u590f', 'thumb': 'https://ehgt.org/a.jpg'}),
        (URL_B, {'title_jpn': '', 'thumb': 'https://ehgt.org/b.jpg'}),
    ])
    galleries = [[None, [('A', URL_A), ('B', URL_B)]],
                 [None, [('A again', URL_A), ('C', URL_C)]]]

    previews = fetch.Fetch()._candidate_previews(galleries, hen)

    assert hen.calls == [[URL_A, URL_B, URL_C]]
    assert previews[URL_A] == {'native': '\u541b\u3068\u50d5\u306e\u590f',
                               'thumb': 'https://ehgt.org/a.jpg',
                               'creators': ()}
    assert URL_C not in previews  # the api returned nothing for it


def test_the_preview_lookup_keeps_the_creator_the_api_already_sent(monkeypatch):
    """The gmetadata entry carries the artist and group namespaces and the lookup is already
    paid for, so the creator costs nothing. Sorted, or a row reshuffles between runs.
    """
    monkeypatch.setattr(app_constants, 'PICKER_PREVIEWS', True)
    hen = _RecordingHen([
        (URL_A, {'title_jpn': '', 'thumb': '',
                 'tags': ['group:edamametei', 'artist:uko', 'language:english']}),
        (URL_B, {'title_jpn': '', 'thumb': '', 'tags': ['language:english']}),
    ])

    previews = fetch.Fetch()._candidate_previews([[None, [('A', URL_A), ('B', URL_B)]]], hen)

    assert previews[URL_A]['creators'] == ('edamametei', 'uko')
    assert previews[URL_B]['creators'] == (), 'a release the source credits to nobody'


def test_a_picker_row_states_the_creator_the_titles_no_longer_carry():
    """Reported from a real library-wide scan of the same sources: 'Pink Archive' by unacchi
    against Alpha91's gallery of the same name. canonical_title strips the creator out of both
    titles before they are scored, so the row is the only place it can reach the user.
    """
    previews = {URL_A: {'native': '君と僕の夏', 'thumb': 'https://ehgt.org/a.jpg',
                        'creators': ('edamametei', 'uko')},
                URL_B: {'native': '', 'thumb': '', 'creators': ()}}

    rows, thumbnails = fetch.picker_labels([('A Title', URL_A), ('A Title', URL_B)], previews)

    assert rows[0] == ('A Title\n君と僕の夏\nby edamametei, uko', URL_A)
    assert rows[1] == ('A Title', URL_B), 'no native title and no creator means no extra lines'
    assert thumbnails == {URL_A: 'https://ehgt.org/a.jpg'}


def test_a_picker_row_is_unchanged_when_there_are_no_previews():
    "Which is also the chaika case: the lookup is an e-hentai api call with no equivalent there."
    rows = [('A Title', URL_A)]
    assert fetch.picker_labels(rows, {}) == (rows, {})


def test_a_run_with_more_candidates_than_the_api_takes_is_split(monkeypatch):
    monkeypatch.setattr(app_constants, 'PICKER_PREVIEWS', True)
    urls = ['https://e-hentai.org/g/{}/x/'.format(i) for i in range(60)]
    hen = _RecordingHen()

    fetch.Fetch()._candidate_previews([[None, [(str(i), u) for i, u in enumerate(urls)]]], hen)

    assert [len(call) for call in hen.calls] == [25, 25, 10]
    assert [u for call in hen.calls for u in call] == urls


def test_a_failed_preview_lookup_does_not_stop_the_picker(monkeypatch):
    """Covers are a convenience; losing them must not cost the user the whole manual pass."""
    monkeypatch.setattr(app_constants, 'PICKER_PREVIEWS', True)

    class _Broken(pewnet.EHen):
        def __init__(self):
            pass

        def get_metadata(self, *args, **kwargs):
            raise ValueError('the api fell over')

    galleries = [[None, [('A', URL_A)]]]
    assert fetch.Fetch()._candidate_previews(galleries, _Broken()) == {}

# --- Metadata files beside a gallery ------------------------------------------------------
# The E-Hentai Downloader userscript writes an info.txt whose first lines are bare: the romaji
# title, the native title, and the gallery url, with no key in front of any of them. The
# HDoujin parser reports success for any info.txt that has lines in it, so it claimed these and
# extracted nothing from them.

WESTERN_INFO = """mona

https://exhentai.org/g/2266155/337f88a8c5/

Category: Western
Uploader: Bromax34
Posted: 2022-07-07 19:25
Parent: None
Visible: Yes
Language: English
File Size: 163.2 MB
Length: 25 pages
Favorited: 171 times
Rating: 4.35

Tags:
> language: english
> parody: genshin impact
> character: mona megistus
> female: ass expansion, breast expansion, furry, sole female, transformation
> other: no penetration


Page 1: https://exhentai.org/s/4268875a6f/2266155-1
Image 1: monas_curse_01.png
"""

DOUJIN_INFO = """[\u30ed\u30ea\u30e2] \u3060\u3089\u3057\u306a\u3044\u59c9
[\u30ed\u30ea\u30e2] \u3060\u3089\u3057\u306a\u3044\u59c9
https://exhentai.org/g/2144632/5a332a0018/

Category: Doujinshi
Uploader: Pokom
Posted: 2022-02-17 14:01
Parent: None
Visible: Yes
Language: Japanese
File Size: 18.00 MB
Length: 4 pages

Tags:
> parody: original
> artist: rorimo
> female: sister, sleeping, sole female
> mixed: incest

Uploader Comment:
https://www.pixiv.net/artworks/93885643
"""

HDOUJIN_INFO = """Title: Some Gallery
Artist: Yamada
Circle: Some Circle
Tags: sole female, sister
URL: https://e-hentai.org/g/111/aaa/
Description: notes here
"""


@pytest.fixture
def metafile(tmp_path):
    """Writes an info.txt into a gallery folder and returns what GMetafile makes of it."""
    utils.init_utils()  # title_parser reads module globals that only init_utils sets

    def run(contents, name='a gallery'):
        folder = tmp_path / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'info.txt').write_text(contents, encoding='utf-8')
        return utils.GMetafile(str(folder)).metadata

    return run


def test_the_url_is_read_from_a_bare_line(metafile):
    """The one field that matters: it turns a failed search into a direct fetch."""
    assert metafile(WESTERN_INFO)['link'] == 'https://exhentai.org/g/2266155/337f88a8c5/'
    assert metafile(DOUJIN_INFO)['link'] == 'https://exhentai.org/g/2144632/5a332a0018/'


def test_the_native_title_is_preferred_over_the_romaji_one(metafile):
    """The romaji line is what the folder was named after, so searching it has already failed."""
    assert metafile(DOUJIN_INFO)['title'] == '\u3060\u3089\u3057\u306a\u3044\u59c9'


def test_a_gallery_with_one_title_leaves_the_native_line_blank(metafile):
    assert metafile(WESTERN_INFO)['title'] == 'mona'


def test_the_namespaced_tag_block_is_read(metafile):
    tags = metafile(WESTERN_INFO)['tags']
    assert tags['Female'] == ['ass expansion', 'breast expansion', 'furry', 'sole female',
                              'transformation']
    assert tags['Parody'] == ['genshin impact']


@pytest.mark.parametrize('field, expected', [
    ('type', 'Doujinshi'),
    ('language', 'Japanese'),
    ('artist', 'Rorimo'),          # from the artist namespace, not the bracketed folder prefix
])
def test_the_keyed_fields_are_read(metafile, field, expected):
    assert metafile(DOUJIN_INFO)[field] == expected


def test_the_posted_date_becomes_a_datetime(metafile):
    assert metafile(WESTERN_INFO)['pub_date'].isoformat() == '2022-07-07T19:25:00'


def test_an_hdoujin_info_txt_is_still_read_by_its_own_parser(metafile):
    """Its url is keyed, so the bare-url check must not claim the file."""
    parsed = metafile(HDOUJIN_INFO)
    assert parsed['link'] == 'https://e-hentai.org/g/111/aaa/'
    assert parsed['title'] == 'Some Gallery'


def test_a_folder_with_no_metafile_yields_nothing(metafile, tmp_path):
    utils.init_utils()
    empty = tmp_path / 'no metafile'
    empty.mkdir()
    assert utils.GMetafile(str(empty)).metadata['link'] == ''


def test_a_gallery_with_no_link_takes_the_one_beside_it(match_gallery, tmp_path, monkeypatch):
    """Without this the file only helps galleries imported after it was understood."""
    monkeypatch.setattr(app_constants, 'USE_GALLERY_LINK', True)
    utils.init_utils()

    fetcher = fetch.Fetch()
    fetcher._hen_list = []
    gallery = gallerydb.Gallery()
    folder = tmp_path / 'seeded gallery'
    folder.mkdir()
    (folder / 'info.txt').write_text(WESTERN_INFO, encoding='utf-8')
    gallery.path = str(folder)

    assert fetcher._metafile_link(gallery) == 'https://exhentai.org/g/2266155/337f88a8c5/'


def test_seeding_a_link_never_touches_the_stored_metadata(match_gallery, tmp_path):
    """The file is a download-time snapshot; applying it would overwrite with a stale copy."""
    utils.init_utils()
    folder = tmp_path / 'untouched gallery'
    folder.mkdir()
    (folder / 'info.txt').write_text(DOUJIN_INFO, encoding='utf-8')

    gallery = gallerydb.Gallery()
    gallery.path = str(folder)
    gallery.title = 'the title the user already has'
    gallery.artist = 'Someone Else'

    fetch.Fetch()._metafile_link(gallery)

    assert gallery.title == 'the title the user already has'
    assert gallery.artist == 'Someone Else'


def test_an_unreadable_gallery_folder_is_not_fatal(tmp_path):
    """A gallery on an unmounted drive must not stop the run before it starts."""
    gallery = gallerydb.Gallery()
    gallery.path = str(tmp_path / 'not here at all')
    assert fetch.Fetch()._metafile_link(gallery) == ''

# --- Cover previews reach an image host that checks the login ------------------------------
# add_to_queue stored the session on a class attribute nothing reads, so every download went
# out unauthenticated and exhentai's thumbnail host answered each one with a 403 page - which
# arrives as an ordinary file, leaving a null pixmap as the only symptom.

class _RecordingSession:
    def __init__(self):
        self.urls = []

    def get(self, url, stream=False):
        self.urls.append(url)
        return 'response'


def test_a_queued_download_keeps_the_session_it_was_given():
    session = _RecordingSession()
    try:
        item = pewnet.Downloader.add_to_queue('https://s.exhentai.org/w/00/1-a.webp', session)
        assert item.session is session
    finally:
        pewnet.Downloader._inc_queue.get_nowait()


def test_a_download_is_made_with_the_items_own_session():
    session = _RecordingSession()
    item = pewnet.DownloaderItem('https://s.exhentai.org/w/00/1-a.webp', session)
    # __new__ so the real __init__ does not go making a download directory.
    downloader = pewnet.Downloader.__new__(pewnet.Downloader)

    assert downloader._get_response(item.download_url, session=item.session) == 'response'
    assert session.urls == ['https://s.exhentai.org/w/00/1-a.webp']


def test_an_image_session_carries_the_sources_cookies(monkeypatch):
    monkeypatch.setattr(pewnet.EHen, 'COOKIES', {'ipb_member_id': 'shared'})
    # __new__ so __init__ does not go and load the real stored login off disk.
    hen = pewnet.EHen.__new__(pewnet.EHen)
    hen.cookies = {'ipb_pass_hash': 'per instance'}
    hen.e_url_o = 'https://e-hentai.org/'

    session = hen.image_session()

    assert session.cookies.get('ipb_member_id') == 'shared'
    assert session.cookies.get('ipb_pass_hash') == 'per instance'


@pytest.mark.parametrize('hen_cls, site', [(pewnet.EHen, 'https://e-hentai.org/'),
                                           (pewnet.ExHen, 'https://exhentai.org/')])
def test_an_image_session_names_its_own_site_as_the_referer(hen_cls, site):
    # Cookies alone get a 403 from the thumbnail host; it wants the referer as well.
    hen = hen_cls.__new__(hen_cls)
    hen.cookies = {}
    hen.e_url_o = site

    assert hen.image_session().headers['Referer'] == site

# Both shapes below come from a scan of the whole library: the userscript does not always write
# the same thing, and each of these was silently falling through to the HDoujin parser or
# picking up text that only looked like a field.

HASH_SUFFIXED_INFO = """Some Gallery [English]
ある本
https://exhentai.org/g/3211989/97eb195d68/#

Category: Non-H
Posted: 2025-01-27 16:32
Language: English  TR

Tags:
> language: english, translated
> artist: tsurui
"""

COMMENTED_INFO = """Some Gallery
ある本
https://exhentai.org/g/3851689/1b6b6f3f18/

Category: Manga
Posted: 2026-03-21 22:12
Language: Japanese

Uploader Comment:
Circle: not a real field
Category: Western
Artist: ワダアルコ
"""


@pytest.mark.parametrize('suffix', [
    '',
    '#',        # copied from the gallery page itself
    '?p=1',     # copied while on the second page of it
    '?p=2#',
])
def test_a_url_line_carrying_where_it_was_copied_from_is_still_this_format(metafile, suffix):
    """77 real galleries fell through to the HDoujin parser, which read nothing out of them.

    Whatever follows the gallery id records where the link was copied from, so all of these
    have to reduce to the one url that addresses the gallery.
    """
    parsed = metafile(HASH_SUFFIXED_INFO.replace('97eb195d68/#', '97eb195d68/' + suffix))
    assert parsed['link'] == 'https://exhentai.org/g/3211989/97eb195d68/'
    assert parsed['tags']['Artist'] == ['tsurui']


def test_the_category_keeps_the_casing_the_source_wrote(metafile):
    """'Non-H' is one of the app's own gallery types; recapitalising it makes it another."""
    assert metafile(HASH_SUFFIXED_INFO)['type'] == 'Non-H'


def test_a_translated_language_reads_as_the_language(metafile):
    """The site marks a translation as 'English  TR'; only the first word names a language."""
    assert metafile(HASH_SUFFIXED_INFO)['language'] == 'English'


def test_free_text_below_the_header_is_not_read_as_fields(metafile):
    """An uploader comment can hold anything, including lines shaped exactly like a field."""
    parsed = metafile(COMMENTED_INFO)
    assert parsed['type'] == 'Manga', 'a Category: line in a comment overrode the real one'
    assert parsed['language'] == 'Japanese'

# --- Is the stored language a fact, or just the default? --------------------------------------
# G_DEF_LANGUAGE ships as 'English', and every gallery whose folder name never stated a language
# is stored as that. Filtering on it discards correct candidates for a language nobody ever
# established. These monkeypatch the default rather than trusting the ambient one: the repo's
# settings.ini is untracked and sets Japanese, so the suite would otherwise never see the
# configuration the application actually ships with.

def test_a_language_that_is_only_the_default_is_not_a_fact(match_gallery, monkeypatch):
    """The bug: an untagged folder reads as English on a stock install, and filters on it."""
    monkeypatch.setattr(app_constants, 'G_DEF_LANGUAGE', 'English')
    chinese = '[Yamada] Kimi to Boku no Natsu | Our Summer [Chinese]'
    english = '[Yamada] Kimi to Boku no Natsu | Our Summer [English]'
    assert match_gallery('Kimi to Boku no Natsu \uff5c Our Summer',
                         [(chinese, URL_B), (english, URL_A)]) == 'picker:2'


def test_a_language_the_folder_name_states_is_a_fact(match_gallery, monkeypatch):
    """Stated outright, so it filters even though it equals the default."""
    monkeypatch.setattr(app_constants, 'G_DEF_LANGUAGE', 'English')
    chinese = '[Yamada] Kimi to Boku no Natsu | Our Summer [Chinese]'
    english = '[Yamada] Kimi to Boku no Natsu | Our Summer [English]'
    assert match_gallery('Kimi to Boku no Natsu \uff5c Our Summer [English]',
                         [(chinese, URL_B), (english, URL_A)]) == 'picker:1'


def test_a_language_that_differs_from_the_default_is_a_fact(match_gallery, monkeypatch):
    """Nothing but a real parse could have set it, so it filters with no tag in the folder."""
    monkeypatch.setattr(app_constants, 'G_DEF_LANGUAGE', 'Japanese')
    chinese = '[Yamada] Kimi to Boku no Natsu | Our Summer [Chinese]'
    english = '[Yamada] Kimi to Boku no Natsu | Our Summer [English]'
    assert match_gallery('Kimi to Boku no Natsu \uff5c Our Summer',
                         [(chinese, URL_B), (english, URL_A)]) == 'picker:1'


@pytest.mark.parametrize('default, folder, language, expected', [
    ('English', 'Some Title', 'English', False),            # the default, stated nowhere
    ('English', 'Some Title [English]', 'English', True),   # stated by the folder
    ('English', 'Some Title', 'Japanese', True),            # nothing else could have set it
    ('Japanese', 'Some Title', 'Japanese', False),
    ('Japanese', 'Some Title', 'English', True),
    ('English', 'Some Title', '', False),                   # never established at all
])
def test_language_is_known(tmp_path, monkeypatch, default, folder, language, expected):
    monkeypatch.setattr(app_constants, 'G_DEF_LANGUAGE', default)
    path = tmp_path / folder
    path.mkdir(parents=True, exist_ok=True)
    gallery = gallerydb.Gallery()
    gallery.path = str(path)
    gallery.language = language
    assert fetch.language_is_known(gallery) is expected

# --- Reducing a query back to a bare title for chaika -----------------------------------------
# chaika has no filter syntax, so the e-hentai style query has to be cut down. A title long
# enough to be trimmed loses its surrounding quotes, which made the artist filter the first
# quoted run in the query - and the artist name was sent as the title.

@pytest.mark.parametrize('query, expected', [
    ('"A Normal Quoted Title" a:"tanaka taro"$ l:english$', 'A Normal Quoted Title'),
    ('Some Very Long Trimmed Title a:"tanaka taro"$ l:english$',
     'Some Very Long Trimmed Title'),
    ('Fucked Into Submission 3 a:shindou$', 'Fucked Into Submission 3'),
    ('"Title" l:japanese$', 'Title'),
    ('Bare Title With No Filters', 'Bare Title With No Filters'),
])
def test_a_query_reduces_to_its_title_not_its_artist(query, expected):
    assert pewnet.ChaikaHen._plain_title(query) == expected


def test_a_title_search_never_addresses_the_hash_endpoint(monkeypatch):
    """self.url takes a sha1; handing it a title addresses nothing at all."""
    hen = pewnet.ChaikaHen()
    # Archives with no ids: the branch that falls back to the endpoint itself.
    monkeypatch.setattr(hen, '_get_json', lambda *a, **k: {'archives': [{'title': 'Some Title'}]})

    assert hen.search('"Some Title" l:english$') == {}


def test_a_hash_search_still_falls_back_to_the_hash_endpoint(monkeypatch):
    """The same branch is correct for a hash, which is what self.url actually takes."""
    sha1 = 'a' * 40
    hen = pewnet.ChaikaHen()
    monkeypatch.setattr(hen, '_get_json', lambda *a, **k: [{'title': 'Some Title'}])

    found = hen.search(sha1)

    assert found[sha1] == [('Some Title', hen.url + sha1)]


# --- The search ladder ------------------------------------------------------------------------
# Every title below is a real one from a run that found nothing for it. The source held the
# gallery; the four attempts were spent on variations that could not reach it.


def _searchable(folder, artist='', language=''):
    "A gallery whose folder name is the given one. The path need not exist."
    gallery = gallerydb.Gallery()
    gallery.path = r'J:\Doujin\{}\gallery.zip'.format(folder)
    gallery.artist = artist
    gallery.language = language
    return gallery


@pytest.mark.parametrize('language, expected', [
    ('Japanese', ''),
    ('japanese', ''),
    ('English', ' l:english$'),
    ('Chinese', ' l:chinese$'),
    ('', ''),
])
def test_only_a_language_the_source_tags_becomes_a_filter(language, expected):
    """A japanese original carries no language tag, so the filter matches nothing at all.

    Measured against one artist: 25 galleries unfiltered, none of them with the japanese filter,
    including the untagged originals the english filter correctly leaves out.
    """
    assert fetch.language_filter(language) == expected


def test_the_filters_use_the_short_namespace_the_source_accepts():
    """'a:' and 'l:' mean the same to the source's search as 'artist:' and 'language:'.

    Checked against live queries rather than against the wiki, which documents the short forms
    for tagging and omits them from its search qualifier table: a namespace that reads as an
    alias and is not one returns a different result set with no error. Four pairs, quoted
    multi-word artist and both filters together included, returned identical hits.

    Worth the change because the filters are spent out of a capped query: across a whole
    library the twelve characters they give back cut the queries that lose their quoted phrase
    from 220 to 101, and a phrase cut mid-title matches nothing.
    """
    queries = fetch.search_queries(
        _searchable('[Tanaka Taro] Some Title', 'Tanaka Taro', 'English'))
    assert queries[0].endswith(' a:"tanaka taro"$ l:english$')
    assert not any('artist:' in q or 'language:' in q for q in queries), \
        "the app's own search grammar uses the long forms; the source query must not"


def test_a_japanese_gallery_is_searched_for_without_a_language_filter():
    queries = fetch.search_queries(
        _searchable('[Suzupony (Suzunomoku)] Naruko The Quartetto',
                    'Suzupony (Suzunomoku)', 'Japanese'))

    assert queries, 'the gallery has a searchable title'
    assert not any(' l:' in q for q in queries)


@pytest.mark.parametrize('folder, artist, bare', [
    # No separator: the bare form is the title without its "[Circle (Artist)]" prefix.
    ('[70 Nenshiki Yuukyuu Kikan (Ohagi-san)] Coppelia Brothel',
     '70 Nenshiki Yuukyuu Kikan (Ohagi-san)', '"Coppelia Brothel"'),
    # A separator as well: the bare form is the romaji half alone.
    ('[23.4do (Ichiri)] Boku no Risou no Isekai Seikatsu 11 | My Ideal Life in Another World 11',
     '23.4do (Ichiri)', '"Boku no Risou no Isekai Seikatsu 11"'),
])
def test_the_bare_title_is_reachable_inside_the_attempt_budget(folder, artist, bare):
    """Nothing filtered, nothing prefixed - the form a source is likeliest to hold.

    It has to be one of the four attempts rather than the fifth, or a gallery whose artist or
    language is the thing the source disagrees with never gets asked for at all.
    """
    queries = fetch.search_queries(_searchable(folder, artist, 'English'))

    assert len(queries) <= fetch.MAX_SEARCH_ATTEMPTS, 'the request budget is unchanged'
    assert bare in queries


def test_the_artist_and_the_language_still_get_the_first_attempts():
    """They are the two most productive variations and keep their slots."""
    queries = fetch.search_queries(
        _searchable('[70 Nenshiki Yuukyuu Kikan (Ohagi-san)] Coppelia Brothel',
                    '70 Nenshiki Yuukyuu Kikan (Ohagi-san)', 'English'))

    assert queries[0].endswith(' a:"70 nenshiki yuukyuu kikan (ohagi-san)"$ l:english$')
    assert queries[1].endswith('" l:english$')


def test_a_gallery_with_no_searchable_title_yields_no_queries():
    """path_title is '' for a drive root, and an empty query matches the whole site."""
    gallery = gallerydb.Gallery()
    gallery.path = ''
    gallery.artist = ''
    gallery.language = ''

    assert fetch.search_queries(gallery) == []


def test_a_gallery_with_no_searchable_title_is_skipped(match_gallery, tmp_path, monkeypatch):
    """path_title is '' for a drive root, and an empty query matches the whole site."""
    monkeypatch.setattr(app_constants, 'SYSTEM_TRAY', type('T', (), {'showMessage': lambda *a, **k: None})())

    fetcher = fetch.Fetch()
    fetcher._hen_list = []
    gallery = gallerydb.Gallery()
    gallery.path = ''
    gallery.artist = ''
    gallery.language = ''
    gallery.link = ''
    gallery.hashes = []
    gallery.title = ''

    fetcher._auto_metadata_process([gallery], _StubHen({}), 'ehen')

    assert not getattr(gallery, 'temp_url', '')
    assert fetcher.error_galleries, 'the gallery should be reported, not crash the run'


def test_chaika_paces_its_requests(monkeypatch):
    """A fallback pass issues these in a loop; unpaced it reached 35 requests in a minute."""
    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    slept = []
    monkeypatch.setattr(pewnet.time, 'sleep', lambda s: slept.append(s))
    monkeypatch.setattr(pewnet.requests, 'get', lambda *a, **k: _Response())
    monkeypatch.setattr(pewnet.ChaikaHen, '_last_request', pewnet.time.time())

    pewnet.ChaikaHen()._get_json('https://panda.chaika.moe/jsearch?gallery=1')

    assert slept, 'a request issued right after the previous one must wait'
    assert 0 < slept[0] <= pewnet.ChaikaHen.MIN_REQUEST_INTERVAL


def test_chaika_strips_the_short_namespaces_as_it_did_the_long_ones():
    """chaika has no filter syntax, so the fallback cuts the filters off before sending.

    It matches any `word:` rather than the two names, which is what let the filters be
    shortened without touching it - but nothing said so, and a name-specific pattern here
    would have sent `a:"x"$ l:english$` to chaika as part of the title.
    """
    plain = pewnet.ChaikaHen._plain_title
    assert plain('"Coppelia Brothel" a:"ohagi-san"$ l:english$') == 'Coppelia Brothel'
    assert plain('Some Very Long Trimmed Title a:"tanaka taro"$ l:english$') \
        == 'Some Very Long Trimmed Title'
    assert plain('Fucked Into Submission 3 a:shindou$') == 'Fucked Into Submission 3'
