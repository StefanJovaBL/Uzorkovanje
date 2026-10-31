import streamlit as st
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely import affinity
from pyproj import CRS, Transformer
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import numpy as np
import json

st.set_page_config(page_title="WebGIS Šema Uzorkovanja", layout="wide")

st.title("🌾 WebGIS Alat za Automatsku Šemu Uzorkovanja Tla")
st.markdown("Nacrtajte parcelu na satelitskom snimku ili učitajte GeoJSON fajl, a zatim kliknite dugme za proračun. Aplikacija primjenjuje **negativni bafer od 10m**, optimizuje orijentaciju i dijeli parcelu na **tačno 10 zona** sa centroidima.")

# Inicijalizacija memorije
if "drawn_polygon" not in st.session_state:
    st.session_state.drawn_polygon = None

# Dugme za resetovanje
if st.session_state.drawn_polygon is not None:
    if st.button("🔄 Poništi i unesi novu parcelu"):
        st.session_state.drawn_polygon = None
        st.rerun()

poly_wgs84 = st.session_state.drawn_polygon

if poly_wgs84 is None:
    input_mode = st.radio("Izaberite način unosa parcele:", ["✍️ Nacrtaj na mapi", "📁 Učitaj GeoJSON fajl"])
    
    if input_mode == "📁 Učitaj GeoJSON fajl":
        uploaded_file = st.file_uploader("Učitajte fajl granice parcele:", type=["geojson", "json"])
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
        m = folium.Map(location=[44.7722, 17.1910], zoom_start=14, tiles=None)

        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Satelitska mapa',
            overlay=False,
            control=True
        ).add_to(m)

        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Nazivi i granice',
            overlay=True,
            control=True
        ).add_to(m)

        folium.TileLayer('OpenStreetMap', name='OpenStreetMap', overlay=False, control=True).add_to(m)

        draw = Draw(
            export=False,
            position='topleft',
            draw_options={'polyline': False, 'rectangle': False, 'circle': False, 'marker': False, 'circlemarker': False, 'polygon': True},
            edit_options={'edit': True}
        )
        draw.add_to(m)
        folium.LayerControl().add_to(m)

        st.subheader("Nacrtajte granicu parcele klikom na mapu:")
        output = st_folium(m, width=1000, height=500, returned_objects=["all_drawings", "last_active_drawing"], key="input_map")

        detected_poly = None
        if output:
            active = output.get("last_active_drawing")
            if active and "geometry" in active:
                geom = active["geometry"]
                if geom and geom.get("type") == "Polygon":
                    detected_poly = shape(geom)
            
            if detected_poly is None:
                drawings = output.get("all_drawings")
                if drawings and "features" in drawings and len(drawings["features"]) > 0:
                    feat = drawings["features"][-1]
                    if feat and "geometry" in feat:
                        geom = feat["geometry"]
                        if geom and geom.get("type") == "Polygon":
                            detected_poly = shape(geom)

        if detected_poly is not None and detected_poly.is_valid:
            st.success("✔ Parcela je uspješno nacrtana na mapi!")
            if st.button("🚀 Pokreni analizu i izračunaj tačke uzorkovanja"):
                st.session_state.drawn_polygon = detected_poly
                st.rerun()
        else:
            st.info("💡 Kliknite na ikonicu poligona u gornjem lijevom uglu mape da nacrtate granicu parcele.")

if st.session_state.drawn_polygon is not None:
    poly_wgs84 = st.session_state.drawn_polygon
    
    centroid_wgs84 = poly_wgs84.centroid
    lon = centroid_wgs84.x
    lat = centroid_wgs84.y
    
    utm_zone = int((lon + 180) / 6) + 1
    hemisphere = 'north' if lat >= 0 else 'south'
    epsg_utm = 32600 + utm_zone if hemisphere == 'north' else 32700 + utm_zone
    
    crs_wgs84 = CRS.from_epsg(4326)
    crs_utm = CRS.from_epsg(epsg_utm)
    
    project_to_utm = Transformer.from_crs(crs_wgs84, crs_utm, always_xy=True).transform
    project_to_wgs84 = Transformer.from_crs
