"""Regression cases for cover thumbnails.

Every one of these comes from a gallery in a real library that showed "Loading..." or
"Thumbnail regeneration needed!" forever. A cover that cannot be made is not the problem; a
cover that fails without saying so, and leaves the gallery waiting on a result that never
arrives, is.
"""
import os

import pytest
from PIL import Image

import app_constants
import executors
import utils

utils.init_utils()


@pytest.fixture
def image_folder(tmp_path):
    "A folder holding one real image, named however the test wants."
    def make(name):
        folder = tmp_path / name
        folder.mkdir()
        Image.new('RGB', (60, 90), 'red').save(str(folder / 'img001.png'))
        return str(folder)
    return make


# --- a folder that is named like an archive ---------------------------------------------------

@pytest.mark.parametrize('name', ['extracted.zip', 'extracted.cbz', 'extracted.7z'])
def test_a_folder_named_like_an_archive_is_read_as_a_folder(image_folder, name):
    """Extracting a .zip in place keeps the name, so a library holds folders called "....zip".

    Choosing the archive reader by the name hands it a directory, which fails as a permission
    error, and the gallery gets the placeholder cover instead of its own first page.
    """
    folder = image_folder(name)

    found = utils.get_gallery_img(folder)

    assert found == os.path.join(folder, 'img001.png')


def test_a_real_archive_is_still_read_as_an_archive(tmp_path, monkeypatch):
    """The name is still what marks an archive; only a directory overrules it."""
    import zipfile
    # The page is extracted to app_constants.temp_dir, which is relative to the working
    # directory and would otherwise be written inside the repository.
    monkeypatch.setattr(app_constants, 'temp_dir', str(tmp_path / 'temp'))
    os.mkdir(app_constants.temp_dir)
    png = tmp_path / 'img001.png'
    Image.new('RGB', (60, 90), 'blue').save(str(png))
    archive = tmp_path / 'real.zip'
    with zipfile.ZipFile(str(archive), 'w') as zf:
        zf.write(str(png), 'img001.png')

    found = utils.get_gallery_img(str(archive))

    assert found and found.lower().endswith('img001.png')
    assert os.path.dirname(found) != str(tmp_path), 'it should come out of the archive'


# --- a cover the decoder refuses ---------------------------------------------------------------

def test_an_unreadable_cover_yields_the_placeholder_rather_than_raising(image_folder, monkeypatch):
    """An exception here stays in the worker's future, where nothing ever looks at it.

    The gallery is left waiting on a result that never comes, which is the "Loading..." that
    never finishes. Pillow raising on an oversized image is the case that found this.
    """
    folder = image_folder('a gallery')

    def refuse(path):
        raise Image.DecompressionBombError('too many pixels')

    monkeypatch.setattr(utils, 'PToQImageHelper', refuse)

    assert executors._task_thumbnail(folder) == app_constants.NO_IMAGE_PATH


def test_the_decompression_bomb_ceiling_clears_a_large_scan():
    """Pillow refuses above twice this, and real pages run past the stock ceiling honestly.

    A stitched cosplay set of 273 megapixels is what this was raised for.
    """
    assert Image.MAX_IMAGE_PIXELS >= 300_000_000


# --- the page a folder's cover comes from ------------------------------------------------------

def test_names_sort_the_way_the_file_manager_orders_them():
    """Digit runs read as numbers, zero padding included, and case ignored."""
    names = ['10 CG', '2 effects', '01 main', '1 main', 'img10.png', 'img2.png', 'B.png', 'a.png']

    assert sorted(names, key=utils.natural_sort_key) == [
        '01 main', '1 main', '2 effects', '10 CG', 'a.png', 'B.png', 'img2.png', 'img10.png']


def test_the_cover_is_the_first_page_not_the_first_name(tmp_path):
    """Plain text ordering puts page 10 before page 2, and that page became the cover."""
    for page in (1, 2, 10):
        Image.new('RGB', (10, 10), 'red').save(str(tmp_path / f'{page}.png'))

    assert utils.first_image_in(str(tmp_path)) == str(tmp_path / '1.png')


def test_a_gallery_that_keeps_its_pages_in_subfolders_still_gets_a_cover(tmp_path):
    """Real shape: '01 main', '02 effects', '03 CG', 'omake', and nothing at the top level."""
    for folder, page in (('10 CG', 'c.png'), ('2 effects', 'b.png'), ('01 main', 'a.png')):
        (tmp_path / folder).mkdir()
        Image.new('RGB', (10, 10), 'red').save(str(tmp_path / folder / page))

    assert utils.first_image_in(str(tmp_path)) == str(tmp_path / '01 main' / 'a.png')


def test_a_page_of_its_own_beats_one_in_a_subfolder(tmp_path):
    """Descending is the fallback, not the rule: a gallery with pages uses its own."""
    (tmp_path / '01 main').mkdir()
    Image.new('RGB', (10, 10), 'red').save(str(tmp_path / '01 main' / 'a.png'))
    Image.new('RGB', (10, 10), 'blue').save(str(tmp_path / 'zzz.png'))

    assert utils.first_image_in(str(tmp_path)) == str(tmp_path / 'zzz.png')


def test_a_folder_holding_no_images_at_all_yields_nothing(tmp_path):
    (tmp_path / 'empty').mkdir()

    assert utils.first_image_in(str(tmp_path)) == ''
