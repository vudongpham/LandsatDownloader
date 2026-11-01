import os

import pytest

from lsdownloader.aoi import Aoi

DATA = os.path.join(os.path.dirname(__file__), 'data')


def test_aoi_txt():
    assert Aoi(os.path.join(DATA, 'pathrows.txt')).get_footprints == ['192023', '193023', '193024']


def test_aoi_list():
    a = Aoi('193024,193023,193023')
    assert a.type == 'list'
    assert a.get_footprints == ['193023', '193024']


def test_aoi_vector_berlin():
    # Berlin is covered by WRS-2 path 192/193, rows 023/024
    prs = Aoi(os.path.join(DATA, 'berlin_bbox.gpkg')).get_footprints
    assert set(prs) >= {'193023', '192023'}
    assert all(p[:3] in ('191', '192', '193', '194') and p[3:] in ('023', '024') for p in prs)


def test_aoi_invalid():
    with pytest.raises(SystemExit):
        Aoi('not_a_file_or_tiles')
    with pytest.raises(SystemExit):
        Aoi('19302,193024')
