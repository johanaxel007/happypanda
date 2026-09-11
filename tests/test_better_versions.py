"""Regression cases for the better version review list.

The classification cases use real titles and real tag shapes, the same discipline
`test_metadata_matching.py` follows: a failure here names a specific way the scan would either
miss a release or fill the list with rows nobody can act on.
"""

import pytest

import app_constants
import gallerydb  # noqa: F401  imported before fetch, per the documented order
import betterversions as bv


# --- the store ----------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = bv.BetterVersionStore(str(tmp_path / 'better_versions.db'))
    yield s
    s.close()


def a_row(series_id=1, url='https://e-hentai.org/g/111/aaa/', **kwargs):
    defaults = dict(title='Nekokan! Meshimase | Canned Catfood! Please Try It',
                    kinds=(bv.KIND_TRANSLATED,), held_title='Nekokan! Meshimase')
    defaults.update(kwargs)
    return bv.BetterVersion(series_id=series_id, url=url, **defaults)


def test_a_row_survives_a_reopen(tmp_path):
    "The whole point of a file rather than a session list: the list is worked through later."
    path = str(tmp_path / 'better_versions.db')
    first = bv.BetterVersionStore(path)
    assert first.add(a_row()) is None, 'a new row has no previous state'
    first.close()

    second = bv.BetterVersionStore(path)
    rows = second.rows()
    second.close()
    assert len(rows) == 1
    assert rows[0].kinds == (bv.KIND_TRANSLATED,)
    assert rows[0].held_title == 'Nekokan! Meshimase'


def test_adding_the_same_candidate_twice_reports_the_state_it_already_had(store):
    """A re-found row is not nothing found, which is what the previous state is for.

    Reporting only "was it new" left a scan that turned up nothing but rows already on the
    list saying it had found none at all.
    """
    assert store.add(a_row()) is None
    assert store.add(a_row()) == bv.STATE_NEW
    assert len(store.rows()) == 1


def test_a_dismissed_row_stays_dismissed_when_a_later_scan_finds_it_again(store):
    store.add(a_row())
    store.dismiss(1, 'https://e-hentai.org/g/111/aaa/')
    assert store.rows() == []

    # The next scan turns the same candidate up, and has to be able to tell that apart from
    # both a new row and one the user has yet to look at.
    assert store.add(a_row()) == bv.STATE_DISMISSED
    assert store.rows() == [], 'a dismissed row came back as new'
    assert len(store.rows(include_dismissed=True)) == 1


def test_pruning_drops_rows_of_a_gallery_that_left_the_library(store):
    store.add(a_row(series_id=1))
    store.add(a_row(series_id=2, url='https://e-hentai.org/g/222/bbb/'))
    store.mark_scanned([1, 2])

    assert store.prune({2}) == 1
    assert [r.series_id for r in store.rows()] == [2]
    assert store.scanned_ids() == {2}


def test_reading_the_rows_never_prunes_them(store):
    """The window reads them while the library is still loading in batches.

    Pruning there would delete rows for galleries that had simply not arrived yet, and take
    their scan progress with them.
    """
    store.add(a_row(series_id=1))
    store.mark_scanned([1])
    assert len(store.rows()) == 1
    assert len(store.rows()) == 1          # a second read must not have consumed anything
    assert store.scanned_ids() == {1}


def test_pruning_against_an_empty_library_is_refused(store):
    "A partial or empty index is exactly the state that made this destructive."
    store.add(a_row(series_id=1))
    store.mark_scanned([1])
    assert store.prune(set()) == 0
    assert len(store.rows()) == 1
    assert store.scanned_ids() == {1}


def test_scan_progress_round_trips_and_can_be_forgotten(store):
    store.mark_scanned([4, 5])
    assert store.scanned_ids() == {4, 5}
    store.forget_scanned()
    assert store.scanned_ids() == set()


# --- same_work ----------------------------------------------------------------------------

HELD = 'Nekokan! Meshimase'  # the untranslated original: the source titles it with this half only


@pytest.mark.parametrize('candidate', [
    '[Awa] Nekokan! Meshimase | Canned Catfood! Please Try It [English] [Digital]',
    '[Awa] Nekokan! Meshimase [Decensored]',
    '[Awa] Nekokan! Meshimase | Canned Catfood! Please Try It [English] [Decensored]',
])
def test_a_release_of_the_same_work_is_recognised(candidate):
    "match_forms offers each half of the pair, which is what reaches the original's own title."
    assert bv.same_work(HELD, candidate)


@pytest.mark.parametrize('candidate, why', [
    ('[Awa] Nekokan! Meshimase 2 | Canned Catfood! Please Try It 2 [English]',
     'a sequel: the numbering guard has to reject it whatever it scores'),
    ('[Awa] Nekokan! Meshimase Yawara [English]',
     'a different work in the same family, and it scores 84 - the fetch threshold of 70 '
     'would have accepted it'),
    ('[Other] Something Else Entirely [English]', 'unrelated'),
])
def test_a_different_work_is_rejected(candidate, why):
    assert not bv.same_work(HELD, candidate), why


