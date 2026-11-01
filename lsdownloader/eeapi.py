"""Minimal client for the USGS/EROS machine-to-machine (M2M) API.
API reference: https://m2m.cr.usgs.gov/api/docs/reference/"""
import time
import uuid
from typing import Iterable, List, Optional

import requests

from lsdownloader import utils
from lsdownloader._http import make_session

ENDPOINT = 'https://m2m.cr.usgs.gov/api/api/json/stable/'

DATASETS = {'TM': 'landsat_tm_c2_l1', 'ETM': 'landsat_etm_c2_l1', 'OLI': 'landsat_ot_c2_l1'}
BUNDLE_PRODUCT_NAME = 'Landsat Collection 2 Level-1 Product Bundle'

# metadata filter IDs of the Landsat Collection 2 Level-1 datasets
FILTER_IDS = {
    'data_type_l1': '5e81f14fcf660794',
    'tier': '5e81f14fff5055a3',
    'day_night': '5e81f14f61bda7c4',
    'land_cloud_cover': '5f6aa1a4e0985d4c',
    'path': '5e81f14f8faf8048',
    'row': '5e81f14f8d2a7c24',
    'sensor': '5e81f14f85d499dc',
    'nadir': '5e81f150e42bc489',
}

RATE_LIMIT_ERRORS = {'RATE_LIMIT', 'RATE_LIMIT_USER_DL'}
AUTH_ERRORS = {'AUTH_KEY_EXPIRED', 'AUTH_UNAUTHORIZED', 'AUTH_KEY_INVALID'}
RATE_LIMIT_SLEEP = 905  # seconds: the API limits requests per 15 minutes

SEARCH_PAGE_SIZE = 10000
DOWNLOAD_OPTIONS_CHUNK = 5000
DOWNLOAD_REQUEST_CHUNK = 1000


class APIError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message


