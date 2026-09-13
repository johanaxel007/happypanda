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
"""Reading the source's tags, off a stored gallery or off a raw gmetadata entry.

What this is worth is a single definition of what a namespace means, rather than one per place
that needs it: the api writes `artist:foo_bar` where a stored gallery holds `foo bar` under an
`Artist` key, and anything comparing the two has to fold that the same way at both ends or the
comparison reports a mismatch between one name and itself.

Deliberately imports nothing from the rest of the application, so it is safe at any point in
the import order - including ahead of the `app_constants` / `gallerydb` cycle.

Nothing here writes anywhere. The gmetadata readers take the **raw** api response rather than
`parse_metadata`'s output, which keeps them one call further away from `apply_metadata`.
"""

# Language names as a source writes them, in a bracketed title tag - "[Russian]",
# "[English, Chinese]" - or in its `language:` namespace. The source's own documented set, so a
# name absent from here is one no release can be tagged with.
LANGUAGE_TAGS = frozenset((
    'afrikaans', 'albanian', 'arabic', 'aramaic', 'armenian', 'bengali', 'bosnian', 'bulgarian',
    'burmese', 'catalan', 'cebuano', 'chinese', 'cree', 'creole', 'croatian', 'czech', 'danish',
    'dutch', 'english', 'esperanto', 'estonian', 'finnish', 'french', 'georgian', 'german',
    'greek', 'gujarati', 'hebrew', 'hindi', 'hmong', 'hungarian', 'icelandic', 'indonesian',
    'irish', 'italian', 'japanese', 'javanese', 'kannada', 'kazakh', 'khmer', 'korean',
    'kurdish', 'ladino', 'lao', 'latin', 'latvian', 'marathi', 'mongolian', 'ndebele', 'nepali',
    'norwegian', 'oromo', 'papiamento', 'pashto', 'persian', 'polish', 'portuguese', 'punjabi',
    'romanian', 'russian', 'sango', 'sanskrit', 'serbian', 'shona', 'slovak', 'slovenian',
    'somali', 'spanish', 'swahili', 'swedish', 'tagalog', 'tamil', 'telugu', 'thai', 'tibetan',
    'tigrinya', 'turkish', 'ukrainian', 'urdu', 'vietnamese', 'welsh', 'yiddish', 'zulu',
    # Undocumented, and kept because the two failures are not symmetric: a name the source does
    # tag but never listed reads as "states no language" if it is missing here, which offers a
    # foreign release as a match, while one it does not tag only ever matches nothing.
    'azerbaijani', 'filipino', 'lithuanian', 'malay', 'sinhala',
))

# The namespace naming the series a release belongs to, read qualified: the point of it is that
# it is a parody tag rather than a word that happens to appear elsewhere in the tags.
PARODY_NAMESPACE = 'parody'

# The namespaces naming who made a release. Both, because the source credits a doujin to its
# circle and to the artist inside it inconsistently, and either one matching is enough.
CREATOR_NAMESPACES = frozenset(('artist', 'group'))


# --- every tag, namespace discarded --------------------------------------------------------

def gallery_tag_values(tags):
    """Every tag stored on a gallery, lowercased and without its namespace.

    `Gallery.tags` maps a namespace to its tags, and the source writes some tags with no
    namespace at all - those are stored under 'default'. Dropping the namespace is what makes
    one lookup find both.
    """
    values = set()
    for group in (tags or {}).values():
        if isinstance(group, str):
            group = (group,)
        for tag in group or ():
            value = str(tag).strip().lower()
            if value:
                values.add(value)
    return values


def api_tag_values(entry):
    """Every tag of a raw gmetadata entry, in the same form as a stored gallery's.

    The api writes each tag as 'namespace:tag' or bare, with underscores where the site shows
    spaces. parse_metadata applies the same normalisation on its way to a gallery; it is
    repeated here rather than reused because none of this may reach anything that writes one.
    """
    values = set()
    for tag in (entry or {}).get('tags') or ():
        value = str(tag).split(':', 1)[-1].strip().lower().replace('_', ' ')
        if value:
            values.add(value)
    return values


