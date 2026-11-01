"""Parallel, resumable download of Landsat product bundles (pure Python, no aria2 needed)."""
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlparse

import requests

from lsdownloader import utils
from lsdownloader._http import make_session

KNOWN_LINK_REGEX = re.compile(
    r'^https://(landsatlook\.usgs\.gov/gen-bundle\?landsat_product_id=|dds\.cr\.usgs\.gov/download/)')
CHUNK_SIZE = 1024 * 1024
PART_SUFFIX = '.part'
FATAL_HTTP_CODES = {400, 401, 403, 404, 410}

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - tqdm is a dependency, but keep working without it
    tqdm = None


class DownloadError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class DownloadCancelled(Exception):
    pass


# ----------------------------------------------------------------------------------------------------------------------
# url files
def load_links(filepath: str) -> List[str]:
    utils.validate_file_paths(filepath, 'url', file=True, write=False)
    with open(filepath, 'r') as f:
        links = [line.strip() for line in f if line.strip() and not line.lstrip().startswith('#')]
    if not links:
        print(f'File seems to be empty {filepath}')
    return list(dict.fromkeys(links))


def check_for_broken_links(links: List[str]) -> bool:
    broken = [link for link in links if not re.match(r'^https?://\S+$', link)]
    if broken:
        print('Some links seem to be broken, please check:')
        print(*broken, sep='\n')
        utils.die('Exiting.')
    unknown = [link for link in links if not KNOWN_LINK_REGEX.match(link)]
    if unknown:
        print(f'Warning: {len(unknown)} link(s) do not look like USGS product bundle links, trying anyway.')
    return True


def check_for_downloaded_scenes(links: List[str], dest_folder: str, no_partial_dls: bool = True) -> List[str]:
    """Remove all urls of product bundles that are already present in dest_folder (searched recursively)."""
    in_filesystem = utils.find_files(dest_folder, 'product', recursive=True, no_partial_dls=no_partial_dls)
    return [url for url in links if utils.product_id_from_url(url) not in in_filesystem]


def write_links(urls: List[str], filepath: str) -> None:
    with open(filepath, 'w') as f:
        f.write('\n'.join(urls))
        f.write('\n')


def append_to_force_queue(scene_path: str, queue_fp: str) -> None:
    with open(queue_fp, 'a') as f:
        f.write(f'{os.path.realpath(scene_path)} QUEUED\n')


# ----------------------------------------------------------------------------------------------------------------------
# single file
def _filename_from_response(response: requests.Response, url: str) -> Optional[str]:
    cd = response.headers.get('Content-Disposition', '')
    m = re.search(r"filename\*=(?:UTF-8'')?\"?([^\";]+)\"?", cd, re.I) or \
        re.search(r'filename="?([^";]+)"?', cd, re.I)
    if m:
        name = os.path.basename(unquote(m.group(1).strip()))
        if name:
            return name
    product_id = utils.product_id_from_url(response.url) or utils.product_id_from_url(url)
    if product_id:
        return f'{product_id}.tar'
    return os.path.basename(urlparse(response.url).path) or None


def _total_size(response: requests.Response, offset: int) -> Optional[int]:
    if response.status_code == 206:
        m = re.search(r'/(\d+)\s*$', response.headers.get('Content-Range', ''))
        if m:
            return int(m.group(1))
    length = response.headers.get('Content-Length')
    if length and length.isdigit():
        return int(length) + (offset if response.status_code == 206 else 0)
    return None


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _clean_aria2_leftovers(final_path: str) -> None:
    """aria2 (used by landsatlinks) pre-allocates files, an unfinished one cannot be resumed here."""
    if os.path.exists(f'{final_path}.aria2'):
        _remove(final_path)
        _remove(f'{final_path}.aria2')


def download_file(session: requests.Session, url: str, output_dir: str,
                  stop_event: Optional[threading.Event] = None) -> Tuple[str, int]:
    """
    Download one url into output_dir. Data is written to '<name>.part' and renamed when complete,
    an existing '.part' file is resumed if the server supports HTTP range requests.
    :return: (path of the downloaded file, number of bytes transferred)
    """
    product_id = utils.product_id_from_url(url)
    guess = f'{product_id}.tar' if product_id else None
    part_path, offset, headers = None, 0, {}
    if guess:
        _clean_aria2_leftovers(os.path.join(output_dir, guess))
        part_path = os.path.join(output_dir, guess + PART_SUFFIX)
        if os.path.exists(part_path):
            offset = os.path.getsize(part_path)
            if offset:
                headers['Range'] = f'bytes={offset}-'

    try:
        response = session.get(url, stream=True, headers=headers, timeout=(60, 300))
    except requests.RequestException as e:
        raise DownloadError(f'connection error: {e}')

    with response:
        if response.status_code == 416 and part_path:
            _remove(part_path)  # stale partial file, start over on the next attempt
            raise DownloadError('invalid partial download, restarting')
        if response.status_code >= 400:
            raise DownloadError(f'HTTP {response.status_code} {response.reason}',
                                retryable=response.status_code not in FATAL_HTTP_CODES)
        if 'text/html' in response.headers.get('Content-Type', ''):
            raise DownloadError('server returned a web page instead of a product bundle (link expired?)',
                                retryable=False)

        name = _filename_from_response(response, url) or guess
        if not name:
            raise DownloadError('could not determine the file name', retryable=False)
        final_path = os.path.join(output_dir, name)
        if part_path is None:
            _clean_aria2_leftovers(final_path)
            part_path = final_path + PART_SUFFIX
            if os.path.exists(final_path):
                return final_path, 0

        if response.status_code == 206:
            mode = 'ab'
        else:
            mode, offset = 'wb', 0
        total = _total_size(response, offset)

        transferred = 0
        try:
            with open(part_path, mode) as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if stop_event is not None and stop_event.is_set():
                        raise DownloadCancelled()
                    if chunk:
                        f.write(chunk)
                        transferred += len(chunk)
        except (requests.RequestException, OSError) as e:
            raise DownloadError(f'transfer interrupted: {e}')

    size = os.path.getsize(part_path)
    if total is not None and size != total:
        if size > total:
            _remove(part_path)
        raise DownloadError(f'incomplete download ({utils.bytes_to_humanreadable(size)} of '
                            f'{utils.bytes_to_humanreadable(total)})')
    os.replace(part_path, final_path)
    return final_path, transferred


