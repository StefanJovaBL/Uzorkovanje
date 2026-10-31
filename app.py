import streamlit as st
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely import affinity
from pyproj import CRS, Transformer
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import numpy as np

st.set_page_config(page_title="WebGIS Šema Uzorkovanja", layout="wide")

st.title("🌾 WebGIS Alat za Automatsku Šemu Uzorkovanja Tla")
st.markdown("Nacrtajte parcelu na satelitskom snimku. Aplikacija primjenjuje **negativni bafer od 10m**, optimizuje orijentaciju i dijeli uvučenu parcelu na **tačno 10 površinski identičnih zona** sa svojim centroidima.")

# Inicijalizacija memorije u Streamlitu da se crtež ne gubi pri osvežavanju
if "drawn_polygon" not in st.session_state:
    st.session_state.drawn_polygon = None

# Dugme za resetovanje ako želite da nacrtate novu parcelu
if st.session_state.drawn_polygon is not None:
    if st.button("🔄 Nacrtaj novu parcelu"):
        st.session_state.drawn_polygon = None
        st.rerun()

if st.session_state.drawn_polygon is None:
    # 1. Inicijalna mapa za crtanje
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
        draw_options={
            'polyline': False,
            'rectangle': False,
            'circle': False,
            'marker': False,
            'circlemarker': False,
            'polygon': True
        },
        edit_options={'edit': True}
    )
    draw.add_to(m)
    folium.LayerControl().add_to(m)

    st.subheader("1. Nacrtajte granicu parcele na satelitskom snimku:")
    output = st_folium(m, width=1000, height=500, key="input_map")

    poly_wgs84 = None
    if output and output.get("last_active_drawing"):
        last_geom = output["last_active_drawing"]["geometry"]
        if last_geom["type"] == "Polygon":
            poly_wgs84 = shape(last_geom)

    if poly_wgs84 is None and output and output.get("all_drawings"):
        drawings = output["all_drawings"]
        if drawings and "features" in drawings and len(drawings["features"]) > 0:
            last_feat = drawings["features"][-1]
            if last_feat["geometry"]["type"] == "Polygon":
                poly_wgs84 = shape(last_feat)

    if poly_wgs84 is not None:
        if not poly_wgs84.is_valid:
            st.error("⚠️ Nacrtana kontura nije validan poligon. Molimo nacrtajte ponovo.")
        else:
            st.session_state.drawn_polygon = poly_wgs84
            st.rerun()
    else:
        st.info("💡 Koristite alat za crtanje (ikonica poligona u gornjem lijevom uglu mape) da ocrtate granice parcele.")

# Ako je poligon saču
