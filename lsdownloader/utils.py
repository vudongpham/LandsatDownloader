"""Generic helpers: validation, file system scanning, credentials, formatting."""
import os
import re
import sys
import time
from datetime import datetime
from math import floor, log
from typing import Iterable, List, Optional, Set

PROG_NAME = 'lsdownloader'

# Landsat Collection 1/2 Level-1 product identifier, e.g. LC08_L1TP_192023_20200101_20200113_02_T1
PRODUCT_ID_PATTERN = r'L[CEMOT]0[1-9]_L1(?:TP|GT|GS)_\d{6}_\d{8}_\d{8}_0[12]_(?:T1|T2|RT)'
PRODUCT_ID_REGEX = re.compile(PRODUCT_ID_PATTERN)

# Complete product bundles: folder, .tar, .tar.gz or .tgz
_PRODUCT_FILE_REGEX = re.compile(rf'^({PRODUCT_ID_PATTERN})(\.tar(\.gz)?|\.tgz)?$')
# Unfinished downloads: our own .part files and aria2 control files (landsatlinks compatibility)
_PARTIAL_FILE_REGEX = re.compile(rf'^({PRODUCT_ID_PATTERN})(\.tar(\.gz)?|\.tgz)?\.(part|aria2)$')
# FORCE Level-2 processing logs
_LOG_FILE_REGEX = re.compile(rf'^({PRODUCT_ID_PATTERN})(\.tar)?\.log$')

TILE_REGEX = re.compile(r'^\d{6}$')
SECRET_HELP = (
    "a) 1st line: 'app-token', 2nd line: user, 3rd line: token (recommended)\n"
    "b) 1st line: user, 2nd line: password - deprecated by the USGS M2M API since February 2025"
)


def die(message: str, code: int = 1):
    """Print an error message to stderr and exit."""
    print(message, file=sys.stderr)
    sys.exit(code)


def countdown(seconds: int):
    """Sleep for `seconds`, showing a mm:ss countdown when attached to a terminal."""
    interactive = sys.stdout.isatty()
    while seconds > 0:
        if interactive:
            mins, secs = divmod(seconds, 60)
            print(f'{mins:02d}:{secs:02d}', end='\r', flush=True)
        time.sleep(1)
        seconds -= 1
    print('...resuming')


def find_files(search_path: str, search_type: str,
               recursive: bool = True, no_partial_dls: bool = True) -> Set[str]:
    """
    Return the set of Landsat Level-1 product IDs found in `search_path`.
    :param search_type: 'product' - folders and .tar/.tar.gz/.tgz archives of product bundles
                        'log'     - FORCE Level-2 processing logs (<product id>.log)
    :param no_partial_dls: If True, products accompanied by a .part or .aria2 file (unfinished
                           downloads) are not returned so that they get downloaded (resumed) again.
    """
    if search_type == 'product':
        regex = _PRODUCT_FILE_REGEX
    elif search_type == 'log':
        regex = _LOG_FILE_REGEX
    else:
        raise ValueError(f'Invalid search_type {search_type!r}, expected "product" or "log".')

    found, partial = set(), set()
    if not os.path.isdir(search_path):
        return found

    for root, dirs, filenames in os.walk(search_path):
        names = list(filenames) + list(dirs)
        matched_dirs = set()
        for name in names:
            m = regex.match(name)
            if m:
                found.add(m.group(1))
                if name in dirs:
                    matched_dirs.add(name)
            elif search_type == 'product' and no_partial_dls:
                p = _PARTIAL_FILE_REGEX.match(name)
                if p:
                    partial.add(p.group(1))
        # never descend into product folders or if not recursive
        dirs[:] = [] if not recursive else [d for d in dirs if d not in matched_dirs]

    return found - partial


def check_date_validity(dates: List[str], name: str) -> None:
    if len(dates) != 2:
        die(f'Error: {name} dates not provided in format YYYYMMDD,YYYYMMDD.')
    parsed = []
    for d in dates:
        try:
            parsed.append(datetime.strptime(d.strip(), '%Y%m%d'))
        except ValueError:
            die(f'Error: {name} dates not provided in format YYYYMMDD,YYYYMMDD or date is invalid: {d}')
    if parsed[0] > parsed[1]:
        die(f'Error: {name} start date {dates[0]} is after end date {dates[1]}.')


def is_valid_tile(path_row: str) -> bool:
    """WRS-2 path/row in the format PPPRRR (path 1-233, row 1-248)."""
    if not TILE_REGEX.match(path_row):
        return False
    path, row = int(path_row[0:3]), int(path_row[3:6])
    return 1 <= path <= 233 and 1 <= row <= 248


def check_tile_validity(tile_list: Iterable[str]) -> bool:
    tile_list = list(tile_list)
    return bool(tile_list) and all(is_valid_tile(t) for t in tile_list)


def load_tile_list(file_path: str) -> List[str]:
    validate_file_paths(file_path, 'tile list', file=True, write=False)
    with open(file_path) as file:
        tile_list = [line.strip() for line in file if line.strip()]
    if not check_tile_validity(tile_list):
        die('Invalid tile list. Make sure the file contains one path/row per line in the format PPPRRR. Exiting.')
    return sorted(set(tile_list))


def filter_results_by_pr(scene_response: list, pr_list: Iterable[str]) -> list:
    """Keep only scenes whose path/row (taken from the display ID) is in pr_list."""
    pr_set = set(pr_list)
    return [s for s in scene_response if s.get('displayId', '')[10:16] in pr_set]


def parse_secret(text: str) -> List[str]:
    """Parse the content of a secret file. Returns ['app-token', user, token] or [user, password]."""
    secret = [s.strip() for s in text.split()]
    if (
            len(secret) not in (2, 3) or
            len(secret) == 2 and secret[0] == 'app-token' or
            len(secret) == 3 and secret[0] != 'app-token'
    ):
        raise ValueError(f'Invalid secrets file. Expecting\n{SECRET_HELP}')
    return secret


def load_secret(file_path: str) -> List[str]:
    validate_file_paths(file_path, 'secrets', file=True, write=False)
    with open(file_path) as file:
        try:
            return parse_secret(file.read())
        except ValueError as e:
            die(str(e))


def validate_file_paths(path: str, name: str, file: bool = True, write: bool = False) -> str:
    path = os.path.realpath(path)
    rw, rw_string = (os.W_OK, 'writeable') if write else (os.R_OK, 'readable')
    f_d = 'file' if file else 'directory'

    if file and not os.path.isfile(path):
        die(f'Error: The specified {name} file path does not seem to be a file.\n{path}\n'
            f'Make sure to provide a path to a file, not a directory. Exiting.')
    if not file and not os.path.isdir(path):
        die(f'Error: The specified {name} directory does not seem to be a directory.\n{path}\n'
            f'Make sure to provide a path to a directory, not a file. Exiting.')
    if not os.access(path, rw):
        die(f'Error: {name.capitalize()} {f_d} does not exist or is not {rw_string}:\n{path}')
    return path


def bytes_to_humanreadable(size: Optional[float]) -> str:
    size = size or 0
    power = 0 if size <= 0 else min(floor(log(size, 1024)), 5)
    units = ['B', 'kB', 'MB', 'GB', 'TB', 'PB']
    return f'{round(size / 1024 ** power, 2)} {units[int(power)]}'


def total_size(products: Iterable[dict]) -> int:
    return sum(p.get('filesize') or 0 for p in products)


def product_id_from_url(url: str) -> Optional[str]:
    """Extract the Landsat product ID from a download URL, None if it does not contain one."""
    m = PRODUCT_ID_REGEX.search(url)
    return m.group(0) if m else None