def test_a_magazine_suffix_on_the_held_title_does_not_prevent_a_match():
    "The commonest stored shape: the source's title with its magazine still attached."
    held = 'Ibunka Kousai Homestay | Cultural Exchange Homestay (COMIC LOE VOL.3 Mini LO 1 Jikanme)'
    candidate = ('[Mamezou] Ibunka Kousai Homestay | Cultural Exchange Homestay '
                 '(COMIC LOE VOL.3) [English] [Digital]')
    assert bv.same_work(held, candidate)


def test_a_gallery_with_no_usable_title_matches_nothing():
    assert not bv.same_work('', '[Awa] Nekokan! Meshimase [English]')


def test_capitalisation_alone_does_not_reject_a_real_sibling():
    """The two titles were written by different uploaders, and case is what they disagree on.

    Case-folding is the fix rather than a lower score bar: folding conflates no distinct works,
    while a bar loose enough to absorb the same difference conflates a great many.
    """
    assert bv.same_work('Chuunibyou Demo H ga Shitai!',
                        '[Circle] Chuunibyou demo H ga Shitai! [English]')


def test_a_release_whose_only_difference_is_a_trailing_mark_still_matches():
    assert bv.same_work('Chuunibyou Dakedo Ai sae Areba Kankeinai yo ne',
                        '[Circle] Chuunibyou Dakedo Ai sae Areba Kankeinai yo ne! [Decensored]')


@pytest.mark.parametrize('held, candidate, why', [
    ('TORANOANA Girls Collection 2013 SUMMER TYPE-X',
     '[Circle] TORANOANA Girls Collection 2013 SUMMER TYPE-A [English]',
     'a different release in the same series, 98 apart and with no digits to tell them apart'),
    ('Kino no Tabi no Erohon V - the Erotic World',
     '[Circle] Kino no Tabi no Erohon II - the Erotic World [English]',
     'a roman numeral sequel: title_numbers reads only arabic digits, so the guard is blind'),
])
def test_a_near_identical_but_different_release_is_still_rejected(held, candidate, why):
    assert not bv.same_work(held, candidate), why


# --- the held title's romaji half (the decensored axis needs it) ---------------------------

def test_a_raw_release_matches_a_gallery_stored_with_the_full_title_pair():
    """A quarter of the censored galleries in a real library are stored with a '|' pair.

    Their decensored edition on the source carries only the romaji half, so without offering
    that half of the held title the whole axis misses them.
    """
    held = 'Nekokan! Meshimase | Canned Catfood! Please Try It'
    assert bv.same_work(held, '[Awa] Nekokan! Meshimase [Decensored]')


def test_only_the_romaji_half_of_the_held_title_is_offered():
    """Distinct works share a translated title - 'Doubutsu no Oyome-san' and
    'Kemono no Oyome-san' are both 'Animal Bride' - while a shared romaji head is nearly
    always one work translated twice.
    """
    assert bv.held_forms('Doubutsu no Oyome-san | Animal Bride') == \
        ['Doubutsu no Oyome-san | Animal Bride', 'Doubutsu no Oyome-san']
    assert not bv.same_work('Doubutsu no Oyome-san | Animal Bride',
                            '[Circle] Kemono no Oyome-san | Animal Bride [English]')


def test_the_numbering_guard_survives_the_romaji_half():
    """The head carries none of the numbers its translated half holds.

    Compared form by form, two chapters would agree on an empty set through their heads and
    read as one work.
    """
    assert not bv.same_work('Boku no Isekai Seikatsu | My Life in Another World 2',
                            '[Circle] Boku no Isekai Seikatsu | My Life in Another World 3')


def test_a_title_whose_separator_leaves_an_empty_half_is_not_split():
    assert bv.held_forms('Nekokan! Meshimase |') == ['Nekokan! Meshimase |']


# --- the consent dialog -------------------------------------------------------------------

class _G:
    def __init__(self, title='A Title'):
        self.title = title


def test_the_dialog_quotes_the_language_the_scan_will_really_use(monkeypatch):
    "The setting accepts a custom language the source never tags; the scan falls back."
    monkeypatch.setattr(app_constants, 'BETTER_VERSION_LANGUAGE', 'Klingon')
    _, detail = bv.scan_confirmation_text([_G()], [_G(), _G()])
    assert 'English' in detail
    assert 'does not tag "Klingon"' in detail


def test_the_dialog_names_the_configured_language_when_it_is_usable(monkeypatch):
    monkeypatch.setattr(app_constants, 'BETTER_VERSION_LANGUAGE', 'Spanish')
    _, detail = bv.scan_confirmation_text([_G()], [_G()])
    assert 'translated into Spanish' in detail
    assert 'does not tag' not in detail


