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
])
def test_title_numbers(title, expected):
    assert fetch.title_numbers(title) == expected


# --- Chaika query cleaning -------------------------------------------------------------

@pytest.mark.parametrize('query, expected', [
    ('"Kaizoku Kyonyuu | Big Breasted Pirate" artist:"brave heart petit"$ language:english$',
     'Kaizoku Kyonyuu | Big Breasted Pirate'),
    ('Some Truncated Title artist:foo$ language:english$', 'Some Truncated Title'),
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

    def run(folder_name, results, artist='', language='English'):
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


def test_a_translation_into_another_language_is_dropped(match_gallery):
    """An English gallery and a Russian one are different releases, whatever they score."""
    english = '[Yamada] Kimi to Boku no Natsu | Our Summer [English]'
    russian = '[Yamada] Kimi to Boku no Natsu | Our Summer [Russian]'
    assert match_gallery('Kimi to Boku no Natsu ｜ Our Summer',
                         [(russian, URL_B), (english, URL_A)]) == URL_A


def test_dropping_the_wrong_languages_can_leave_nothing(match_gallery):
    """Failing to match beats applying a Spanish release's metadata to an English gallery."""
    spanish = '[Yamada] Kimi to Boku no Natsu | Our Summer [Spanish]'
    french = '[Yamada] Kimi to Boku no Natsu | Our Summer [French]'
    assert match_gallery('Kimi to Boku no Natsu ｜ Our Summer',
                         [(spanish, URL_B), (french, URL_C)]) is None


def test_a_result_that_states_no_language_is_kept(match_gallery):
    """No tag is the normal shape of an untranslated listing, so it is not evidence of a clash."""
    untagged = '[Yamada] Kimi to Boku no Natsu | Our Summer'
    assert match_gallery('Kimi to Boku no Natsu ｜ Our Summer', [(untagged, URL_A)]) == URL_A


def test_an_untranslated_gallery_is_never_filtered(match_gallery):
    """Its stored language is G_DEF_LANGUAGE for anything the folder name did not state."""
    english = '[Yamada] Kimi to Boku no Natsu | Our Summer [English]'
    assert match_gallery('Kimi to Boku no Natsu ｜ Our Summer', [(english, URL_A)],
                         language='Japanese') == URL_A


def test_the_language_filter_can_be_turned_off(match_gallery, monkeypatch):
    monkeypatch.setattr(app_constants, 'FILTER_RESULTS_BY_LANGUAGE', False)
    english = '[Yamada] Kimi to Boku no Natsu | Our Summer [English]'
    russian = '[Yamada] Kimi to Boku no Natsu | Our Summer [Russian]'
    assert match_gallery('Kimi to Boku no Natsu ｜ Our Summer',
                         [(russian, URL_B), (english, URL_A)]) == 'picker:2'


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
                               'thumb': 'https://ehgt.org/a.jpg'}
    assert URL_C not in previews  # the api returned nothing for it


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
