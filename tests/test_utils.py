import os

import pytest

from lsdownloader import utils

PID = 'LC08_L1TP_192023_20200101_20200113_02_T1'


@pytest.mark.parametrize('expected, text', [
    (['app-token', 'user', 'token'], 'app-token\nuser\ntoken'),
    (['app-token', 'user', 'token'], 'app-token\n\tuser\t\ntoken\n\n'),
    (['app-token', 'user', 'token'], '\napp-token\nuser\ntoken  '),
    (['user', 'password'], 'user\npassword'),
    (['user', 'password'], 'user\npassword\n\n'),
    (['user', 'password'], '\nuser\npassword\t\n'),
])
def test_load_secret(tmp_path, expected, text):
    path = tmp_path / 'secret.txt'
    path.write_text(text)
    assert utils.load_secret(str(path)) == expected


@pytest.mark.parametrize('text', ['user', 'app-token\nuser', 'a\nb\nc', 'app-token\na\nb\nc'])
def test_load_secret_invalid(tmp_path, text):
    path = tmp_path / 'secret.txt'
    path.write_text(text)
    with pytest.raises(SystemExit):
        utils.load_secret(str(path))


def test_tile_validity():
    assert utils.check_tile_validity(['192023', '001001', '233248'])
    assert not utils.check_tile_validity(['19223'])
    assert not utils.check_tile_validity(['234023'])
    assert not utils.check_tile_validity(['000023'])
    assert not utils.check_tile_validity(['192249'])
    assert not utils.check_tile_validity([])


def test_product_id_regex():
    for pid in [PID, 'LT05_L1TP_193026_20060706_20200830_02_T1', 'LE07_L1GT_193026_20060706_20200830_02_T2',
                'LC09_L1TP_193022_20250107_20250107_02_RT']:
        assert utils.PRODUCT_ID_REGEX.fullmatch(pid)
    assert not utils.PRODUCT_ID_REGEX.fullmatch('LC08_L1TP_192023_20200101_20200113_02_T3')
    url = f'https://landsatlook.usgs.gov/gen-bundle?landsat_product_id={PID}&id=abc'
    assert utils.product_id_from_url(url) == PID
    assert utils.product_id_from_url('https://dds.cr.usgs.gov/download/abc') is None


def test_find_files(tmp_path):
    complete = 'LC08_L1TP_192023_20200101_20200113_02_T1'
    folder = 'LE07_L1TP_192023_20200101_20200113_02_T1'
    gz = 'LT05_L1TP_192023_20000101_20200113_02_T1'
    partial = 'LC09_L1TP_192023_20220101_20220113_02_T1'
    aria = 'LC08_L1TP_192024_20200101_20200113_02_T1'
    sub = tmp_path / 'sub'
    sub.mkdir()
    (tmp_path / f'{complete}.tar').write_bytes(b'x')
    (sub / folder).mkdir()
    (sub / folder / 'LC08_L1TP_999999_20200101_20200113_02_T1.tar').write_bytes(b'x')  # inside product: ignored
    (sub / f'{gz}.tar.gz').write_bytes(b'x')
    (tmp_path / f'{partial}.tar.part').write_bytes(b'x')
    (tmp_path / f'{aria}.tar').write_bytes(b'x')
    (tmp_path / f'{aria}.tar.aria2').write_bytes(b'x')
    (tmp_path / 'random.tar').write_bytes(b'x')

    assert utils.find_files(str(tmp_path), 'product') == {complete, folder, gz}
    assert utils.find_files(str(tmp_path), 'product', recursive=False) == {complete}
    assert aria in utils.find_files(str(tmp_path), 'product', no_partial_dls=False)


def test_find_logs():
    logs = os.path.join(os.path.dirname(__file__), 'data', 'force_logs')
    found = utils.find_files(logs, 'log')
    assert found == {'LC09_L1TP_193022_20250107_20250107_02_T1', 'LC08_L1TP_192025_20241223_20241228_02_T1'}


def test_filter_results_by_pr():
    scenes = [{'displayId': PID}, {'displayId': 'LC08_L1TP_193023_20200101_20200113_02_T1'}]
    assert utils.filter_results_by_pr(scenes, ['192023']) == [scenes[0]]


def test_bytes_to_humanreadable():
    assert utils.bytes_to_humanreadable(0) == '0.0 B'
    assert utils.bytes_to_humanreadable(1024 ** 3 * 1.5) == '1.5 GB'


def test_check_date_validity():
    utils.check_date_validity(['20200101', '20201231'], 'x')
    for bad in (['20200101'], ['20201301', '20201231'], ['20201231', '20200101']):
        with pytest.raises(SystemExit):
            utils.check_date_validity(bad, 'x')