def test_the_dialog_says_when_a_selection_is_not_what_will_be_scanned():
    """Reaching for this from the menu bar with galleries highlighted is the obvious way to try
    to scan only those, and it offers the whole tab instead.
    """
    summary, _ = bv.scan_confirmation_text([_G()] * 40, [_G()] * 7000, selected=12)
    assert 'not the 12 galleries you have selected' in summary
    assert 'Scan selected for better versions' in summary


def test_the_dialog_stays_quiet_about_a_selection_it_is_acting_on():
    summary, _ = bv.scan_confirmation_text([_G()] * 12, [_G()] * 12, selected=0)
    assert 'selected' not in summary


def test_the_estimate_counts_one_request_per_gallery(monkeypatch):
    """The scan follows a single result page, so the figure is a ceiling not a floor.

    Following the source's pagination would have made the real cost up to three times this.
    """
    monkeypatch.setattr(app_constants, 'GLOBAL_EHEN_TIME', 3)
    assert bv.SCAN_SEARCH_PAGES == 1
    assert bv.scan_estimate_seconds(100) == 100 * 5
    summary, _ = bv.scan_confirmation_text([_G()] * 720, [_G()] * 900)
    assert 'Search for a better version of 720 of the 900 galleries' in summary
    assert '1h' in summary


def test_the_log_summary_names_the_series_when_there_is_one():
    values = bv.gallery_tag_values({'Language': ['chinese'], 'Other': ['uncensored']})
    parodies = bv.gallery_parodies({'Parody': ['phantasy star online 2']})
    assert bv.tag_summary(values, parodies) == \
        'chinese / uncensored / phantasy star online 2'


@pytest.mark.parametrize('tags, expected', [
    ({'Language': ['english', 'translated'], 'Other': ['full censorship']},
     'english / censored'),
    ({'Language': ['chinese'], 'Other': ['uncensored']}, 'chinese / uncensored'),
    ({'Female': ['schoolgirl uniform']}, 'no language / censorship unstated'),
])
def test_the_log_summary_states_both_axes_including_their_unstated_case(tags, expected):
    """The rejection log is the only record of why a candidate improved on nothing.

    'Says nothing' is a third state on both axes and has to be distinguishable from the other
    two, or a correct rejection cannot be told from a broken classification.
    """
    assert bv.tag_summary(bv.gallery_tag_values(tags)) == expected


def test_a_picker_row_says_who_noted_it_rather_than_showing_nothing():
    "Nothing classified it - the user recognised it - and an empty cell reads as a bug."
    assert bv.BetterVersion(series_id=1, url='u').kinds_label == 'You noted it'
    assert bv.BetterVersion(series_id=1, url='u',
                            kinds=(bv.KIND_DECENSORED,)).kinds_label == 'Decensored'


def test_a_native_stored_title_can_never_match_a_romaji_listing(monkeypatch):
    """Which is why the scan refuses to start with 'Use japanese title' on.

    apply_metadata stores data['title']['jpn'] under that setting, so the held side is
    Japanese while a search listing gives the romaji title. They share no characters, score
    near zero, and the scan would spend hours matching nothing with no sign of why.
    """
    held = '猫缶！飯せませ'
    assert not bv.same_work(held, '[Awa] Nekokan! Meshimase | Canned Catfood! Please Try It [English]')

    monkeypatch.setattr(app_constants, 'USE_JPN_TITLE', True)
    assert 'Use japanese title' in bv.scan_blocked_reason()
    monkeypatch.setattr(app_constants, 'USE_JPN_TITLE', False)
    assert bv.scan_blocked_reason() == ''


# --- tag reading --------------------------------------------------------------------------

def test_an_unqualified_tag_is_read_the_same_as_a_namespaced_one():
    """The source writes some tags with no namespace, and those are stored under 'default'.

    A namespace-qualified lookup misses a real 'uncensored' on exactly those galleries.
    """
    assert 'uncensored' in bv.gallery_tag_values({'Other': ['uncensored']})
    assert 'uncensored' in bv.gallery_tag_values({'default': ['uncensored']})


def test_api_tags_are_normalised_the_way_stored_ones_are():
    "The api writes 'namespace:tag' with underscores where the site shows spaces."
    values = bv.api_tag_values({'tags': ['language:english', 'other:mosaic_censorship', 'uncensored']})
    assert values == {'english', 'mosaic censorship', 'uncensored'}


# --- better_kinds -------------------------------------------------------------------------

def test_a_translation_of_an_untranslated_gallery_is_a_better_version():
    held = bv.gallery_tag_values({'Female': ['schoolgirl uniform']})  # no language tag at all
    candidate = bv.api_tag_values({'tags': ['language:english', 'language:translated']})
    assert bv.better_kinds(held, candidate, 'english') == (bv.KIND_TRANSLATED,)


def test_a_gallery_already_translated_gets_no_translation_row():
    held = bv.gallery_tag_values({'Language': ['english', 'translated']})
    candidate = bv.api_tag_values({'tags': ['language:english', 'language:translated']})
    assert bv.better_kinds(held, candidate, 'english') == ()