class eeapi(object):

    def __init__(self, user: str, password: str, use_login_token: bool = True,
                 session: Optional[requests.Session] = None, endpoint: str = ENDPOINT):
        self.endpoint = endpoint
        # POST is safe to retry here: all calls we make are idempotent searches/requests
        self.session = session or make_session(allowed_methods=('GET', 'HEAD', 'POST'))
        self._credentials = (user, password, use_login_token)
        self.key = self.login(user, password, use_login_token)

    # ------------------------------------------------------------------------------------------------------------------
    # low level
    def _post(self, request_code: str, payload: dict, auth: bool = True) -> dict:
        headers = {'X-Auth-Token': self.key} if auth else {}
        try:
            r = self.session.post(f'{self.endpoint}{request_code}', json=payload, headers=headers, timeout=(30, 600))
        except requests.RequestException as e:
            raise APIError('CONNECTION_ERROR', str(e)) from e
        try:
            response = r.json()
        except ValueError:
            raise APIError(f'HTTP_{r.status_code}', r.text[:500] or 'Invalid response from M2M API')
        if not isinstance(response, dict):
            raise APIError('INVALID_RESPONSE', str(response)[:500])
        return response

    def login(self, user: str, password: str, use_login_token: bool = True) -> str:
        if use_login_token:
            login_endpoint = 'login-token'
            payload = {'username': user, 'token': password}
        else:
            login_endpoint = 'login'
            payload = {'username': user, 'password': password}
            print('Warning: the user/password login endpoint has been deprecated by the USGS M2M API '
                  '(February 2025).\nPlease create an application token, info here: '
                  'https://www.usgs.gov/media/files/m2m-application-token-documentation')

        response = self._post(login_endpoint, payload, auth=False)
        if response.get('errorCode') or not response.get('data'):
            raise APIError(
                response.get('errorCode') or 'LOGIN_FAILED',
                f'{response.get("errorMessage")}\n'
                'Please check your login data.\n'
                'Login will fail if you did not request access to the M2M API yet.\n'
                'Request access through your user profile at https://ers.cr.usgs.gov/'
            )
        return response['data']

    def logout(self) -> None:
        try:
            self.request('logout')
        except APIError:
            pass

    def request(self, request_code: str, _max_rate_limit_waits: int = 3, **kwargs):
        """
        Send a request to the machine2machine API.
        Waits and retries on rate limiting, logs in again if the API key expired.
        :param request_code: API method, list of codes: https://m2m.cr.usgs.gov/api/docs/reference/
        :param kwargs: parameterization of the API request.
        :return: the 'data' field of the API response
        """
        relogged = False
        waits = 0
        while True:
            response = self._post(request_code, kwargs)
            code = response.get('errorCode')
            if not code:
                return response.get('data')
            if code in RATE_LIMIT_ERRORS and waits < _max_rate_limit_waits:
                waits += 1
                print(f'Rate limit exceeded ({code}). Will sleep for 15 minutes.')
                utils.countdown(RATE_LIMIT_SLEEP)
                continue
            if code in AUTH_ERRORS and not relogged and request_code != 'logout':
                relogged = True
                self.key = self.login(*self._credentials)
                continue
            raise APIError(code, response.get('errorMessage') or '')

    # ------------------------------------------------------------------------------------------------------------------
    # search
    def scene_search(self,
                     start: str, end: str,
                     dataset_name: str = None, entity_id=None,
                     seasonal_filter: list = None, pr_list: list = None,
                     ingest_filter: list = None,
                     max_results: int = None, **kwargs) -> List[dict]:
        """
        Search for scenes matching search criteria. Results are paginated transparently.
        :param start: Temporal filter: start date (YYYY-MM-DD)
        :param end: Temporal filter: end date (YYYY-MM-DD)
        :param dataset_name: Name of the dataset to be queried (e.g. 'landsat_ot_c2_l1')
        :param entity_id: Entity ID to directly search for scenes
        :param seasonal_filter: Temporal filter: months to be included (list of int)
        :param pr_list: Filter by path/row (list of 'PPPRRR' str)
        :param ingest_filter: [start, end] of the ingestion into the archive (YYYY-MM-DD)
        :param max_results: maximum number of results returned (default: all)
        :param kwargs: additional filters for the metadataFilter childFilters
        :return: List containing one dict per scene
        """
        if dataset_name not in DATASETS.values():
            raise ValueError(f"Invalid dataset {dataset_name!r}. Use one of {', '.join(DATASETS.values())}")
        if dataset_name == DATASETS['OLI']:
            kwargs.setdefault('sensor', 'OLI_TIRS')
            kwargs.setdefault('nadir', 'NADIR')

        if pr_list:
            paths = [int(pr[0:3]) for pr in pr_list]
            rows = [int(pr[3:6]) for pr in pr_list]
            kwargs.update(path_min=min(paths), path_max=max(paths), row_min=min(rows), row_max=max(rows))

        min_cc = kwargs.get('min_cc')
        include_unknown_cc = min_cc is not None and float(min_cc) < 0

        scene_filter = {
            'acquisitionFilter': {'start': start, 'end': end},
            'metadataFilter': {'filterType': 'and', 'childFilters': self.create_child_filters(**kwargs)},
        }
        if seasonal_filter and len(set(seasonal_filter)) < 12:
            scene_filter['seasonalFilter'] = sorted(set(int(m) for m in seasonal_filter))
        if ingest_filter:
            scene_filter['ingestFilter'] = {'start': ingest_filter[0], 'end': ingest_filter[1]}

        results = []
        starting_number = 1
        while True:
            page_size = SEARCH_PAGE_SIZE if max_results is None else min(SEARCH_PAGE_SIZE, max_results - len(results))
            params = {
                'datasetName': dataset_name,
                'includeUnknownCloudCover': include_unknown_cc,
                'maxResults': page_size,
                'startingNumber': starting_number,
                'sceneFilter': scene_filter,
            }
            if entity_id:
                params['entityId'] = entity_id
            data = self.request('scene-search', **params) or {}
            page = data.get('results') or []
            results.extend(page)
            next_record = data.get('nextRecord')
            total = data.get('totalHits') or 0
            if (not page or not next_record or next_record <= starting_number or len(results) >= total
                    or (max_results is not None and len(results) >= max_results)):
                break
            starting_number = next_record
        return results

    def get_download_options(self, dataset_name: str, scene_ids: List[str]) -> List[dict]:
        """
        Retrieve download options, keep the available Collection 2 Level-1 product bundles
        :return: List of dicts with entity id, product id, display id, and filesize for each product bundle
        """
        dl_options = []
        for i in range(0, len(scene_ids), DOWNLOAD_OPTIONS_CHUNK):
            chunk = scene_ids[i:i + DOWNLOAD_OPTIONS_CHUNK]
            dl_options.extend(self.request('download-options', datasetName=dataset_name, entityIds=chunk) or [])

        products, seen = [], set()
        for product in dl_options:
            if product.get('productName') != BUNDLE_PRODUCT_NAME or product.get('available') is not True:
                continue
            if product['entityId'] in seen:
                continue
            seen.add(product['entityId'])
            products.append({
                'entityId': product['entityId'],
                'productId': product['id'],
                'displayId': product['displayId'],
                'filesize': product.get('filesize') or 0,
            })
        return products

    def retrieve_search_results(
            self, datasetName, data_type_l1, tier,
            start, end, seasonalFilter, ingestFilter,
            minCC, maxCC,
            prList
    ) -> List[dict]:
        """
        Combine scene_search and get_download_options, filter the results by allowed path/row
        :return: List of dicts containing scene IDs, legacy IDs, and filesize for each scene
        """
        scenes = self.scene_search(
            dataset_name=datasetName,
            pr_list=prList,
            start=start, end=end, seasonal_filter=seasonalFilter,
            ingest_filter=ingestFilter,
            min_cc=minCC, max_cc=maxCC,
            data_type_l1=data_type_l1, tier=tier
        )
        scenes = utils.filter_results_by_pr(scenes, prList)
        if len(scenes) >= 15000:
            print(f'Warning: The M2M API only allows requesting 15000 scenes/15 min. '
                  f'{utils.PROG_NAME} will pause for 15 mins if rate limiting occurs.')
        entity_ids = [s.get('entityId') for s in scenes if s.get('entityId')]
        if not entity_ids:
            return []
        return self.get_download_options(dataset_name=datasetName, scene_ids=entity_ids)

    # ------------------------------------------------------------------------------------------------------------------
    # download links
    def get_download_links(self, dl_product_ids: List[dict], label: Optional[str] = None,
                           wait_preparing: int = 600, poll_interval: int = 30) -> List[str]:
        """
        Retrieve download links for product bundles.
        Requests are split into chunks of 1000 as large numbers have been leading to issues.
        Downloads that are still being prepared by USGS are polled for up to `wait_preparing` seconds.
        :param dl_product_ids: dicts with 'entityId' and 'productId' from get_download_options
        :return: List of download urls (unique, in request order)
        """
        label = label or f'{utils.PROG_NAME}-{uuid.uuid4().hex[:12]}'
        urls: List[str] = []
        preparing_urls: List[str] = []
        n_preparing = 0
        for i in range(0, len(dl_product_ids), DOWNLOAD_REQUEST_CHUNK):
            chunk = dl_product_ids[i:i + DOWNLOAD_REQUEST_CHUNK]
            downloads = [{'entityId': p['entityId'], 'productId': p['productId'], 'label': label} for p in chunk]
            response = self.request('download-request', downloads=downloads, label=label) or {}
            urls.extend(d['url'] for d in response.get('availableDownloads') or [] if d.get('url'))
            preparing = response.get('preparingDownloads') or []
            n_preparing += len(preparing)
            preparing_urls.extend(d['url'] for d in preparing if d.get('url'))
            for failed in response.get('failed') or []:
                print(f'Warning: download request failed: {failed}')

        if n_preparing and wait_preparing > 0:
            urls.extend(self._retrieve_prepared(label, n_preparing, wait_preparing, poll_interval))

        # keep the (possibly not yet ready) links of downloads that are still being prepared,
        # as landsatlinks did, unless a ready link for the same product was retrieved
        have = {utils.product_id_from_url(u) for u in urls} - {None}
        urls.extend(u for u in preparing_urls if utils.product_id_from_url(u) not in have)

        return list(dict.fromkeys(urls))

    def _retrieve_prepared(self, label: str, n_preparing: int, timeout: int, poll_interval: int) -> List[str]:
        print(f'{n_preparing} product bundle(s) are being prepared by USGS, waiting for download links.')
        deadline = time.monotonic() + timeout
        urls: List[str] = []
        while True:
            data = self.request('download-retrieve', label=label) or {}
            urls = [d['url'] for d in data.get('available') or [] if d.get('url')]
            still_requested = len(data.get('requested') or [])
            if not still_requested or time.monotonic() >= deadline:
                if still_requested:
                    print(f'Warning: {still_requested} download(s) still being prepared, '
                          'their links may not work yet.')
                return urls
            time.sleep(poll_interval)

    # ------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def create_meta_dict(filter_id: str, filter_type: str, **kwargs) -> dict:
        meta_dict = {'filterId': filter_id, 'filterType': filter_type}
        meta_dict.update(kwargs)
        return meta_dict

    def create_child_filters(self, **kwargs) -> list:
        data_type_l1 = kwargs.get('data_type_l1', 'L1TP')
        tier = kwargs.get('tier', 'T1')
        day_night = kwargs.get('day_night', 'DAY')

        filters = []
        if data_type_l1:
            filters.append(self.create_meta_dict(FILTER_IDS['data_type_l1'], 'value', value=data_type_l1))
        if tier:
            filters.append(self.create_meta_dict(FILTER_IDS['tier'], 'value', value=tier))
        if day_night:
            filters.append(self.create_meta_dict(FILTER_IDS['day_night'], 'value', value=day_night))
        if kwargs.get('min_cc') is not None or kwargs.get('max_cc') is not None:
            min_cc = kwargs.get('min_cc')
            max_cc = kwargs.get('max_cc')
            filters.append(self.create_meta_dict(
                FILTER_IDS['land_cloud_cover'], 'between',
                firstValue=float(min_cc) if min_cc is not None else 0,
                secondValue=float(max_cc) if max_cc is not None else 100,
            ))
        if 'path_min' in kwargs and 'path_max' in kwargs:
            filters.append(self.create_meta_dict(FILTER_IDS['path'], 'between',
                                                 firstValue=kwargs['path_min'], secondValue=kwargs['path_max']))
        if 'row_min' in kwargs and 'row_max' in kwargs:
            filters.append(self.create_meta_dict(FILTER_IDS['row'], 'between',
                                                 firstValue=kwargs['row_min'], secondValue=kwargs['row_max']))
        if kwargs.get('sensor'):
            filters.append(self.create_meta_dict(FILTER_IDS['sensor'], 'value', value=kwargs['sensor']))
        if kwargs.get('nadir'):
            filters.append(self.create_meta_dict(FILTER_IDS['nadir'], 'value', value='NADIR'))
        return filters


def dataset_names(sensors: Iterable[str]) -> List[str]:
    return [DATASETS[s] for s in sensors]