def download_with_retries(session, url: str, output_dir: str, retries: int = 3,
                          stop_event: Optional[threading.Event] = None, backoff: float = 30) -> Tuple[str, int]:
    last_error = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return download_file(session, url, output_dir, stop_event)
        except DownloadError as e:
            last_error = e
            if not e.retryable or attempt >= retries:
                break
            wait = backoff * 2 ** (attempt - 1)
            if stop_event is not None:
                if stop_event.wait(wait):
                    raise DownloadCancelled()
            else:
                time.sleep(wait)
    raise last_error


# ----------------------------------------------------------------------------------------------------------------------
# many files
def download(urls: List[str], output_dir: str, n_tasks: int = 4, force_queue_fp: str = None,
             retries: int = 3, session: Optional[requests.Session] = None) -> Tuple[List[str], List[str]]:
    """
    Download all urls with n_tasks parallel workers.
    Successfully downloaded product bundles are appended to the FORCE queue file (if given) as soon as they finish.
    :return: (list of downloaded file paths, list of urls that failed)
    """
    os.makedirs(output_dir, exist_ok=True)
    n_tasks = max(1, n_tasks)
    session = session or make_session(pool_size=max(10, n_tasks))
    stop_event = threading.Event()
    done, failed = [], []
    t0 = time.monotonic()
    n_bytes = 0

    bar = tqdm(total=len(urls), desc='Downloading', unit='product bundle', ascii=' >=') if tqdm else None
    write = bar.write if bar else print

    executor = ThreadPoolExecutor(max_workers=n_tasks)
    futures = {}
    try:
        futures = {executor.submit(download_with_retries, session, url, output_dir, retries, stop_event): url
                   for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                path, transferred = future.result()
            except DownloadCancelled:
                continue
            except Exception as e:  # noqa: BLE001 - report and carry on with the other downloads
                failed.append(url)
                write(f'Failed: {utils.product_id_from_url(url) or url}: {e}')
            else:
                n_bytes += transferred
                done.append(path)
                if force_queue_fp:
                    append_to_force_queue(path, force_queue_fp)
            if bar:
                bar.update()
    except KeyboardInterrupt:
        stop_event.set()
        for f in futures:
            f.cancel()
        raise
    finally:
        executor.shutdown(wait=True)
        if bar:
            bar.close()

    elapsed = max(time.monotonic() - t0, 1e-6)
    print(f'{len(done)} product bundle(s) downloaded, {len(failed)} failed. '
          f'{utils.bytes_to_humanreadable(n_bytes)} in {elapsed / 60:.1f} min '
          f'({utils.bytes_to_humanreadable(n_bytes / elapsed)}/s)')
    return done, failed


def download_standalone(links_fp: str, output_dir: str, n_tasks: int = 4, queue_fp: str = None,
                        retries: int = 3) -> int:
    """Download urls from a text file. Returns the process exit code."""
    print(f'\nLoading urls from {links_fp}\n')
    urls = load_links(links_fp)
    if not urls:
        return 1
    check_for_broken_links(urls)
    urls_to_download = check_for_downloaded_scenes(urls, output_dir)

    n_left = len(urls_to_download)
    if not n_left:
        print(f'All products already present in filesystem.\n{output_dir}\nExiting.')
        return 0
    if n_left == len(urls):
        print(f'Found {len(urls)} product bundle URLs.')
    else:
        print(f'{len(urls) - n_left} of {len(urls)} product bundles found in filesystem, '
              f'{n_left} left to download.\n')

    _, failed = download(urls_to_download, output_dir, n_tasks, queue_fp, retries)
    if failed:
        print(f'{len(failed)} download(s) failed. Re-run the same command to retry, '
              'finished product bundles are skipped.')
        return 1
    print('Download complete')
    return 0