def test_a_translation_into_another_language_is_not_the_target():
    held = bv.gallery_tag_values({})
    candidate = bv.api_tag_values({'tags': ['language:russian', 'language:translated']})
    assert bv.better_kinds(held, candidate, 'english') == ()


def test_an_uncensored_release_of_a_censored_gallery_is_a_better_version():
    held = bv.gallery_tag_values({'Other': ['mosaic censorship']})
    candidate = bv.api_tag_values({'tags': ['other:uncensored']})
    assert bv.better_kinds(held, candidate, 'english') == (bv.KIND_DECENSORED,)


def test_an_uncensored_release_of_a_gallery_nobody_tagged_is_offered():
    """The held gallery only has to lack the uncensored tag, not to state a censorship one.

    A release nobody tagged either way stays in scope; the cost is a row for a gallery that was
    already uncensored without saying so.
    """
    held = bv.gallery_tag_values({'Female': ['schoolgirl uniform']})
    candidate = bv.api_tag_values({'tags': ['other:uncensored', 'language:translated',
                                            'language:english']})
    assert bv.better_kinds(held, candidate, 'english') == (bv.KIND_DECENSORED,
                                                          bv.KIND_TRANSLATED)


# --- the series a release belongs to ------------------------------------------------------
# A short title survives canonicalisation with nothing left to tell two works apart, and the
# parody tag is what the source normalises well enough to compare.

def test_the_parody_is_read_from_the_namespace_not_from_any_matching_tag():
    assert bv.gallery_parodies({'Parody': ['phantasy star online 2'],
                                'Other': ['uncensored']}) == {'phantasy star online 2'}
    assert bv.api_parodies({'tags': ['parody:fate grand order', 'language:english']}) \
        == {'fate grand order'}
    # An unqualified tag of the same name says nothing about which series a release is in.
    assert bv.gallery_parodies({'default': ['phantasy star online 2']}) == set()


def test_api_parodies_normalises_the_underscores_the_api_uses():
    assert bv.api_parodies({'tags': ['parody:kantai_collection']}) == {'kantai collection'}


def test_two_works_sharing_a_short_title_are_told_apart_by_their_series():
    """Reported from a real run: a Phantasy Star Online 2 doujin called 'Seishoku' was offered
    a Fate/Grand Order one of the same name. Both canonicalise to the same eight characters.
    """
    assert not bv.same_parody({'phantasy star online 2'}, {'fate grand order'})


def test_one_series_written_two_ways_in_a_title_is_one_tag():
    """Why the tag beats the title: 'Kantai Collection' and 'Kantai Collection -KanColle-' are
    the same work, and no string comparison of those separates them from a real mismatch.
    """
    assert bv.same_parody({'kantai collection'}, {'kantai collection'})


def test_a_crossover_still_matches_a_release_tagged_with_one_of_its_series():
    assert bv.same_parody({'kantai collection', 'azur lane'}, {'kantai collection'})


@pytest.mark.parametrize('held, candidate', [
    (set(), {'fate grand order'}),
    ({'phantasy star online 2'}, set()),
    (set(), set()),
])
def test_an_untagged_series_decides_nothing(held, candidate):
    "Plenty of releases carry no parody tag, so absence cannot be treated as a mismatch."
    assert bv.same_parody(held, candidate)


# --- who made a release -------------------------------------------------------------------
# The series is not enough on its own: two doujins of one franchise share it as readily as
# they share a short title. Every case below is a row a real library-wide scan stored.

def test_the_creator_is_read_from_both_namespaces():
    assert bv.gallery_creators({'Artist': ['nyanyakun'], 'Group': ['nyanyahouse'],
                                'Other': ['uncensored']}) == {'nyanyakun', 'nyanyahouse'}
    assert bv.api_creators({'tags': ['artist:ikameshi', 'group:ikameshi_shokudou',
                                     'language:english']}) == {'ikameshi', 'ikameshi shokudou'}
    # Unqualified, an artist's name says nothing about who made the release.
    assert bv.gallery_creators({'default': ['nyanyakun']}) == set()


def test_two_doujins_of_one_franchise_are_told_apart_by_their_creator():
    """From a real scan: 'MIZUGI Archive' by guchico was offered Subachi's 'Mizugi Archive'.

    Both are Blue Archive, so the series tag agrees, and both canonicalise to the same title.
    """
    assert bv.same_parody({'blue archive'}, {'blue archive'})
    assert not bv.same_creator({'guchico'}, {'subachi', 'subachikyu'})


def test_a_character_name_as_a_title_is_not_a_work():
    """Nine AI sets of 'Fischl' were offered against a held gallery of that name. The title is
    a character, the series is Genshin Impact on both sides, and only the creator differs.
    """
    assert not bv.same_creator({'pineapple panda'}, {'miyabi'})


def test_a_release_credited_to_its_circle_alone_still_matches_its_artist():
    "The source credits one, the other or both, so the two namespaces are pooled."
    assert bv.same_creator({'yabuishikai', 'sui shinon'}, {'yabuishikai'})


