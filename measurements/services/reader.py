"""Reading uploaded files into a GeoDataFrame."""
import shutil
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from measurements.services.errors import ProcessingError

SUPPORTED_EXTENSIONS = {".zip": "shapefile", ".kml": "kml"}

# Zip-bomb guards: a small archive must not be able to expand into gigabytes.
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1000


def detect_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ProcessingError("Unsupported file type. Upload a .zip (Shapefile) or .kml file.")
    return SUPPORTED_EXTENSIONS[ext]


def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest = dest.resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ARCHIVE_MEMBERS:
                raise ProcessingError("Archive contains too many files.")
            if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
                raise ProcessingError("Archive expands to more than the allowed size.")
            for info in infos:
                if not (dest / info.filename).resolve().is_relative_to(dest):  # zip-slip guard
                    raise ProcessingError("Archive contains unsafe paths.")
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise ProcessingError("File is not a valid zip archive.") from exc


def _concat(frames: list[gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    if len(frames) == 1:
        return frames[0]
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)


def _read_shapefile(zip_path: Path) -> gpd.GeoDataFrame:
    extract_dir = zip_path.with_suffix("")
    try:
        _safe_extract(zip_path, extract_dir)
        shp_files = sorted(extract_dir.rglob("*.shp"))
        if not shp_files:
            raise ProcessingError("No .shp file found inside the archive.")
        return _concat([gpd.read_file(p) for p in shp_files])  # fully loaded into memory
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)  # extracted files are no longer needed


def _read_kml(path: Path) -> gpd.GeoDataFrame:
    # A KML file can hold several layers (folders); read them all.
    layers = [name for name, _ in pyogrio.list_layers(path)]
    gdf = _concat([gpd.read_file(path, layer=name, driver="KML") for name in layers])
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)  # KML is always WGS84 by specification
    return gdf


def read_geofile(path: Path, file_type: str) -> gpd.GeoDataFrame:
    try:
        gdf = _read_shapefile(path) if file_type == "shapefile" else _read_kml(path)
    except ProcessingError:
        raise
    except Exception as exc:  # GDAL/pyogrio raise a variety of types
        raise ProcessingError(f"Could not read geospatial data: {exc}") from exc
    if gdf.crs is None:
        raise ProcessingError("File has no CRS (missing .prj?). Cannot measure safely.")
    return gdf
