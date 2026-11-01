"""Area of interest -> list of WRS-2 path/rows (PPPRRR)."""
import os
from importlib.resources import files
from typing import List

from lsdownloader import utils

WRS2_FP = str(files('lsdownloader').joinpath('assets', 'landsat_wrs2.gpkg'))
VECTOR_EXTENSIONS = ('.shp', '.gpkg', '.geojson', '.json', '.kml', '.fgb')


class Aoi:
    """
    The AOI can be
      a) a .txt file with one path/row per line (PPPRRR)
      b) a vector file (.shp, .gpkg, .geojson, ...) with point, line or polygon geometries (any CRS)
      c) a comma separated list of path/rows, e.g. '193023,193024'
    """

    def __init__(self, fp: str):
        self.fp = fp
        self.type = self.determine_aoi_type()

    def determine_aoi_type(self) -> str:
        if not os.path.exists(self.fp):
            tiles = [t.strip() for t in self.fp.split(',') if t.strip()]
            if utils.check_tile_validity(tiles):
                return 'list'
        utils.validate_file_paths(self.fp, 'aoi', file=True, write=False)
        if self.fp.lower().endswith('.txt'):
            return 'txt'
        if self.fp.lower().endswith(VECTOR_EXTENSIONS):
            return 'vector'
        utils.die(
            'Error: invalid AOI. Please use one of the following:\n'
            '.txt - text file containing one tile per line in the format PPPRRR (P = path, R = row)\n'
            f'{", ".join(VECTOR_EXTENSIONS)} - vector file containing point, line, or polygon geometries\n'
            'or a comma separated list of path/rows, e.g. 193023,193024')

    def prlist_from_list(self) -> List[str]:
        return sorted({t.strip() for t in self.fp.split(',') if t.strip()})

    def prlist_from_txt(self) -> List[str]:
        with open(self.fp) as file:
            pr_list = [line.strip() for line in file if line.strip()]
        if not utils.check_tile_validity(pr_list):
            utils.die(
                'Error: invalid path/row values found in tile list.\n'
                'Make sure the file contains one tile per line in the format PPPRRR (P = path, R = row).\n'
                'Keep padding zeroes! Good: 194023, bad: 19423')
        return sorted(set(pr_list))

    def prlist_from_vector(self) -> List[str]:
        pr_list = vector_to_pathrows(self.fp)
        if not pr_list:
            utils.die('Error: AOI does not seem to intersect with WRS2 grid. Please check your input data.')
        return pr_list

    @property
    def get_footprints(self) -> List[str]:
        if self.type == 'list':
            return self.prlist_from_list()
        if self.type == 'txt':
            return self.prlist_from_txt()
        return self.prlist_from_vector()


def vector_to_pathrows(fp: str, wrs2_fp: str = WRS2_FP) -> List[str]:
    """Return the sorted WRS-2 path/rows whose footprint intersects the geometries of a vector file."""
    import geopandas as gpd  # imported lazily: only needed for vector AOIs

    aoi = gpd.read_file(fp)
    aoi = aoi[aoi.geometry.notna() & ~aoi.geometry.is_empty]
    if aoi.empty:
        return []
    if aoi.crs is None:
        utils.die(f'Error: {fp} has no coordinate reference system.')
    aoi = aoi.to_crs('EPSG:4326')
    geom = aoi.geometry.union_all() if hasattr(aoi.geometry, 'union_all') else aoi.geometry.unary_union

    # only read the grid features inside the AOI bounding box instead of the whole grid
    wrs2 = gpd.read_file(wrs2_fp, bbox=tuple(aoi.total_bounds))
    if wrs2.empty:
        return []
    hits = wrs2.intersects(geom)
    if geom.geom_type in ('Polygon', 'MultiPolygon'):
        # ignore tiles that only share a border with the AOI
        hits &= ~wrs2.touches(geom)
    return sorted({str(p).zfill(6) for p in wrs2.loc[hits, 'PRFID']})