def test_the_creator_tag_beats_the_names_written_in_the_title():
    """Why the tag rather than the '[Circle (Artist)]' group: across a real run the titles
    wrote 'jackdempa' and '[Jaku Denpa]' for one artist, and '[Google Translated]' where an
    artist belongs. The source's own namespace normalises all of it.
    """
    assert bv.same_creator({'jackdempa'}, bv.api_creators({'tags': ['artist:jackdempa']}))


@pytest.mark.parametrize('held, candidate', [
    (set(), {'mori takuya'}),
    ({'hiiragi yuichi'}, set()),
    (set(), set()),
])
def test_an_uncredited_release_decides_nothing(held, candidate):
    "29 of 709 candidates in a real run carried no creator tag; absence is not a mismatch."
    assert bv.same_creator(held, candidate)


# --- a row has to be an improvement, not a trade ------------------------------------------
# Both of these come from a real scan run: the first is the row it got wrong.

def test_an_uncensored_release_in_another_language_is_not_a_better_version():
    """Reported once against a real gallery: 'Vanessa Customize', held in English and censored,
    was offered a Spanish uncensored release. Taking it trades the language away.
    """
    held = bv.gallery_tag_values({'Language': ['english', 'translated'],
                                  'Other': ['full censorship']})
    candidate = bv.api_tag_values({'tags': ['language:spanish', 'language:translated',
                                            'other:uncensored']})
    assert bv.better_kinds(held, candidate, 'english') == ()


def test_a_translation_into_the_target_language_is_still_offered_for_a_foreign_gallery():
    """The other row from the same run, which was right: 'Seishoku', held in Chinese and
    already uncensored, was offered an English release.
    """
    held = bv.gallery_tag_values({'Language': ['chinese'], 'Other': ['uncensored']})
    candidate = bv.api_tag_values({'tags': ['language:english', 'language:translated']})
    assert bv.better_kinds(held, candidate, 'english') == (bv.KIND_TRANSLATED,)


def test_a_censored_translation_is_not_offered_for_an_uncensored_gallery():
    "The mirror of the Vanessa case: it would give the censorship back to gain the language."
    held = bv.gallery_tag_values({'Language': ['chinese'], 'Other': ['uncensored']})
    candidate = bv.api_tag_values({'tags': ['language:english', 'language:translated',
                                            'other:mosaic censorship']})
    assert bv.better_kinds(held, candidate, 'english') == ()


def test_an_uncensored_raw_is_not_offered_for_a_translated_gallery():
    """A raw release states no language, so taking it loses the translation.

    This is the shape the held title's romaji half reaches, so it has to be rejected here
    rather than never matched.
    """
    held = bv.gallery_tag_values({'Language': ['english', 'translated'],
                                  'Other': ['mosaic censorship']})
    candidate = bv.api_tag_values({'tags': ['other:uncensored']})
    assert bv.better_kinds(held, candidate, 'english') == ()


def test_an_uncensored_raw_is_offered_for_an_untranslated_gallery():
    "Same languages on both sides - nothing is being traded away."
    held = bv.gallery_tag_values({'Other': ['mosaic censorship']})
    candidate = bv.api_tag_values({'tags': ['other:uncensored']})
    assert bv.better_kinds(held, candidate, 'english') == (bv.KIND_DECENSORED,)


def test_a_release_that_is_both_reports_both():
    held = bv.gallery_tag_values({'Other': ['full censorship']})
    candidate = bv.api_tag_values({'tags': ['other:uncensored', 'language:english',
                                            'language:translated']})
    kinds = bv.better_kinds(held, candidate, 'english')
    assert kinds == (bv.KIND_DECENSORED, bv.KIND_TRANSLATED)


def test_an_already_uncensored_gallery_gets_no_decensored_row():
    held = bv.gallery_tag_values({'Other': ['mosaic censorship', 'uncensored']})
    candidate = bv.api_tag_values({'tags': ['other:uncensored']})
    assert bv.better_kinds(held, candidate, 'english') == ()


# --- better_kinds, the translation quality axis ---------------------------------------------
# The source marks a translation it considers poor, so a gallery can already be in the language
# you want and still be worth replacing. Three tags say so, and the improvement is a release in
# the same language carrying none of them.

def test_a_clean_release_of_a_roughly_translated_gallery_is_a_better_version():
    held = bv.gallery_tag_values({'Language': ['english', 'translated', 'rough translation']})
    candidate = bv.api_tag_values({'tags': ['language:english', 'language:translated']})
    assert bv.better_kinds(held, candidate, 'english') == (bv.KIND_REFINED,)


@pytest.mark.parametrize('tag', ['rewrite', 'rough grammar', 'rough translation'])
def test_each_rough_tag_makes_a_gallery_worth_replacing(tag):
    held = bv.gallery_tag_values({'Language': ['english', 'translated', tag]})
    candidate = bv.api_tag_values({'tags': ['language:english', 'language:translated']})
    assert bv.better_kinds(held, candidate, 'english') == (bv.KIND_REFINED,)


