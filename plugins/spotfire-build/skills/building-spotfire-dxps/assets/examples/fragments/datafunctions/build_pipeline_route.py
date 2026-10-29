"""
==============================================================================
 Build Pipeline Route  (v1.0)
 Straight pipeline segments between consecutive pump stations, west to east,
 as map-ready tables for the Station Map page (assets/examples/fragments/maps.json):
   - PIPELINE_ROUTE    GeoDataFrame of WKB LineStrings (feature layer). The spotfire
                       package exports the geometry as a Binary column "Geometry"
                       tagged MapChart.ColumnTypeId = Geometry, plus the table
                       property MapChart.GeographicCrs = EPSG:4326.
   - PIPELINE_VERTICES one row per station in pipeline order (marker layer whose
                       markers are joined by a line connection).
 Runtime packages: numpy, pandas, geopandas, shapely. geopandas and shapely come from
 the "Spotfire Geospatial Library" Python package (deployed in this Analyst 15.0 as
 Modules/Spotfire Geospatial Library_1.1.0.63); customer servers need it deployed too.
------------------------------------------------------------------------------
STAGING: INPUT PARAMETERS  (Data function properties > Input parameters)
------------------------------------------------------------------------------
  name               type     document property     notes
  PUMP_DATA          Table    (table PUMP_DATA)     uses Station, Latitude, Longitude
------------------------------------------------------------------------------
STAGING: OUTPUT PARAMETERS (Data function properties > Output parameters)
------------------------------------------------------------------------------
  name               type     destination
  PIPELINE_ROUTE     Table    new data table "PIPELINE_ROUTE" (replace on refresh)
  PIPELINE_VERTICES  Table    new data table "PIPELINE_VERTICES" (replace on refresh)
------------------------------------------------------------------------------
 PIPELINE_ROUTE    - Pipeline Map (feature layer "Pipeline Segments",
                     marker layer "Segment Midpoints" at XCenter/YCenter)
 PIPELINE_VERTICES - Pipeline Map (marker layer "Pipeline Route", line by Route ID)
==============================================================================
"""
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString

# ============================== STAGING: INPUTS ==============================
try:
    PUMP_DATA
except NameError:
    PUMP_DATA = pd.DataFrame({
        "Station": ["Wink", "Crane", "Midland", "Big Spring"],
        "Latitude": [31.751, 31.397, 31.997, 32.250],
        "Longitude": [-103.160, -102.350, -102.078, -101.478],
    })
# ============================================================================

ROUTE_COLS = ["Segment ID", "From Station", "To Station", "Length (km)", "XCenter", "YCenter"]
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two WGS84 points."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return float(2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a)))


stations = PUMP_DATA[["Station", "Latitude", "Longitude"]].copy()
stations["Latitude"] = pd.to_numeric(stations["Latitude"], errors="coerce")
stations["Longitude"] = pd.to_numeric(stations["Longitude"], errors="coerce")
stations = (stations.dropna()
            .groupby("Station", as_index=False)[["Latitude", "Longitude"]].mean()
            .sort_values("Longitude")
            .reset_index(drop=True))

rows, lines = [], []
for i in range(len(stations) - 1):
    a, b = stations.iloc[i], stations.iloc[i + 1]
    rows.append({
        "Segment ID": "S%02d" % (i + 1),
        "From Station": str(a["Station"]),
        "To Station": str(b["Station"]),
        "Length (km)": haversine_km(a["Latitude"], a["Longitude"], b["Latitude"], b["Longitude"]),
        "XCenter": float((a["Longitude"] + b["Longitude"]) / 2.0),
        "YCenter": float((a["Latitude"] + b["Latitude"]) / 2.0),
    })
    lines.append(LineString([(a["Longitude"], a["Latitude"]), (b["Longitude"], b["Latitude"])]))

# ============================== STAGING: OUTPUTS =============================
PIPELINE_ROUTE = gpd.GeoDataFrame(pd.DataFrame(rows, columns=ROUTE_COLS),
                                  geometry=lines, crs="EPSG:4326")
PIPELINE_VERTICES = pd.DataFrame({
    "Route ID": ["Main Line"] * len(stations),
    "Seq": np.arange(1, len(stations) + 1),
    "Station": stations["Station"].astype(str),
    "Latitude": stations["Latitude"],
    "Longitude": stations["Longitude"],
})

# ===================== OUTPUT DTYPE COERCION =====================
# "string" dtype keeps String columns typed even when a table is empty (an empty object
# column cannot be typed by the SBDF exporter).
INT_COLS = ["Seq"]
REAL_COLS = ["Length (km)", "XCenter", "YCenter", "Latitude", "Longitude"]
STR_COLS = ["Segment ID", "From Station", "To Station", "Route ID", "Station"]
for frame in (PIPELINE_ROUTE, PIPELINE_VERTICES):
    for c in INT_COLS:
        if c in frame.columns:
            frame[c] = pd.to_numeric(frame[c], errors="coerce").fillna(0).astype("int64")
    for c in REAL_COLS:
        if c in frame.columns:
            frame[c] = pd.to_numeric(frame[c], errors="coerce").astype("float64")
    for c in STR_COLS:
        if c in frame.columns:
            frame[c] = frame[c].astype("string")
# =================================================================
