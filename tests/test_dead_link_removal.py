"""Tests for the helpers behind the bulk removal of galleries whose source is gone.

The flag a gallery carries is computed once, when the library is read out of the database, so
these cover the case the removal has to survive: a drive that was absent at that moment and
makes every gallery on it read as deleted.
"""

import os
import string

import pytest

import app_constants  # noqa: F401  (must precede gallerydb)
import gallerydb  # noqa: F401
import utils


class FakeGallery:
    """A gallery reduced to the two attributes these helpers touch: a path and a dead_link flag."""

    def __init__(self, path, dead_link=True):
        self.path = path
        self.dead_link = dead_link


def unused_drive():
    "Returns a drive letter with no volume behind it, or skips the test when every letter is taken."
    for letter in reversed(string.ascii_uppercase):
        if not os.path.exists(letter + ':' + os.sep):
            return letter + ':'
    pytest.skip('every drive letter is mounted')


# --- recomputing the flag ---------------------------------------------------------------

def test_a_gallery_whose_source_came_back_is_no_longer_dead(tmp_path):
    gallery = FakeGallery(str(tmp_path))
    assert utils.refresh_dead_links([gallery]) == []
    assert not gallery.dead_link


def test_a_gallery_whose_source_is_still_gone_stays_dead(tmp_path):
    gallery = FakeGallery(str(tmp_path / 'gone'))
    assert utils.refresh_dead_links([gallery]) == [gallery]
    assert gallery.dead_link


def test_a_source_deleted_after_the_library_loaded_is_found(tmp_path):
    """Nothing sets the flag while the app runs, so an unflagged gallery still has to be stated."""
    gallery = FakeGallery(str(tmp_path / 'gone'), dead_link=False)
    assert utils.refresh_dead_links([gallery]) == [gallery]
    assert gallery.dead_link


# --- the volume guard -------------------------------------------------------------------

def test_a_missing_drive_is_reported_as_unreachable():
    drive = unused_drive()
    galleries = [FakeGallery(os.path.join(drive + os.sep, 'Manga', str(n))) for n in range(3)]
    assert utils.unreachable_roots(galleries) == [drive]


def test_a_mounted_drive_is_not_reported(tmp_path):
    assert utils.unreachable_roots([FakeGallery(str(tmp_path))]) == []


def test_each_missing_drive_is_reported_once():
    drive = unused_drive()
    galleries = [FakeGallery(drive + os.sep + name) for name in ('a', 'b')]
    galleries.append(FakeGallery(drive.lower() + os.sep + 'c'))
    assert utils.unreachable_roots(galleries) == [drive]


def test_a_relative_path_states_no_drive():
    """A path with no drive says nothing about a volume, so it must not be reported as one."""
    assert utils.unreachable_roots([FakeGallery(os.path.join('Manga', 'gone'))]) == []