def test_a_candidate_that_is_rough_in_its_own_way_is_not_an_improvement():
    "Trading one caveat for another is not worth telling anyone about."
    held = bv.gallery_tag_values({'Language': ['english', 'translated', 'rough translation']})
    candidate = bv.api_tag_values({'tags': ['language:english', 'language:translated',
                                            'language:rewrite']})
    assert bv.better_kinds(held, candidate, 'english') == ()


def test_a_gallery_whose_translation_is_unmarked_gets_no_quality_row():
    "Nothing says the held translation is poor, so a release that is equally silent is a wash."
    held = bv.gallery_tag_values({'Language': ['english', 'translated']})
    candidate = bv.api_tag_values({'tags': ['language:english', 'language:translated']})
    assert bv.better_kinds(held, candidate, 'english') == ()


def test_an_untranslated_candidate_cannot_refine_a_rough_translation():
    "It carries none of the held gallery's languages, so taking it would lose the translation."
    held = bv.gallery_tag_values({'Language': ['english', 'translated', 'rough translation']})
    candidate = bv.api_tag_values({'tags': ['female:schoolgirl uniform']})
    assert bv.better_kinds(held, candidate, 'english') == ()


def test_a_rough_tag_with_no_language_beside_it_refines_nothing():
    """The source writes one without a language, and then there is no translation to improve.

    Without the guard the held gallery states no language, so every candidate that states none
    either satisfies the language condition and reads as a cleaner version of nothing.
    """
    held = bv.gallery_tag_values({'Language': ['rough translation']})
    candidate = bv.api_tag_values({'tags': ['female:schoolgirl uniform']})
    assert bv.better_kinds(held, candidate, 'english') == ()


def test_a_refined_release_that_puts_the_censorship_back_is_a_trade():
    held = bv.gallery_tag_values({'Language': ['english', 'translated', 'rough grammar'],
                                  'Other': ['uncensored']})
    candidate = bv.api_tag_values({'tags': ['language:english', 'language:translated',
                                            'other:mosaic_censorship']})
    assert bv.better_kinds(held, candidate, 'english') == ()


def test_a_release_that_is_both_cleaner_and_uncensored_reports_both():
    held = bv.gallery_tag_values({'Language': ['english', 'translated', 'rough translation'],
                                  'Other': ['mosaic censorship']})
    candidate = bv.api_tag_values({'tags': ['language:english', 'language:translated',
                                            'other:uncensored']})
    assert bv.better_kinds(held, candidate, 'english') == (bv.KIND_DECENSORED, bv.KIND_REFINED)


def test_a_rough_translation_is_named_in_the_log_summary():
    "The log is the only record of why a candidate was turned down, so both sides state it."
    values = bv.gallery_tag_values({'Language': ['english', 'translated', 'rough translation']})
    assert bv.tag_summary(values) == 'english / censorship unstated / rough: rough translation'
    clean = bv.gallery_tag_values({'Language': ['english', 'translated']})
    assert bv.tag_summary(clean) == 'english / censorship unstated'


# --- worth_scanning -----------------------------------------------------------------------

class FakeGallery:
    def __init__(self, link='https://e-hentai.org/g/1/a/', tags=None, title='A Title', id=1):
        self.link, self.tags, self.title, self.id = link, tags or {}, title, id


def test_an_untranslated_gallery_is_worth_a_query():
    g = FakeGallery(tags={'Female': ['schoolgirl uniform']})
    assert bv.worth_scanning(g, 'english')


def test_a_censored_gallery_is_worth_a_query_even_when_already_translated():
    g = FakeGallery(tags={'Language': ['english', 'translated'],
                          'Other': ['mosaic censorship']})
    assert bv.worth_scanning(g, 'english')


def test_a_gallery_with_nothing_left_to_find_is_skipped():
    "Already in the target language and already uncensored: a query could not pay off."
    g = FakeGallery(tags={'Language': ['english', 'translated'], 'Other': ['uncensored']})
    assert not bv.worth_scanning(g, 'english')


def test_a_roughly_translated_gallery_is_worth_a_query_despite_having_everything_else():
    """Already in the target language and already uncensored, but marked a rough translation.

    This is the gallery the two-axis filter dropped: nothing was left to find until a better
    translation counted as something to find.
    """
    g = FakeGallery(tags={'Language': ['english', 'translated', 'rough translation'],
                          'Other': ['uncensored']})
    assert bv.worth_scanning(g, 'english')


def test_a_gallery_the_source_never_tagged_is_skipped():
    "No tags means the source has never been asked about it, so neither axis can be decided."
    assert not bv.worth_scanning(FakeGallery(tags={}), 'english')


def test_a_gallery_with_no_link_is_skipped():
    """Its stored title is still the folder name, not the source's.

    same_work needs the source's own title on both sides; a folder name is what the ordinary
    metadata pass is for.
    """
    g = FakeGallery(link='', tags={'Female': ['schoolgirl uniform']})
    assert not bv.worth_scanning(g, 'english')


