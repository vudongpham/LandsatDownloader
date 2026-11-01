import pytest

from lsdownloader import eeapi as ee

PID1 = 'LC08_L1TP_192023_20200101_20200113_02_T1'
PID2 = 'LC08_L1TP_193023_20200101_20200113_02_T1'


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.text = ''

    def json(self):
        return self.payload


class FakeSession:
    """Records calls and answers with a scripted handler(request_code, payload) -> response dict."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        code = url.rsplit('/', 1)[-1]
        self.calls.append((code, json, headers))
        return FakeResponse(self.handler(code, json, headers))


def make_api(handler):
    def wrapped(code, payload, headers):
        if code == 'login-token':
            return {'data': 'KEY'}
        return handler(code, payload, headers)
    session = FakeSession(wrapped)
    return ee.eeapi('user', 'token', True, session=session), session


def test_login_error():
    session = FakeSession(lambda c, p, h: {'errorCode': 'AUTH_INVALID', 'errorMessage': 'bad'})
    with pytest.raises(ee.APIError):
        ee.eeapi('user', 'token', True, session=session)


def test_scene_search_pagination_and_filters():
    pages = {1: ([{'entityId': 'a', 'displayId': PID1}], 2), 2: ([{'entityId': 'b', 'displayId': PID2}], 3)}

    def handler(code, payload, headers):
        assert headers['X-Auth-Token'] == 'KEY'
        results, nxt = pages[payload['startingNumber']]
        return {'data': {'results': results, 'nextRecord': nxt, 'totalHits': 2}}

    api, session = make_api(handler)
    res = api.scene_search('2020-01-01', '2020-12-31', dataset_name='landsat_ot_c2_l1',
                           pr_list=['192023', '193023'], seasonal_filter=[6, 7], min_cc=-1, max_cc=70,
                           data_type_l1='L1TP', tier='T1')
    assert [r['entityId'] for r in res] == ['a', 'b']
    payload = session.calls[1][1]
    assert payload['includeUnknownCloudCover'] is True
    assert payload['sceneFilter']['seasonalFilter'] == [6, 7]
    filters = {f['filterId']: f for f in payload['sceneFilter']['metadataFilter']['childFilters']}
    assert filters[ee.FILTER_IDS['path']]['firstValue'] == 192
    assert filters[ee.FILTER_IDS['path']]['secondValue'] == 193
    assert filters[ee.FILTER_IDS['land_cloud_cover']]['secondValue'] == 70
    assert filters[ee.FILTER_IDS['sensor']]['value'] == 'OLI_TIRS'


def test_relogin_on_expired_key():
    state = {'n': 0}

    def handler(code, payload, headers):
        state['n'] += 1
        if state['n'] == 1:
            return {'errorCode': 'AUTH_KEY_EXPIRED', 'errorMessage': 'expired'}
        return {'data': 'ok'}

    api, session = make_api(handler)
    assert api.request('dataset-search') == 'ok'
    assert [c[0] for c in session.calls] == ['login-token', 'dataset-search', 'login-token', 'dataset-search']


def test_rate_limit_waits(monkeypatch):
    monkeypatch.setattr(ee.utils, 'countdown', lambda s: None)
    state = {'n': 0}

    def handler(code, payload, headers):
        state['n'] += 1
        if state['n'] == 1:
            return {'errorCode': 'RATE_LIMIT', 'errorMessage': 'slow down'}
        return {'data': 'ok'}

    api, _ = make_api(handler)
    assert api.request('scene-search') == 'ok'


def test_download_options_and_links():
    def handler(code, payload, headers):
        if code == 'download-options':
            return {'data': [
                {'productName': ee.BUNDLE_PRODUCT_NAME, 'available': True, 'entityId': 'a', 'id': 'p1',
                 'displayId': PID1, 'filesize': 10},
                {'productName': ee.BUNDLE_PRODUCT_NAME, 'available': False, 'entityId': 'b', 'id': 'p2',
                 'displayId': PID2, 'filesize': 10},
                {'productName': 'Other', 'available': True, 'entityId': 'a', 'id': 'p3',
                 'displayId': PID1, 'filesize': 10},
            ]}
        if code == 'download-request':
            assert payload['downloads'][0] == {'entityId': 'a', 'productId': 'p1', 'label': payload['label']}
            return {'data': {
                'availableDownloads': [{'url': f'https://landsatlook.usgs.gov/gen-bundle?landsat_product_id={PID1}'}],
                'preparingDownloads': [{'url': f'https://landsatlook.usgs.gov/gen-bundle?landsat_product_id={PID2}'}],
            }}
        if code == 'download-retrieve':
            return {'data': {'available': [{'url': f'https://dds.cr.usgs.gov/download/x?{PID2}'}], 'requested': []}}
        return {'data': None}

    api, _ = make_api(handler)
    products = api.get_download_options('landsat_ot_c2_l1', ['a', 'b'])
    assert products == [{'entityId': 'a', 'productId': 'p1', 'displayId': PID1, 'filesize': 10}]
    urls = api.get_download_links(products, poll_interval=0)
    # the preparing link is replaced by the retrieved one
    assert urls == [f'https://landsatlook.usgs.gov/gen-bundle?landsat_product_id={PID1}',
                    f'https://dds.cr.usgs.gov/download/x?{PID2}']
