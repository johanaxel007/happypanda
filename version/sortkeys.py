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
"""The sort vocabulary: every name a gallery view can be sorted by, and the value each compares.

Each name is defined once, with its label, the value it compares and the direction it starts in,
so a name means the same thing wherever a sort is asked for by it. A value is a plain `str` or
`int`, cheap to produce and compared natively, so a sort of the whole library never builds a Qt
date per comparison.

Imports nothing from the application at module level, so it is safe anywhere in the import order.
"""
import datetime
from typing import Any, Callable, NamedTuple

# What a gallery with no date compares as, so it sorts after every dated one in either direction.
# Far outside any date_value, and still inside the 64-bit integer a Qt model value carries.
EMPTY_LAST_ASCENDING = 2 ** 62
EMPTY_LAST_DESCENDING = -(2 ** 62)


class SortKey(NamedTuple):
    name: str
    label: str
    value: Callable[[Any], Any]
    descending: bool  # the direction a fresh pick of this sort starts in
    late: bool = False  # reads chapters or tags, which startup loads only after its first sort


def date_value(value):
    """Returns the stored clock time as whole seconds counted from its own fields, or None.

    Counting from the fields orders exactly as the naive `datetime` does. Going through a time zone
    instead would make a local time that does not exist, inside a daylight saving gap, sort out of
    place.
    """
    if isinstance(value, datetime.datetime):
        return value.toordinal() * 86400 + value.hour * 3600 + value.minute * 60 + value.second
    if isinstance(value, datetime.date):
        return value.toordinal() * 86400
    return None


def _tags_text(gallery):
    import utils  # utils loads Qt, which this module must not do on import
    return utils.tag_to_string(gallery.tags or {})


_KEYS = (
    SortKey('title', 'Title', lambda g: g.title or '', False),
    SortKey('artist', 'Author', lambda g: g.artist or '', False),
    SortKey('date_added', 'Date Added', lambda g: date_value(g.date_added), True),
    SortKey('pub_date', 'Date Published', lambda g: date_value(g.pub_date), True),
    SortKey('times_read', 'Read Count', lambda g: g.times_read or 0, True),
    SortKey('last_read', 'Last Read', lambda g: date_value(g.last_read), True),
    SortKey('rating', 'Rating', lambda g: g.rating or 0, True),
    SortKey('page_count', 'Page Count', lambda g: g.chapters.pages(), True, late=True),
    SortKey('tags', 'Tags', _tags_text, False, late=True),
    SortKey('type', 'Type', lambda g: g.type or '', False),
    SortKey('fav', 'Favorite', lambda g: g.fav or 0, True),
    SortKey('chapters', 'Chapters', lambda g: len(g.chapters), True, late=True),
    SortKey('language', 'Language', lambda g: g.language or '', False),
    SortKey('link', 'URL', lambda g: g.link or '', False),
    SortKey('description', 'Description', lambda g: g.info or '', False),
)

KEYS = {key.name: key for key in _KEYS}

MENU_SORTS = ('artist', 'date_added', 'pub_date', 'last_read', 'title', 'rating', 'times_read',
              'page_count')
"""The sort names offered as a list of choices, in the order they are listed."""


def saved_descending(name, stored):
    """Returns whether the saved sort `name` opens descending, given the direction stored beside it.

    `stored` is 'desc' or 'asc'. Anything else, including a direction saved beside a sort name
    this version does not know, starts that sort in its own direction.
    """
    key = KEYS.get(name)
    if key is None:
        return KEYS['title'].descending
    if stored in ('desc', 'asc'):
        return stored == 'desc'
    return key.descending


def sort_value(name, gallery, descending):
    """Returns what `gallery` compares as under the sort `name` in the given direction.

    A missing value becomes whichever extreme puts it last in that direction, so the galleries
    that have one are never pushed below the ones that do not.
    """
    value = KEYS[name].value(gallery)
    if value is None:
        return EMPTY_LAST_DESCENDING if descending else EMPTY_LAST_ASCENDING
    return value