# --- scan_query ---------------------------------------------------------------------------

def test_the_query_is_the_romaji_half_alone():
    """Quoting the whole pair would exclude the untranslated original, which has only a half.

    No artist and no language filter either: a language filter would exclude the very
    translations the scan looks for.
    """
    g = FakeGallery(title='Nekokan! Meshimase | Canned Catfood! Please Try It')
    assert bv.scan_query(g) == '"Nekokan! Meshimase"'


def test_a_trailing_parody_group_is_dropped_from_the_query():
    """search_form peels trailing bracketed groups, and that is wanted here.

    The query gets broader, which is how the other releases turn up, and canonical_title
    strips the same group from both sides when the hits are scored.
    """
    g = FakeGallery(title='Karakasa Obake to Miko (Touhou Project)')
    assert bv.scan_query(g) == '"Karakasa Obake to Miko"'


def test_a_double_space_in_a_source_title_does_not_cut_the_query_short():
    """fetch.split_on_separator treats a whitespace run as a deleted separator.

    That is a filesystem artefact of a folder name; a source's own title has a real one or
    none, so scan_query must not use it.
    """
    g = FakeGallery(title='Some Title  With Two Spaces')
    assert bv.scan_query(g) == '"Some Title With Two Spaces"'


def test_a_gallery_whose_title_reduces_to_nothing_gets_no_query():
    "An empty query matches the whole site."
    assert bv.scan_query(FakeGallery(title='')) == ''


# --- the classification pass itself --------------------------------------------------------
# Every guard above is a function a test can call directly, which proves nothing about whether
# _classify consults it. These drive the pass with a stub source instead.

class FakeHen:
    "Answers get_metadata from a url -> gmetadata entry map, the way EHen's api does."

    def __init__(self, entries):
        self.entries = entries
        self.batches = []

    def get_metadata(self, urls):
        self.batches.append(list(urls))
        gid_to_url = {i: url for i, url in enumerate(urls, 1)}
        gmetadata = [dict(self.entries[url], gid=i) for i, url in enumerate(urls, 1)
                     if url in self.entries]
        return {'gmetadata': gmetadata}, gid_to_url


def classify(store, gallery, candidates, entries, target='english'):
    "Runs one classification pass and returns the rows it stored."
    scan = bv.BetterVersionScan()
    scan._classify(FakeHen(entries), store, [(gallery, candidates)], target)
    return store.rows()


def test_a_release_by_another_creator_never_reaches_the_list(store):
    """The row this whole guard exists for, from a real library-wide scan: a held 'Pink
    Archive' by unacchi was offered Alpha91's gallery of the same name. Same title, same
    series, different artist.
    """
    held = FakeGallery(title='Pink Archive (Blue Archive)',
                       tags={'Group': ['unahouse'], 'Artist': ['unacchi'],
                             'Parody': ['blue archive'], 'Other': ['mosaic censorship']})
    url = 'https://e-hentai.org/g/2699042/635a4d5ea9/'
    entries = {url: {'title': '[Alpha91] Pink Archive (Blue Archive)', 'title_jpn': '',
                     'thumb': '', 'tags': ['artist:alpha91', 'parody:blue_archive',
                                           'other:uncensored']}}
    assert classify(store, held, [(entries[url]['title'], url)], entries) == []


def test_the_same_release_by_the_same_creator_still_reaches_the_list(store):
    "The guard must not cost the rows it was never aimed at."
    held = FakeGallery(title='Pink Archive (Blue Archive)',
                       tags={'Group': ['unahouse'], 'Artist': ['unacchi'],
                             'Parody': ['blue archive'], 'Other': ['mosaic censorship']})
    url = 'https://e-hentai.org/g/2699043/635a4d5ea0/'
    entries = {url: {'title': '[Unahouse (Unacchi)] Pink Archive (Blue Archive)',
                     'title_jpn': '', 'thumb': '',
                     'tags': ['artist:unacchi', 'parody:blue_archive', 'other:uncensored']}}
    rows = classify(store, held, [(entries[url]['title'], url)], entries)
    assert [r.kinds for r in rows] == [(bv.KIND_DECENSORED,)]


def test_a_release_the_source_credits_to_nobody_is_still_offered(store):
    "The guard fails open, so an uncredited release behaves exactly as it did before it."
    held = FakeGallery(title='Nekokan! Meshimase',
                       tags={'Artist': ['nekonyan'], 'Other': ['mosaic censorship']})
    url = 'https://e-hentai.org/g/3/c/'
    entries = {url: {'title': 'Nekokan! Meshimase', 'title_jpn': '', 'thumb': '',
                     'tags': ['other:uncensored']}}
    rows = classify(store, held, [(entries[url]['title'], url)], entries)
    assert [r.kinds for r in rows] == [(bv.KIND_DECENSORED,)]


