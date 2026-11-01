import pytest

from lsdownloader import cli
from lsdownloader.parseargs import parse_cli_arguments

PID = 'LC08_L1TP_193023_20200101_20200113_02_T1'
PID_HAVE = 'LC08_L1TP_193024_20200101_20200113_02_T1'


def test_parse_defaults():
    a = parse_cli_arguments(['search', '193023', 'out'])
    assert (a.sensor, a.cloudcover, a.tier, a.level, a.workers) == ('TM,ETM,OLI', '-1,100', 'T1', 'L1TP', 4)
    a = parse_cli_arguments(['download', 'urls.txt', 'out', '-q', 'queue.txt'])
    assert (a.url_file, a.output_dir, a.queue_file) == ('urls.txt', 'out', 'queue.txt')
    with pytest.raises(SystemExit):
        parse_cli_arguments(['search', 'a', 'b', '--download', '-n'])


def test_no_command():
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 1


class FakeApi:
    instances = []

    def __init__(self, user, passwd, token):
        self.args = (user, passwd, token)
        self.searches = []
        self.logged_out = False
        FakeApi.instances.append(self)

    def retrieve_search_results(self, **kw):
        self.searches.append(kw)
        if kw['datasetName'] != 'landsat_ot_c2_l1':
            return []
        return [{'entityId': 'a', 'productId': 'p', 'displayId': PID, 'filesize': 100},
                {'entityId': 'b', 'productId': 'q', 'displayId': PID_HAVE, 'filesize': 100}]

    def get_download_links(self, dl_product_ids):
        return [f'https://landsatlook.usgs.gov/gen-bundle?landsat_product_id={p["displayId"]}'
                for p in dl_product_ids]

    def logout(self):
        self.logged_out = True


def test_search_writes_links(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'eeapi', FakeApi)
    secret = tmp_path / 'secret.txt'
    secret.write_text('app-token\nme\ntok\n')
    (tmp_path / f'{PID_HAVE}.tar').write_bytes(b'x')
    out_file = tmp_path / 'urls.txt'

    with pytest.raises(SystemExit) as e:
        cli.main(['search', '193023,193024', str(tmp_path), '-s', 'oli,TM', '-d', '20200101,20201231',
                  '-c', '0,70', '-m', '6,7', '--secret', str(secret), '-o', str(out_file)])
    assert e.value.code == 0
    api = FakeApi.instances[-1]
    assert api.args == ('me', 'tok', True) and api.logged_out
    assert [s['datasetName'] for s in api.searches] == ['landsat_ot_c2_l1', 'landsat_tm_c2_l1']
    assert api.searches[0]['prList'] == ['193023', '193024']
    assert api.searches[0]['seasonalFilter'] == [6, 7]
    assert out_file.read_text().split() == [f'https://landsatlook.usgs.gov/gen-bundle?landsat_product_id={PID}']


def test_credentials_from_env(monkeypatch):
    monkeypatch.setenv('M2M_USERNAME', 'u')
    monkeypatch.setenv('M2M_TOKEN', 't')
    assert cli.get_credentials(None) == ('u', 't', True)


@pytest.mark.parametrize('args', [
    ['-s', 'MSS'], ['-c', '0,101'], ['-m', '13'], ['-d', '20201301,20201231'], ['-l', 'L1GT'],
])
def test_search_invalid_args(tmp_path, monkeypatch, args):
    monkeypatch.setattr(cli, 'eeapi', FakeApi)
    with pytest.raises(SystemExit) as e:
        cli.main(['search', '193023', str(tmp_path)] + args)
    assert e.value.code != 0
