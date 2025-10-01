# --- bootstrap: install missing deps (installs only if missing) ---
import sys, subprocess, importlib.util
def ensure_packages(mod_to_pip):
    missing = [pip for mod, pip in mod_to_pip
               if importlib.util.find_spec(mod) is None]
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
ensure_packages([
    ("geopandas", "geopandas"),
    ("folium",    "folium"),
    ("shapely",   "shapely"),
    ("pyproj",    "pyproj"),
    ("fiona",     "fiona"),
])

# --- R → Python equivalent map ---
import json
import geopandas as gpd
import folium
from pathlib import Path

# 1) Read shapefile
shp_path = Path("tl_2021_18_tract.shp")   # adjust path if needed
gdf = gpd.read_file(shp_path)

# 2) CRS: assign NAD83 only if missing, then transform to WGS84
if gdf.crs is None:
    gdf = gdf.set_crs(epsg=4269)          # only if you KNOW source is NAD83
gdf = gdf.to_crs(epsg=4326)               # leaflet expects 4326

# 3) Filter to the same counties as your R work (Elkhart, St. Joseph, Marshall)
keep_fips = {"039", "141", "099"}
gdf = gdf[gdf["COUNTYFP"].astype(str).isin(keep_fips)].copy()

# (Optional) If you patched NAME like "113.10" → "113.1" in R:
#gdf["NAME"] = gdf["NAME"].astype(str).str.replace(r"^113\.10$", "113.1", regex=True)

# 4) Build the map with same style and tooltip label ~NAME
m = folium.Map(tiles="OpenStreetMap")     # no zoom_start; we'll fit to layer bounds

style = {"color": "black", "weight": 1, "fillOpacity": 0.25}
gj = folium.GeoJson(
    data=json.loads(gdf.to_json()),       # avoids Shapely 2.x array-interface issue
    name="Tracts",
    style_function=lambda _: style,
    tooltip=folium.GeoJsonTooltip(fields=["NAME"], aliases=["Tract:"])
).add_to(m)

# Fit to bounds (to match leaflet’s default extent behavior)
minx, miny, maxx, maxy = gdf.total_bounds
m.fit_bounds([[miny, minx], [maxy, maxx]])

folium.LayerControl(collapsed=False).add_to(m)
m.save("TranspoFoodiePovMap5_2.html")
print("Saved: TranspoFoodiePovMap5_2.html")
