import os
import sys
from datetime import datetime
from getpass import getpass
from typing import Optional, Tuple

from lsdownloader import aoi, download, utils
from lsdownloader.eeapi import DATASETS, APIError, eeapi
from lsdownloader.parseargs import build_parser


def get_credentials(secret_fp: Optional[str]) -> Tuple[str, str, bool]:
    """Return (user, password/token, use_login_token) from the secret file, the
    M2M_USERNAME/M2M_TOKEN environment variables or an interactive prompt."""
    if secret_fp:
        secret = utils.load_secret(os.path.realpath(secret_fp))
        if len(secret) == 3:
            return secret[1], secret[2], True
        return secret[0], secret[1], False

    user, token = os.environ.get('M2M_USERNAME'), os.environ.get('M2M_TOKEN')
    if user and token:
        return user, token, True

    if not sys.stdin.isatty():
        utils.die('Error: no credentials. Use --secret or set M2M_USERNAME and M2M_TOKEN '
                  '(run docker with -it to be prompted).')
    print('\n')
    user = input('Enter your USGS EarthExplorer username: ')
    token = getpass('Enter your USGS M2M application token: ')
    return user, token, True


def _validate_queue_path(queue_path: Optional[str]) -> None:
    if not queue_path:
        return
    if os.path.isfile(queue_path):
        utils.validate_file_paths(queue_path, 'queue', file=True, write=True)
    else:
        utils.validate_file_paths(os.path.dirname(os.path.realpath(queue_path)), 'queue', file=False, write=True)


def _prepare_output_dir(path: str) -> str:
    output_dir = os.path.realpath(path)
    os.makedirs(output_dir, exist_ok=True)
    utils.validate_file_paths(output_dir, 'downloads', file=False, write=True)
    return output_dir


def run_download(args) -> int:
    output_dir = _prepare_output_dir(args.output_dir)
    _validate_queue_path(args.queue_file)
    utils.validate_file_paths(args.url_file, 'url file', file=True, write=False)
    return download.download_standalone(links_fp=args.url_file, output_dir=output_dir,
                                        n_tasks=args.workers, queue_fp=args.queue_file, retries=args.retries)