# --- the tags of one namespace -------------------------------------------------------------

def gallery_namespace_values(tags, namespaces):
    """A stored gallery's tags in the given namespaces, lowercased.

    Namespace-qualified, unlike `gallery_tag_values`: these tags answer "which series" and
    "whose work", and an unqualified tag of the same name would answer neither.
    """
    found = set()
    for namespace, group in (tags or {}).items():
        if str(namespace).strip().lower() not in namespaces:
            continue
        if isinstance(group, str):
            group = (group,)
        found |= {str(t).strip().lower() for t in group or () if str(t).strip()}
    return found


def api_namespace_values(entry, namespaces):
    """A raw gmetadata entry's tags in the given namespaces, in a stored gallery's form."""
    found = set()
    for tag in (entry or {}).get('tags') or ():
        namespace, _, name = str(tag).partition(':')
        if namespace.strip().lower() not in namespaces:
            continue
        name = name.strip().lower().replace('_', ' ')
        if name:
            found.add(name)
    return found


def gallery_languages(values):
    """The languages among a set of tag values, as the source names them."""
    return {v for v in values if v in LANGUAGE_TAGS}


def gallery_parodies(tags):
    """The works a gallery is a parody of, from its stored tags."""
    return gallery_namespace_values(tags, {PARODY_NAMESPACE})


def api_parodies(entry):
    """The works a raw gmetadata entry is a parody of, in the same form as a stored gallery's."""
    return api_namespace_values(entry, {PARODY_NAMESPACE})


def gallery_creators(tags):
    """Who made a gallery, from its stored tags: its circle and its artists together."""
    return gallery_namespace_values(tags, CREATOR_NAMESPACES)


def api_creators(entry):
    """Who made a raw gmetadata entry, in the same form as a stored gallery's."""
    return api_namespace_values(entry, CREATOR_NAMESPACES)


# --- comparing two releases ----------------------------------------------------------------

def same_parody(held_parodies, candidate_parodies):
    """Whether two releases can be the same work, judged on the series the source tags them with.

    The parody is the one thing a short title cannot carry. `canonical_title` strips the group
    naming the series, so a Phantasy Star Online 2 doujin called 'Seishoku' and a Fate/Grand
    Order one of the same name reduce to the same eight characters and score a perfect match.

    Read from the tag rather than the title because the source normalises it: one
    'kantai collection' where titles write both 'Kantai Collection' and 'Kantai Collection
    -KanColle-', which no string comparison of titles separates from a real mismatch. Compared
    by intersection so a crossover tagged with several still matches a release tagged with one.

    Undecidable when either side names none, which is common enough that absence cannot stand in
    for a mismatch: the answer there is yes and the other checks carry it.
    """
    if not held_parodies or not candidate_parodies:
        return True
    return bool(held_parodies & candidate_parodies)


def same_creator(held_creators, candidate_creators):
    """Whether two releases can be the same work, judged on who the source credits them to.

    `canonical_title` strips the '[Circle (Artist)]' group before scoring, so the title carries
    nothing about who drew it and two unrelated doujins of one character score a perfect match:
    'Asuma Toki' held from one artist against 'Asuma Toki' from another. The series tag cannot
    separate those either, since both are the same franchise.

    Read from the tag rather than from that group for the reason `same_parody` gives - the
    source normalises it, where the titles write 'jackdempa' and '[Jaku Denpa]' for one artist.
    Circle and artist are pooled because a release names one, the other or both, and either
    matching is the same answer.

    Undecidable when either side credits nobody, which stays the answer rather than a mismatch:
    the source leaves a release uncredited often enough that absence says nothing.
    """
    if not held_creators or not candidate_creators:
        return True
    return bool(held_creators & candidate_creators)
