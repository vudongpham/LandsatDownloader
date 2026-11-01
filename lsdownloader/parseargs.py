import argparse
from datetime import date

from lsdownloader import __version__
from lsdownloader.utils import PROG_NAME

REPO_URL = 'https://github.com/vudongpham/LandsatDownloader'


class _Formatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawTextHelpFormatter):
    pass


def positive_int(value):
    try:
        v = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f'{value} is not an integer')
    if v < 1:
        raise argparse.ArgumentTypeError(f'{value} must be >= 1')
    return v


def build_parser() -> argparse.ArgumentParser:
    current_date = date.today().strftime('%Y%m%d')

    parser = argparse.ArgumentParser(
        prog=PROG_NAME,
        description='Search and download Landsat Collection 2 Level 1 product bundles using the USGS '
                    f'machine-to-machine API. {REPO_URL}'
    )
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'{PROG_NAME} version {__version__} {REPO_URL}'
    )
    subparsers = parser.add_subparsers(dest='command')

    # ------------------------------------------------------------------------------------------------------------------
    # search
    parser_search = subparsers.add_parser(
        'search', formatter_class=_Formatter,
        help='Search for products, generate download links and optionally download the results.'
    )
    parser_search.add_argument(
        'aoi',
        help='Area of interest. Supported:\n'
             'a) .txt - one path/row per line in the format PPPRRR\n'
             'b) .shp, .gpkg, .geojson - vector file (any CRS)\n'
             'c) comma separated path/rows, e.g. 193023,193024'
    )
    parser_search.add_argument(
        'output_dir',
        help='Output directory where the download links and downloaded products will be stored.'
    )
    parser_search.add_argument(
        '-s', '--sensor',
        default='TM,ETM,OLI',
        help='Sensor(s): TM (Landsat 4/5), ETM (Landsat 7), OLI (Landsat 8/9),\n'
             'or a comma-separated list (e.g. ETM,OLI).'
    )
    parser_search.add_argument(
        '-d', '--daterange',
        default=f'19700101,{current_date}',
        help='Start date and end date (inclusive). Format: YYYYMMDD,YYYYMMDD.\n'
             'Default: beginning of archive until today.'
    )
    parser_search.add_argument(
        '-c', '--cloudcover',
        default='-1,100',
        help='Percent (land) cloud cover range to be considered.\n'
             'A minimum of -1 includes scenes with unknown cloud cover.'
    )
    parser_search.add_argument(
        '-m', '--months',
        default='1,2,3,4,5,6,7,8,9,10,11,12',
        help='Seasonal filter - months to be considered.'
    )
    parser_search.add_argument(
        '-i', '--ingestrange',
        default=f'19700101,{current_date}',
        help='Filter for when data was added to the USGS EROS archive.\n'
             'Start and end date. Format: YYYYMMDD,YYYYMMDD.\n'
             'Default: beginning of archive until today.'
    )
    parser_search.add_argument(
        '-t', '--tier',
        choices=['T1', 'T2', 'RT'],
        default='T1',
        help='Landsat collection tier level.'
    )
    parser_search.add_argument(
        '-l', '--level',
        choices=['L1TP', 'L1GT', 'L1GS'],
        default='L1TP',
        help='Landsat level of processing.'
    )
    search_group = parser_search.add_mutually_exclusive_group()
    search_group.add_argument(
        '--download',
        action='store_true',
        help='Download the product bundles directly after creating the download links.'
    )
    search_group.add_argument(
        '-n', '--no-action',
        action='store_true',
        help='Only search for product bundles and print info without generating links or downloading.'
    )
    parser_search.add_argument(
        '-f', '--forcelogs',
        help='Path to FORCE Level-2 log files (searched recursively).\n'
             'Products that have been processed by FORCE are skipped.'
    )
    parser_search.add_argument(
        '-q', '--queue-file',
        default=None,
        help='Path to FORCE queue file. Downloaded product bundles will be appended to the queue.'
    )
    parser_search.add_argument(
        '--secret',
        help='Path to the file containing the M2M API login (EarthExplorer account):\n'
             "a) 1st line: 'app-token', 2nd line: user, 3rd line: token (recommended)\n"
             'b) 1st line: user, 2nd line: password - deprecated by the USGS API since February 2025\n'
             'If omitted, the M2M_USERNAME and M2M_TOKEN environment variables are used,\n'
             'otherwise you will be prompted.'
    )
    parser_search.add_argument(
        '-w', '--workers',
        type=positive_int, default=4,
        help='Number of parallel downloads (with --download).'
    )
    parser_search.add_argument(
        '-r', '--retries',
        type=positive_int, default=3,
        help='Attempts per product bundle before giving up (with --download).'
    )
    parser_search.add_argument(
        '-o', '--url-file',
        default=None,
        help='Path of the file the download links are written to.\n'
             'Default: <output_dir>/urls_landsat_<sensors>_<timestamp>.txt'
    )

    # ------------------------------------------------------------------------------------------------------------------
    # download
    parser_dl = subparsers.add_parser(
        'download', formatter_class=_Formatter,
        help='Load URLs from a text file and download without creating download links first.'
    )
    parser_dl.add_argument(
        'url_file',
        help='Path to the file containing the urls to download.'
    )
    parser_dl.add_argument(
        'output_dir',
        help='Path to the output directory where the downloaded products will be stored.'
    )
    parser_dl.add_argument(
        '-q', '--queue-file',
        default=None,
        help='Path to FORCE queue file. Downloaded product bundles will be appended to the queue.'
    )
    parser_dl.add_argument(
        '-w', '--workers',
        type=positive_int, default=4,
        help='Number of parallel downloads.'
    )
    parser_dl.add_argument(
        '-r', '--retries',
        type=positive_int, default=3,
        help='Attempts per product bundle before giving up.'
    )

    return parser


def parse_cli_arguments(argv=None):
    return build_parser().parse_args(argv)