def test_a_rejected_candidate_still_counts_its_gallery_as_scanned(store):
    "Otherwise the gallery is searched for again on every later run, forever."
    held = FakeGallery(title='Pink Archive (Blue Archive)', id=7,
                       tags={'Artist': ['unacchi'], 'Other': ['mosaic censorship']})
    url = 'https://e-hentai.org/g/4/d/'
    entries = {url: {'title': '[Alpha91] Pink Archive', 'title_jpn': '', 'thumb': '',
                     'tags': ['artist:alpha91', 'other:uncensored']}}
    classify(store, held, [(entries[url]['title'], url)], entries)
    assert store.scanned_ids() == {7}


# --- rechecking the rows already on the list -----------------------------------------------
# A scan records every gallery it searched, so a guard added afterwards can only reach the
# rows it already stored through this path.

def test_a_hand_noted_row_is_never_rechecked(store):
    """The user picked it from the chooser while looking at the alternatives.

    That is better evidence than the tags, and the tags were never what put it on the list.
    """
    store.add(a_row(series_id=1, source=bv.SOURCE_PICKER))
    store.add(a_row(series_id=2, url='https://e-hentai.org/g/222/bbb/', source=bv.SOURCE_SCAN))
    assert [r.series_id for r in bv.recheckable_rows(store)] == [2]


def test_a_row_by_another_creator_is_rejected_on_recheck():
    held = FakeGallery(tags={'Artist': ['unacchi'], 'Parody': ['blue archive']})
    entry = {'tags': ['artist:alpha91', 'parody:blue_archive']}
    assert bv.row_rejection(held, entry) == 'a different creator'


def test_a_row_of_another_series_is_rejected_on_recheck():
    """The one row a real library-wide scan stored before the series guard existed: a Phantasy
    Star Online 2 doujin called 'Seishoku' against a Fate/Grand Order one.
    """
    held = FakeGallery(tags={'Artist': ['nyanyakun'], 'Parody': ['phantasy star online 2']})
    entry = {'tags': ['artist:ikameshi', 'parody:fate_grand_order']}
    assert bv.row_rejection(held, entry) == 'a different series'


def test_a_row_that_still_looks_right_survives_a_recheck():
    held = FakeGallery(tags={'Group': ['unahouse'], 'Artist': ['unacchi'],
                             'Parody': ['blue archive']})
    entry = {'tags': ['artist:unacchi', 'parody:blue_archive', 'other:uncensored']}
    assert bv.row_rejection(held, entry) == ''


def test_the_recheck_never_judges_a_row_on_whether_it_still_improves():
    """A metadata fetch rewrites the held gallery's tags, so the improvement axes move under
    the list. Dismissing a row over that would dismiss it for a change in the library.
    """
    held = FakeGallery(tags={'Artist': ['unacchi'], 'Other': ['uncensored'],
                             'Language': ['english', 'translated']})
    # Improves on neither axis any more, and is still the same work.
    entry = {'tags': ['artist:unacchi', 'other:mosaic censorship']}
    assert bv.row_rejection(held, entry) == ''


# --- putting a dismissed row back ----------------------------------------------------------
# A row can be dismissed by a rule as well as by hand, and the recheck judges against the held
# gallery's tags as they stand - which a metadata fetch may have rewritten since. That is why
# dismissal has a way back rather than being a delete.

def test_a_dismissed_row_can_be_put_back_on_the_list(store):
    store.add(a_row())
    store.dismiss(1, 'https://e-hentai.org/g/111/aaa/')
    assert store.rows() == []

    store.restore(1, 'https://e-hentai.org/g/111/aaa/')
    rows = store.rows()
    assert [r.url for r in rows] == ['https://e-hentai.org/g/111/aaa/']
    assert rows[0].state == bv.STATE_NEW, rows[0].state


def test_a_restored_row_keeps_everything_it_was_stored_with(store):
    "Restoring must not cost the classification, or the row comes back saying nothing."
    store.add(a_row(kinds=(bv.KIND_DECENSORED, bv.KIND_TRANSLATED), native_title='\u539f\u9898'))
    store.dismiss(1, 'https://e-hentai.org/g/111/aaa/')
    store.restore(1, 'https://e-hentai.org/g/111/aaa/')

    row = store.rows()[0]
    assert row.kinds == (bv.KIND_DECENSORED, bv.KIND_TRANSLATED)
    assert row.native_title == '\u539f\u9898'
    assert row.held_title == 'Nekokan! Meshimase'


def test_restoring_a_row_that_was_never_dismissed_changes_nothing(store):
    store.add(a_row())
    store.restore(1, 'https://e-hentai.org/g/111/aaa/')
    assert [r.state for r in store.rows()] == [bv.STATE_NEW]


def test_a_later_scan_offers_a_restored_row_as_already_listed(store):
    """Restoring puts the row back in the 'new' state, so a rescan has to report it as one it
    already knows rather than as a fresh find.
    """
    store.add(a_row())
    store.dismiss(1, 'https://e-hentai.org/g/111/aaa/')
    store.restore(1, 'https://e-hentai.org/g/111/aaa/')
    assert store.add(a_row()) == bv.STATE_NEW
