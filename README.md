# lsdownloader

Search and download Landsat Collection 2 Level 1 product bundles (Landsat 4/5 TM, 7 ETM+, 8/9 OLI-TIRS) using the [USGS/EROS machine-to-machine (M2M) API](https://m2m.cr.usgs.gov/).

`lsdownloader` is based on [landsatlinks](https://github.com/ernstste/landsatlinks) by Stefan Ernst and keeps its sub-commands and arguments, so existing landsatlinks commands work by replacing `landsatlinks` with `lsdownloader`.

Changes compared to landsatlinks:
- **No aria2 or GDAL needed.** Downloads use pure Python and work on Linux, macOS and Windows. AOIs are read with geopandas.
- **Parallel, resumable downloads.** Unfinished downloads are kept as `.part` files and resumed with HTTP range requests. A file is only renamed to `.tar` after its size has been checked, so a broken download never counts as finished.
- **Automatic retries** with backoff for connection errors, rate limiting (429) and server errors. One failed product no longer stops the whole job. Failed links are saved so they can be retried, and the command exits with a non-zero code.
- **More robust M2M API use.** Search results are fetched page by page (no 50,000 scene limit), the tool logs in again when the API key expires, and it waits when the rate limit is hit. Downloads that USGS is still preparing are polled until their link is ready.
- **More ways to log in.** Credentials can come from a secrets file, from the `M2M_USERNAME`/`M2M_TOKEN` environment variables, or from a prompt that asks for an application token.
- **More AOI types.** Path/rows can be given directly on the command line, e.g. `193023,193024`.
- **Bug fixes** in the product ID pattern and the path/row checks. The `RT` tier can now be selected.

### Requirements
You need a [USGS EarthExplorer](https://ers.cr.usgs.gov/) account with access to the M2M API, which you request on your [profile page](https://ers.cr.usgs.gov/profile/access).\
The USGS turned off the username/password login in February 2025, so you need an **application token**. [How to create an app token](https://www.usgs.gov/media/files/m2m-application-token-documentation).

### Install with Docker image
```
docker pull vudongpham/lsdownloader:latest
```
### Install with Singularity
```
singularity pull -F ~/lsdownloader_latest.sif docker://vudongpham/lsdownloader:latest
```

### Install with python
With Git installed on your machine
```
python -m pip install git+https://github.com/vudongpham/LandsatDownloader.git
```
Without Git
```
python -m pip install https://github.com/vudongpham/LandsatDownloader/archive/refs/heads/main.zip
```

### Credentials
Store your login in a text file, e.g. `secret.txt`, and pass it with `--secret`:
```
app-token
<username>
<token>
```
(The old two-line `<username>` / `<password>` format is still read, but the USGS no longer accepts it.)

You can also set the `M2M_USERNAME` and `M2M_TOKEN` environment variables. If neither is given, `lsdownloader` asks for them. Use `docker run -it` so the prompt works.

### Usage
There are two sub-commands, __search__ and __download__:
- __search__ finds the product bundles that match your query and gets their download links. It saves the links to a text file or, with `--download`, downloads the bundles right away.
- __download__ downloads product bundles from a links file that __search__ created earlier.

#### 1. `lsdownloader search`

_Required arguments:_
- aoi\
  The area of interest. Valid input:\
  a) .txt - text file containing one tile per line in the format PPPRRR (P = path, R = row) \
  Keep padding zeroes! Good: 194023, bad: 19423\
  b) .shp, .gpkg, .geojson - vector file containing point, line, or polygon geometries (any CRS)\
  c) comma separated path/rows directly, e.g. `193023,193024`
- output_dir\
  The directory where the file with the download URLs, or the downloaded products, will be stored (created if missing).

_Optional arguments:_
- -s | --sensor\
  Restrict results to specific sensor(s).\
  choices = 'TM', 'ETM', 'OLI' (Landsat 4/5, Landsat 7, Landsat 8/9), comma separated\
  Default: TM,ETM,OLI
- -d | --daterange\
  Start date and end date = date range to be considered (inclusive).\
  Format: YYYYMMDD,YYYYMMDD\
  Default: full archive until today.
- -c | --cloudcover\
  Percent (land) cloud cover range to be considered. A minimum of -1 also keeps scenes with unknown cloud cover.\
  Default: -1,100
- -m | --months\
  Seasonal filter: define the months to be considered.\
  Default: 1,2,3,4,5,6,7,8,9,10,11,12
- -i | --ingestrange\
  Ingestion time filter: only keep data added to the USGS EROS archive in this time range. Use it, for example, to leave out old Landsat 9 images that were reprocessed.\
  Format: YYYYMMDD,YYYYMMDD\
  Default: beginning of the archive until today.
- -t | --tier\
  Landsat collection tier level. Valid tiers: T1, T2, RT\
  Default: T1
- -l | --level\
  Landsat level of processing. Valid levels: L1TP, L1GT, L1GS (L1GT/L1GS require tier T2 or RT)\
  Default: L1TP
- --download\
  Download the product bundles directly after creating the download links.
- -n | --no-action\
  Only search for product bundles and print info about the search results, without creating links or downloading.
- -f | --forcelogs\
  Path to the directory with the FORCE Level-2 processing logs (searched recursively).\
  Links are only created for products that FORCE hasn't processed yet.
- -q | --queue-file\
  Path to FORCE queue file. The file path of each downloaded product bundle is added to the queue as soon as it finishes.
- --secret\
  Path to the secrets file (see [Credentials](#credentials)).
- -w | --workers\
  Number of parallel downloads with `--download`. Default: 4
- -r | --retries\
  Attempts per product bundle before giving up, with `--download`. Default: 3
- -o | --url-file\
  Where to write the download links. Default: `<output_dir>/urls_landsat_<sensors>_<timestamp>.txt`

Example: Landsat 8/9 over Berlin, October and November 2018-2020, max. 70% cloud cover.\
Docker
```
docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/lsdownloader lsdownloader search \
    -s OLI -d 20180101,20201231 -m 10,11 -c 0,70 \
    --secret $(pwd)/secret.txt --no-action \
    $(pwd)/tests/data/berlin_bbox.gpkg \
    $(pwd)/level1
```

Python
```
lsdownloader search -s OLI -d 20180101,20201231 -m 10,11 -c 0,70 \
    --secret ~/secret.txt --no-action \
    ~/berlin.gpkg ~/level1
```
Output
```
Sensor(s): OLI
Tile(s): 192023,192024,193023,193024
Date range: 2018-01-01 to 2020-12-31
Included months: 10,11
Cloud cover: 0% to 70%
Tier / level: T1 / L1TP

20 Landsat Level 1 scenes matching criteria found
22.13 GB data volume found
```
Leave out `--no-action` to write the links to `~/level1/urls_landsat_OLI_<timestamp>.txt`, or use `--download` to download right away.

#### 2. `lsdownloader download`

_Required arguments:_
- url_file\
  Path to the file containing the download links (one per line).
- output_dir\
  The directory where the product bundles will be stored.

_Optional arguments:_
- -q | --queue-file\
  Path to FORCE queue file. Downloaded product bundle file paths will be appended to the queue.
- -w | --workers\
  Number of parallel downloads. Default: 4
- -r | --retries\
  Attempts per product bundle before giving up. Default: 3

Docker
```
docker run -it --rm \
    -v $(pwd):$(pwd) \
    vudongpham/lsdownloader lsdownloader download \
    -q $(pwd)/level1/queue.txt \
    $(pwd)/level1/urls_landsat_OLI_20250101T120000.txt \
    $(pwd)/level1
```

Python
```
lsdownloader download ~/level1/urls_landsat_OLI_20250101T120000.txt ~/level1

Loading urls from ~/level1/urls_landsat_OLI_20250101T120000.txt

6 of 116 product bundles found in filesystem, 110 left to download.

Downloading:   5%|===>                     | 6/110 [08:36<2:29:13, 86.09s/product bundle]
```
Re-run the same command to resume an interrupted job. Finished product bundles are skipped and `.part` files are resumed.

### Gotchas
- `lsdownloader` checks the output directory __recursively__ (including all subfolders) for existing product bundles, and only creates download URLs for bundles it doesn't find. It counts every folder, .tar, .tar.gz and .tgz file whose name follows the [Landsat Collection Level-1 naming convention](https://www.usgs.gov/faqs/what-naming-convention-landsat-collection-2-level-1-and-level-2-scenes). Bundles that still have a `.part` file next to them (or a `.aria2` file, left over from landsatlinks) are treated as unfinished and downloaded again.
- The M2M API is rate limited to 15,000 requests per 15 minutes. If you go over this limit, `lsdownloader` waits 15 minutes and then continues. It checks the output directory for existing bundles before it requests download links, to avoid using up requests.
- Download links expire after some time. If many downloads fail with HTTP 403, run `search` again to get fresh links.

### Running the tests
```
python -m pip install pytest
python -m pytest tests
```
The tests run offline.

### License
MIT. Based on [landsatlinks](https://github.com/ernstste/landsatlinks), Copyright 2020-2022 Stefan Ernst.