def run_search(args) -> int:
    # ==================================================================================================================
    # 1. Check input and set up variables
    output_dir = _prepare_output_dir(args.output_dir)
    queue_path = args.queue_file
    _validate_queue_path(queue_path)

    # load pathrow list
    pr_list = aoi.Aoi(args.aoi).get_footprints

    # dataset names
    sensors = [s.strip().upper() for s in args.sensor.split(',') if s.strip()]
    if not sensors or not all(s in DATASETS for s in sensors):
        utils.die('Error: Invalid sensor name. Please use one of the following: TM/ETM/OLI.\n'
                  'A comma-separated combination of sensor names is also possible (e.g. ETM,OLI)\nExiting.')
    sensors = list(dict.fromkeys(sensors))
    dataset_names = [DATASETS[s] for s in sensors]

    # validate dates and set range
    dates = args.daterange.split(',')
    utils.check_date_validity(dates, 'Start/End')
    start, end = [datetime.strptime(d.strip(), '%Y%m%d').strftime('%Y-%m-%d') for d in dates]

    # validate and set cloud cover thresholds
    try:
        min_cc, max_cc = (float(v) for v in args.cloudcover.split(','))
    except ValueError:
        utils.die('Error: Cloud cover must be given as min,max, e.g. 0,70.')
    if not (-1 <= min_cc <= 100 and -1 <= max_cc <= 100) or min_cc > max_cc:
        utils.die('Error: Cloud cover values must be between -1 and 100 (min <= max).')

    # seasonal filter
    try:
        seasonal_filter = sorted({int(m) for m in args.months.split(',') if m.strip()})
    except ValueError:
        utils.die('Error: Months must be given as a comma separated list, e.g. 6,7,8.')
    if not seasonal_filter or not all(1 <= m <= 12 for m in seasonal_filter):
        utils.die('Error: Months must be between 1 and 12.')

    # ingestion time filter
    ingest_dates = args.ingestrange.split(',')
    utils.check_date_validity(ingest_dates, 'Ingest')
    ingest_filter = [datetime.strptime(d.strip(), '%Y%m%d').strftime('%Y-%m-%d') for d in ingest_dates]

    # make sure chosen combinations of tier and processing level make sense
    if args.level != 'L1TP' and args.tier == 'T1':
        utils.die('Error: Tier 1 selected with processing level L1GT or L1GS (tier defaults to T1 if not specified).\n'
                  'Choose Tier 2 (T2) or Real-Time (RT) for processing levels lower than L1TP.')

    # validate FORCE Level-2 log path
    if args.forcelogs:
        utils.validate_file_paths(args.forcelogs, 'FORCE log', file=False, write=False)

    # ==================================================================================================================
    # 2. Run
    user, passwd, use_login_token = get_credentials(args.secret)
    api = eeapi(user, passwd, use_login_token)

    try:
        print(
            f'\nSensor(s): {", ".join(sensors)}\n'
            f'Tile(s): {",".join(pr_list)}\n'
            f'Date range: {start} to {end}\n'
            f'Included months: {",".join(str(m) for m in seasonal_filter)}\n'
            f'Cloud cover: {min_cc:g}% to {max_cc:g}%\n'
            f'Tier / level: {args.tier} / {args.level}\n'
        )

        # Get product IDs of products that match the search criteria
        products = []
        for dataset_name in dataset_names:
            products.extend(api.retrieve_search_results(
                datasetName=dataset_name, data_type_l1=args.level, tier=args.tier,
                start=start, end=end, seasonalFilter=seasonal_filter,
                ingestFilter=ingest_filter,
                minCC=min_cc, maxCC=max_cc,
                prList=pr_list
            ))
        if not products:
            print('No scenes matching search results found. Exiting.')
            return 0

        print(f'{len(products)} Landsat Level 1 scenes matching criteria found\n'
              f'{utils.bytes_to_humanreadable(utils.total_size(products))} data volume found')

        # Check for FORCE Level-2 log files in the filesystem
        if args.forcelogs:
            print('\nChecking file system for FORCE Level-2 processing log files.')
            processed = utils.find_files(search_path=args.forcelogs, search_type='log', recursive=True)
            if not processed:
                print(f'No FORCE logs found at {args.forcelogs}')
            else:
                products = [p for p in products if p['displayId'] not in processed]
                if not products:
                    print(f'{len(processed)} FORCE log files found, '
                          f'all product bundles from search already processed.\nExiting.')
                    return 0
                print(f'{len(processed)} FORCE log files found, '
                      f'{len(products)} products from search results not processed by FORCE yet.\n'
                      f'Remaining download size: {utils.bytes_to_humanreadable(utils.total_size(products))}')

        # Check for existing product bundles in filesystem
        in_filesystem = utils.find_files(search_path=output_dir, search_type='product', recursive=True)
        if in_filesystem:
            n_before = len(products)
            products = [p for p in products if p['displayId'] not in in_filesystem]
            if not products:
                print(f'{len(in_filesystem)} product bundles found in output directory, '
                      f'nothing left to download.\nExiting.')
                return 0
            if len(products) < n_before:
                print(f'{n_before - len(products)} product bundles found in output directory, '
                      f'{len(products)} not downloaded yet.\n'
                      f'Remaining download size: {utils.bytes_to_humanreadable(utils.total_size(products))}')

        if args.no_action:
            return 0

        # Generate download links
        urls = api.get_download_links(dl_product_ids=products)
    finally:
        api.logout()

    if not urls:
        print('Error: the M2M API did not return any download links.', file=sys.stderr)
        return 1

    if args.download:
        # Download product bundles
        _, failed = download.download(urls=urls, output_dir=output_dir, n_tasks=args.workers,
                                      force_queue_fp=queue_path, retries=args.retries)
        if failed:
            links_path = os.path.join(output_dir, f'urls_failed_{datetime.now():%Y%m%dT%H%M%S}.txt')
            download.write_links(failed, links_path)
            print(f'{len(failed)} download(s) failed, their links were written to {links_path}\n'
                  f'Retry with: {utils.PROG_NAME} download {links_path} {output_dir}')
            return 1
        print('Download complete')
        return 0

    # or just save download urls to disk
    links_path = args.url_file or os.path.join(
        output_dir, f'urls_landsat_{"_".join(sensors)}_{datetime.now():%Y%m%dT%H%M%S}.txt')
    print(f'Writing download links to {links_path}\n')
    download.write_links(urls, links_path)
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        print(f'No arguments provided, run "{utils.PROG_NAME} --help" for more information')
        parser.print_help()
        sys.exit(1)

    try:
        code = run_download(args) if args.command == 'download' else run_search(args)
    except KeyboardInterrupt:
        print('\nCTRL+C detected, exiting')
        sys.exit(130)
    except APIError as e:
        utils.die(f'Error: {e}')
    sys.exit(code)
