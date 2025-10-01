# --- bootstrap: install missing deps (installs only if missing) ---
import sys, subprocess, importlib.util
def ensure_packages(mod_to_pip):
    missing = [pip for mod, pip in mod_to_pip if importlib.util.find_spec(mod) is None]
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
ensure_packages([
    ("geopandas","geopandas"), ("folium","folium"),
    ("shapely","shapely"), ("pyproj","pyproj"),
    ("fiona","fiona"), ("branca","branca"),
    ("pandas","pandas"),
])

# --- imports ---
import json, warnings
from pathlib import Path
import pandas as pd
import geopandas as gpd
import folium
import branca.colormap as cm

# ----------------------------
# 1) Load tracts (merged_df equivalent) and prep CRS
# ----------------------------
tracts_path = Path("merged_df.geojson")  # preferred (has PovertyNum, MedianIncomeNum, CensusReporter_Link)
fallback_shp = Path("tl_2021_18_tract.shp")

if tracts_path.exists():
    gdf = gpd.read_file(tracts_path)
else:
    gdf = gpd.read_file(fallback_shp)

# CRS: set if unknown (only if you KNOW source), then transform to WGS84
if gdf.crs is None:
    # if you know the source is NAD83, uncomment next line
    # gdf = gdf.set_crs(4269)
    # otherwise assume already lon/lat; set to 4326 so folium works
    gdf = gdf.set_crs(4326)
gdf = gdf.to_crs(4326)

# Filter to Elkhart(039), St. Joseph(141), Marshall(099) if COUNTYFP present
keep_fips = {"039", "141", "099"}
if "COUNTYFP" in gdf.columns:
    gdf = gdf[gdf["COUNTYFP"].astype(str).isin(keep_fips)].copy()

# Ensure NAME exists (for label)
if "NAME" not in gdf.columns:
    gdf["NAME"] = gdf.index.astype(str)

