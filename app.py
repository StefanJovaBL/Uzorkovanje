import streamlit as st
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely.ops import transform
from shapely import affinity
from pyproj import CRS, Transformer
import folium
from folium.plugins import Draw, LocateControl
from streamlit_folium import st_folium
import numpy as np
import json

st.set_page_config(page_title="WebGIS Šema Uzorkovanja", layout="wide")

st.title("🌾 WebGIS Alat za Automatsku Šemu Uzorkovanja Tla")
st.markdown("Nacrtajte parcelu na satelitskom snimku ili učitajte GeoJSON fajl. Aplikacija optimizuje orijentaciju, rotira šemu za **45 stepeni** i dijeli parcelu u **mrežu od 15 zona (3 reda × 5 kolona)**.")

if "drawn_polygon" not in st.session_state:
    st.session_state.drawn_polygon = None

if st.session_state.drawn_polygon is not None:
    if st.button("🔄 Poništi i unesi novu parcelu"):
        st.session_state.drawn_polygon = None
        st.rerun()

poly_wgs84 = st.session_state.drawn_polygon

if poly_wgs84 is None:
    input_mode = st.radio("Izaberite način unosa parcele:", ["✍️ Nacrtaj na mapi", "📁 Učitaj GeoJSON fajl"], key="input_mode_radio")
    
    if input_mode == "📁 Učitaj GeoJSON fajl":
        uploaded_file = st.file_uploader("Učitajte fajl granice parcele:", type=["geojson", "json"], key="geojson_uploader")
        if uploaded_file is not None:
            try:
                gdf = gpd.read_file(uploaded_file)
                if not gdf.empty:
                    if gdf.crs is not None and gdf.crs != "EPSG:4326":
                        gdf = gdf.to_crs("EPSG:4326")
                    geom = gdf.geometry.iloc[0]
                    if isinstance(geom, MultiPolygon):
                        poly_wgs84 = max(geom.geoms, key=lambda a: a.area)
                    elif isinstance(geom, Polygon):
                        poly_wgs84 = geom
                    
                    if poly_wgs84 and poly_wgs84.is_valid:
                        st.session_state.drawn_polygon = poly_wgs84
                        st.rerun()
                    else:
                        st.error("Učitana geometrija nije validan poligon.")
            except Exception as e:
                st.error(f"Greška pri čitanju fajla: {e}")
    
    else:
        m = folium.Map(location=[44.7722, 17.1910], zoom_start=14)

        folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Satelitska mapa', show=True).add_to(m)
        folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Nazivi i granice', overlay=True).add_to(m)

        LocateControl(auto_start=False, position='bottomleft', strings={"title": "Prikaži moj GPS položaj", "popup": "Vaša trenutna lokacija"}, locate_options={"maxZoom": 18, "enableHighAccuracy": True}).add_to(m)

        draw = Draw(export=False, position='topleft', draw_options={'polyline': False, 'rectangle': False, 'circle': False, 'marker': False, 'circlemarker': False, 'polygon': True}, edit_options={'edit': True})
        draw.add_to(m)
        folium.LayerControl().add_to(m)

        st.subheader("Nacrtajte granicu parcele klikom na mapu:")
        output = st_folium(m, width=700, height=500, key="input_map")

        detected_poly = None
        if output:
            for key in ["last_active_drawing", "all_drawings"]:
                val = output.get(key)
                if val and isinstance(val, dict):
                    if "geometry" in val:
                        geom = val["geometry"]
                        if geom and geom.get("type") == "Polygon":
                            detected_poly = shape(geom)
                            break
                    if "features" in val:
                        features = val["features"]
                        if features and len(features) > 0:
                            last_feat = features[-1]
                            if last_feat and "geometry" in last_feat:
                                geom = last_feat["geometry"]
                                if geom and geom.get("type") == "Polygon":
                                    detected_poly = shape(geom)
                                    break

        if detected_poly is not None and detected_poly.is_valid:
