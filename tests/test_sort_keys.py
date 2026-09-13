"""Tests for the sort vocabulary: each sort name's value, its starting direction and its saved form.

The values are what Qt compares, so these check the orders they produce when compared natively,
which is how the proxy compares a `str` or an `int`.
"""

import datetime

import pytest

import app_constants  # noqa: F401  (must precede gallerydb, which the tags sort reaches through utils)
import gallerydb  # noqa: F401
import sortkeys


class FakeChapters:
    def __init__(self, pages):
        self._pages = pages

    def pages(self):
        return sum(self._pages)

    def __len__(self):
        return len(self._pages)


class FakeGallery:
    """A gallery reduced to the attributes a sort reads."""

    def __init__(self, **values):
        self.title = 'untitled'
        self.artist = ''
        self.date_added = datetime.datetime(2020, 1, 1)
        self.pub_date = None
        self.last_read = None
        self.times_read = 0
        self.rating = 0
        self.chapters = FakeChapters([10])
        self.tags = {}
        self.type = ''
        self.fav = 0
        self.language = ''
        self.link = ''
        self.info = ''
        for name, value in values.items():
            setattr(self, name, value)


def ordered(name, galleries, descending):
    """Returns the titles in the order the proxy would show them."""
    return [g.title for g in sorted(galleries, key=lambda g: sortkeys.sort_value(name, g, descending),
                                    reverse=descending)]


def test_date_value_orders_as_the_datetime_does():
    stamps = [datetime.datetime(2024, 3, 31, 2, 30), datetime.datetime(1999, 12, 31, 23, 59, 59),
              datetime.datetime(2024, 3, 31, 1, 59, 59), datetime.datetime(2000, 1, 1)]
    assert sorted(stamps, key=sortkeys.date_value) == sorted(stamps)


def test_date_value_of_no_date_is_none():
    assert sortkeys.date_value(None) is None
    assert sortkeys.date_value('') is None


def test_date_value_is_the_int_a_qt_model_can_carry():
    value = sortkeys.date_value(datetime.datetime(9999, 12, 31, 23, 59, 59))
    assert isinstance(value, int)
    assert sortkeys.EMPTY_LAST_DESCENDING < sortkeys.date_value(datetime.datetime(1, 1, 1))
    assert value < sortkeys.EMPTY_LAST_ASCENDING < 2 ** 63


@pytest.mark.parametrize('name, attribute', [('pub_date', 'pub_date'), ('last_read', 'last_read'),
                                             ('date_added', 'date_added')])
@pytest.mark.parametrize('descending', [False, True])
def test_a_gallery_with_no_date_sorts_last_in_either_direction(name, attribute, descending):
    galleries = [FakeGallery(title='none-1', **{attribute: None}),
                 FakeGallery(title='old', **{attribute: datetime.datetime(2018, 5, 5)}),
                 FakeGallery(title='none-2', **{attribute: None}),
                 FakeGallery(title='new', **{attribute: datetime.datetime(2019, 5, 5)})]
    shown = ordered(name, galleries, descending)
    assert shown[:2] == (['new', 'old'] if descending else ['old', 'new'])
    assert sorted(shown[2:]) == ['none-1', 'none-2']


def test_counts_and_strings_compare_as_their_own_type():
    galleries = [FakeGallery(title='b', chapters=FakeChapters([5, 5]), times_read=3),
                 FakeGallery(title='a', chapters=FakeChapters([30]), times_read=None)]
    assert ordered('page_count', galleries, True) == ['a', 'b']
    assert ordered('chapters', galleries, True) == ['b', 'a']
    assert ordered('times_read', galleries, True) == ['b', 'a']
    assert ordered('title', galleries, False) == ['a', 'b']


def test_tags_compare_as_the_column_shows_them():
    import utils
    tags = {'female': ['stockings', 'glasses'], 'default': ['full color']}
    assert sortkeys.sort_value('tags', FakeGallery(tags=tags), False) == utils.tag_to_string(tags)
    assert sortkeys.sort_value('tags', FakeGallery(tags=None), False) == ''


def test_every_value_is_a_type_qt_compares_natively():
    gallery = FakeGallery(title=None, artist=None, type=None, language=None, link=None, info=None,
                          rating=None, fav=None)
    for name in sortkeys.KEYS:
        for descending in (False, True):
            assert isinstance(sortkeys.sort_value(name, gallery, descending), (str, int)), name


def test_the_menu_offers_only_known_sorts_and_each_once():
    assert set(sortkeys.MENU_SORTS) <= set(sortkeys.KEYS)
    assert len(set(sortkeys.MENU_SORTS)) == len(sortkeys.MENU_SORTS)


@pytest.mark.parametrize('name, stored, descending', [
    ('title', 'desc', True),
    ('date_added', 'asc', False),
    ('date_added', '', True),      # never saved: the sort's own direction
    ('title', None, False),        # the ini's 'none'
    ('artist', 'sideways', False),
    ('removed_sort', 'desc', False),  # a name this version does not know falls back to title
])
def test_a_saved_direction_applies_only_when_it_is_one(name, stored, descending):
    assert sortkeys.saved_descending(name, stored) is descending


def test_sorts_that_read_late_loaded_data_are_marked():
    assert {name for name, key in sortkeys.KEYS.items() if key.late} == {'page_count', 'tags',
                                                                           'chapters'}