# Poverty & income fields (mirror R)
def percent_to_float(s):
    return pd.to_numeric(pd.Series(s).astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")

has_poverty = False
if "PovertyNum" in gdf.columns:
    gdf["PovertyNum"] = pd.to_numeric(gdf["PovertyNum"], errors="coerce"); has_poverty = True
elif "POVERTY" in gdf.columns:
    gdf["PovertyNum"] = percent_to_float(gdf["POVERTY"]); has_poverty = True
else:
    gdf["PovertyNum"] = pd.NA  # keep column to avoid KeyError

if "MedianIncomeNum" not in gdf.columns and "Median.Income." in gdf.columns:
    gdf["MedianIncomeNum"] = pd.to_numeric(
        gdf["Median.Income."].astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce"
    )

gdf["PovertyLabel"] = gdf["PovertyNum"].map(lambda x: f"{float(x):.1f}%" if pd.notna(x) else "N/A")
gdf["MedianIncomeLabel"] = gdf.get("MedianIncomeNum", pd.Series([None]*len(gdf))).map(
    lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"
)

# ----------------------------
# 2) Base map (CartoDB.Positron) + fit bounds
# ----------------------------
m = folium.Map(tiles="CartoDB positron")
minx, miny, maxx, maxy = gdf.total_bounds
m.fit_bounds([[miny, minx], [maxy, maxx]])

# ----------------------------
# 3) Poverty Layer (filled polygons, white borders, highlight)
# ----------------------------
cmap = None
if has_poverty and gdf["PovertyNum"].notna().any():
    valid = gdf.dropna(subset=["PovertyNum"])
    vmin, vmax = float(valid["PovertyNum"].min()), float(valid["PovertyNum"].max())
    cmap = cm.linear.PuRd_09.scale(vmin, vmax)  # similar to R pal_poverty
    cmap.caption = "Poverty Level (%)"

def poverty_style(feat):
    # Fill color encodes poverty (like R); white borders, thin weight
    if cmap is not None:
        val = feat["properties"].get("PovertyNum", None)
        fill = "#cccccc" if val is None else cmap(val)
    else:
        fill = "#cccccc"
    return {"fillColor": fill, "fillOpacity": 0.55, "color": "white", "weight": 0.3}

poverty_fg = folium.FeatureGroup(name="Poverty Level", show=False)
folium.GeoJson(
    data=json.loads(gdf.to_json()),
    name="Poverty Level",
    style_function=poverty_style,
    highlight_function=lambda f: {"weight": 2, "color": "#666", "fillOpacity": 0.9},
    tooltip=folium.GeoJsonTooltip(
        fields=["NAME", "PovertyLabel"],
        aliases=["Tract", "Poverty"],
        sticky=False
    ),
).add_to(poverty_fg)

# Polygon popups: build rich HTML like your R popup
for _, row in gdf.iterrows():
    try:
        c = row.geometry.centroid  # attach popup at centroid (folium limitation for clickable link)
        html = (
            f"<strong>Tract {row.get('NAME','')}</strong><br>"
            f"Poverty Level: {row.get('PovertyLabel','N/A')}<br>"
            f"Median Income: {row.get('MedianIncomeLabel','N/A')}<br>"
        )
        link = row.get("CensusReporter_Link") or row.get("CensusReporter_Link ")
        if isinstance(link, str) and link.strip():
            html += f"<a href='{link}' target='_blank'>View Full Tract Info</a>"
        folium.Marker([c.y, c.x], popup=folium.Popup(html, max_width=420),
                      icon=folium.DivIcon(html="")).add_to(poverty_fg)
    except Exception:
        pass

poverty_fg.add_to(m)
if cmap is not None:
    cmap.add_to(m)  # legend (note: folium doesn't support bottom-right position out of the box)

# ----------------------------
# 4) County Boundaries (always visible; label & popup)
# ----------------------------
# If you have target_counties, load it; else dissolve tracts by COUNTYFP to get boundaries
target_counties_path = Path("target_counties.geojson")
if target_counties_path.exists():
    target_counties = gpd.read_file(target_counties_path)
    if target_counties.crs is None: target_counties = target_counties.set_crs(4326)
    target_counties = target_counties.to_crs(4326)
else:
    if "COUNTYFP" in gdf.columns:
        name_map = {"039": "Elkhart", "141": "St. Joseph", "099": "Marshall"}
        tmp = gdf[["COUNTYFP","geometry"]].copy()
        tmp["name"] = tmp["COUNTYFP"].map(name_map).fillna(tmp["COUNTYFP"])
        target_counties = tmp.dissolve(by="name", as_index=False)
    else:
        target_counties = gpd.GeoDataFrame(geometry=[])

if len(target_counties):
    folium.GeoJson(
        data=json.loads(target_counties.to_json()),
        name="County Boundaries",
        style_function=lambda f: {"color": "black", "weight": 3, "opacity": 0.8, "fillOpacity": 0},
        tooltip=folium.GeoJsonTooltip(fields=["name"], aliases=["County"]) if "name" in target_counties.columns else None,
        popup=folium.GeoJsonPopup(fields=["name"], aliases=["County"]) if "name" in target_counties.columns else None
    ).add_to(m)  # not in a FeatureGroup → not togglable (always on)

# ----------------------------
# 5) Bus Routes (custom colors; label & popup; hidden by default)
# ----------------------------
routes_path = Path("TranspoRoutes.shp")
if routes_path.exists():
    routes = gpd.read_file(routes_path)
    if routes.crs is None:
        routes = routes.set_crs(4326)  # set proper source CRS if known, then to_crs(4326)
    else:
        routes = routes.to_crs(4326)

    # keep only routes intersecting selected tracts (optional)
    try:
        region = gdf.unary_union
        routes = routes[routes.intersects(region)]
    except Exception:
        pass

    # choose route name column
    label_col = next((c for c in ["clean_name","line_name","route_long_name","route_short_name"] if c in routes.columns), None)
    if label_col is None:
        routes["clean_name"] = routes.index.astype(str); label_col = "clean_name"

    # R palette → hex
    route_colors_hex = {
        "1 Madison / Mishawaka": "#000080", "10 Western Avenue": "#00E5EE",
        "11 Southside Mishawaka": "#FF34B3", "12 Rum Village": "#191970",
        "12/14 Rum Village / Sample": "#D8BFD8", "13 Corby / Town & Country": "#FFFF00",
        "14 Sample / Mayflower": "#7A378B",
        "15A University Park Mall / Mishawaka (via Main Stree)": "#8B4513",
        "15B University Park Mall / Mishawaka (via Grape Road)": "#8B7355",
        "16 Blackthorn Express": "#FF69B4", "17 The Sweep": "#B3EE3A",
        "3A Portage": "#B22222", "3B Portage": "#FF3030",
        "4 Lincolnway West / Excel Center / Airport": "#FF8C00",
        "5 North Michigan / Laurel Woods": "#000080", "6 South Michigan / Erskine Village": "#EE0000",
        "7 Notre Dame / University Park Mall": "#228B22", "7A Notre Dame Midnight Express": "#00CD00",
        "8 Miami / Scottsdale": "#40E0D0",
        "8/6 Miami / Scottsdale / South Michigan / Erskine Vi": "#EE0000",
        "9 Northside Mishawaka": "#CD00CD",
    }
    # note: keys must match your routes[label_col] exactly (they look truncated in your R code)

    routes["__color__"] = routes[label_col].map(route_colors_hex).fillna("#808080")

    routes_fg = folium.FeatureGroup(name="Bus Routes", show=False)
    folium.GeoJson(
        data=json.loads(routes.to_json()),
        name="Bus Routes",
        style_function=lambda f: {"color": f["properties"].get("__color__","#808080"), "weight": 3, "opacity": 0.9},
        tooltip=folium.GeoJsonTooltip(fields=[label_col], aliases=["Route"]),
        popup=folium.GeoJsonPopup(fields=[label_col], aliases=["Route"])
    ).add_to(routes_fg)
    routes_fg.add_to(m)
else:
    warnings.warn("TranspoRoutes.shp not found; skipping Bus Routes layer.")

# ----------------------------
# 6) Pantry Coverage (approx of addGlPolygons; hidden by default)
# ----------------------------
pantries_poly_path = Path("pantries_sf.geojson")
if pantries_poly_path.exists():
    pantries_sf = gpd.read_file(pantries_poly_path)
    if pantries_sf.crs is None: pantries_sf = pantries_sf.set_crs(4326)
    pantries_sf = pantries_sf.to_crs(4326)

    cover_fg = folium.FeatureGroup(name="Pantry Coverage", show=False)
    def cover_style(_):
        return {"fillColor": "#9370DB", "fillOpacity": 0.18, "color": "#6A5ACD", "opacity": 0.1, "weight": 1}
    folium.GeoJson(data=json.loads(pantries_sf.to_json()), style_function=cover_style).add_to(cover_fg)
    cover_fg.add_to(m)

# ----------------------------
# 7) Pantry Markers (clustered; hidden by default)
# ----------------------------
pantries_csv = Path("pantries.csv")
if pantries_csv.exists():
    from folium.plugins import MarkerCluster
    pantries = pd.read_csv(pantries_csv)
    pantries_fg = folium.FeatureGroup(name="Food Pantries", show=False)
    cluster = MarkerCluster().add_to(pantries_fg)

    def val(r, k): v = r.get(k); return "" if pd.isna(v) else str(v)
    for _, r in pantries.iterrows():
        lat, lon = r.get("lat"), r.get("long")
        if pd.isna(lat) or pd.isna(lon): continue
        html = (
            f"<strong>{val(r,'Pantry.Name')}</strong><br>"
            f"Address: {val(r,'Address')}<br>"
            f"Hours: {val(r,'Recurring.Hours')}<br>"
            f"Requirements: {val(r,'What.to.Bring')}<br>"
        )
        link = r.get("Link")
        if isinstance(link, str) and link.strip():
            html += f"<a href='{link}' target='_blank'>View on Google Maps</a>"
        folium.Marker([lat, lon], popup=folium.Popup(html, max_width=420)).add_to(cluster)
    pantries_fg.add_to(m)

# ----------------------------
# 8) Layer control (overlay groups toggled; county boundaries fixed)
# ----------------------------
folium.LayerControl(collapsed=False).add_to(m)

# ----------------------------
# 9) Save
# ----------------------------
m.save("TranspoFoodiePovMap5_1.html")
print("Saved: TranspoFoodiePovMap5_1.html")
