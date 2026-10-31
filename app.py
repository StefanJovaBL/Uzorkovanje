import streamlit as st
import geopandas as gpd
from shapely.geometry import Polygon, shape
from shapely import affinity
from pyproj import CRS, Transformer
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import numpy as np

st.set_page_config(page_title="WebGIS Šema Uzorkovanja", layout="wide")

st.title("🌾 WebGIS Alat za Automatsku Šemu Uzorkovanja Tla")
st.markdown("Nacrtajte parcelu na satelitskom snimku. Aplikacija primjenjuje **negativni bafer od 10m**, pronalazi optimalnu orijentaciju i dijeli parcelu na **10 površinski identičnih zona** sa centroidima.")

# 1. Inicijalna mapa centrirana oko Banja Luke sa satelitskom podlogom
m = folium.Map(location=[44.7722, 17.1910], zoom_start=14, tiles=None)

# Satelitska podloga (Esri World Imagery)
folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Satelitska mapa',
    overlay=False,
    control=True
).add_to(m)

# Hibridne oznake
folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Nazivi i granice',
    overlay=True,
    control=True
).add_to(m)

folium.TileLayer('OpenStreetMap', name='OpenStreetMap', overlay=False, control=True).add_to(m)

# Alat za crtanje
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
output = st_folium(m, width=1000, height=500, returned_objects=["all_drawings", "last_active_drawing"])

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
        # Određivanje UTM zone
        centroid_wgs84 = poly_wgs84.centroid
        lon = centroid_wgs84.x
        lat = centroid_wgs84.y
        
        utm_zone = int((lon + 180) / 6) + 1
        hemisphere = 'north' if lat >= 0 else 'south'
        epsg_utm = 32600 + utm_zone if hemisphere == 'north' else 32700 + utm_zone
        
        crs_wgs84 = CRS.from_epsg(4326)
        crs_utm = CRS.from_epsg(epsg_utm)
        
        project_to_utm = Transformer.from_crs(crs_wgs84, crs_utm, always_xy=True).transform
        project_to_wgs84 = Transformer.from_crs(crs_utm, crs_wgs84, always_xy=True).transform
        
        from shapely.ops import transform
        poly_utm = transform(project_to_utm, poly_wgs84)
        
        orig_area_ha = poly_utm.area / 10000.0

        # Primjena negativnog bafera od 10 metara (uvlačenje granice)
        buffered_utm = poly_utm.buffer(-10)
        
        if buffered_utm.is_empty or buffered_utm.area <= 0:
            st.error("⚠️ Parcela je predata suviše mala ili uska za bafer od 10 metara. Molimo nacrtajte veću parcelu.")
        else:
            buffer_area_ha = buffered_utm.area / 10000.0
            st.success("✔ Granica uspješno kreirana i primijenjen bafer od 10m!")
            st.info(f"📊 **Izvještaj o parceli:**\n- UTM zona: **EPSG:{epsg_utm}**\n- Originalna površina: **{orig_area_ha:.2f} ha**\n- Površina nakon 10m bafera: **{buffer_area_ha:.2f} ha**")

            # Optimizacija orijentacije preko minimalnog rotiranog pravougaonika (MBR)
            mbr = buffered_utm.minimum_rotated_rectangle
            rect_coords = list(mbr.exterior.coords)
            v1 = np.array(rect_coords[1]) - np.array(rect_coords[0])
            v2 = np.array(rect_coords[2]) - np.array(rect_coords[1])
            l1 = np.linalg.norm(v1)
            l2 = np.linalg.norm(v2)
            
            # Uglovno poravnanje duže osi
            if l1 > l2:
                angle = np.degrees(np.arctan2(v1[1], v1[0]))
            else:
                angle = np.degrees(np.arctan2(v2[1], v2[0]))
            
            # Centar rotacije
            centroid_buf = buffered_utm.centroid
            
            # Rotiramo baferovani poligon da se poravna sa koordinatnim osama
            rotated_poly = affinity.rotate(buffered_utm, -angle, origin=centroid_buf)
            minx, miny, maxx, maxy = rotated_poly.bounds
            
            # Binarna pretraga za 10 površinski jednakih zona
            total_area = rotated_poly.area
            target_area = total_area / 10.0
            
            current_ymin = miny
            sub_polygons_rotated = []
            
            for i in range(9):
                low, high = current_ymin, maxy
                best_ymax = maxy
                for _ in range(25): # Visoka preciznost iteracija
                    mid = (low + high) / 2.0
                    box = Polygon([(minx - 1000, current_ymin - 1000), (maxx + 1000, current_ymin - 1000),
                                   (maxx + 1000, mid), (minx - 1000, mid)])
                    strip = rotated_poly.intersection(box)
                    if strip.area < target_area:
                        low = mid
                    else:
                        high = mid
                        best_ymax = mid
                
                box = Polygon([(minx - 1000, current_ymin - 1000), (maxx + 1000, current_ymin - 1000),
                               (maxx + 1000, best_ymax), (minx - 1000, best_ymax)])
                strip = rotated_poly.intersection(box)
                sub_polygons_rotated.append(strip)
                current_ymin = best_ymax
                
            # 10. zona (ostatak)
            box = Polygon([(minx - 1000, current_ymin - 1000), (maxx + 1000, current_ymin - 1000),
                           (maxx + 1000, maxy + 1000), (minx - 1000, maxy + 1000)])
            strip = rotated_poly.intersection(box)
            sub_polygons_rotated.append(strip)

            # Vraćanje zona i centroida u originalnu rotaciju i WGS84
            sub_polygons_wgs84 = []
            centroids_wgs84 = []
            
            for strip in sub_polygons_rotated:
                if strip.is_empty:
                    continue
                # Rotiranje nazad
                strip_orig = affinity.rotate(strip, angle, origin=centroid_buf)
                c_orig = affinity.rotate(strip.centroid, angle, origin=centroid_buf)
                
                # Transformacija u WGS84
                strip_wgs84 = transform(project_to_wgs84, strip_orig)
                c_wgs84 = transform(project_to_wgs84, c_orig)
                
                sub_polygons_wgs84.append(strip_wgs84)
                centroids_wgs84.append((c_wgs84.y, c_wgs84.x))

            # Prikaz rezultata na mapi
            st.subheader("2. Rezultat: Baferovana granica (10m unutra) i 10 jednakih zona sa centroidima")
            result_map = folium.Map(location=[lat, lon], zoom_start=15, tiles=None)
            
            folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                attr='Esri',
                name='Satelitska mapa'
            ).add_to(result_map)
            
            folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
                attr='Esri',
                name='Nazivi i granice',
                overlay=True
            ).add_to(result_map)
            
            # Originalna nacrtana granica (crvena isprekidana/puna linija)
            folium.GeoJson(
                poly_wgs84.__geo_interface__,
                style_function=lambda x: {'color': 'red', 'weight': 2, 'fillColor': 'none', 'dashArray': '5, 5'},
                tooltip="Originalna granica"
            ).add_to(result_map)
            
            # Baferovana granica (narandžasta - granica uzorkovanja)
            buffered_wgs84 = transform(project_to_wgs84, buffered_utm)
            folium.GeoJson(
                buffered_wgs84.__geo_interface__,
                style_function=lambda x: {'color': 'orange', 'weight': 2, 'fillColor': 'blue', 'fillOpacity': 0.05},
                tooltip="Baferovana granica (-10m)"
            ).add_to(result_map)
            
            # Pod-poligoni i centroidi
            colors = ['#3388ff', '#ff3333', '#33ff33', '#ffff33', '#ff33ff', '#33ffff', '#ffa500', '#800080', '#008080', '#808000']
            for idx, (p_wgs, centroid_coords) in enumerate(zip(sub_polygons_wgs84, centroids_wgs84)):
                folium.GeoJson(
                    p_wgs.__geo_interface__,
                    style_function=lambda x, i=idx: {'color': 'green', 'weight': 1, 'fillColor': colors[i % 10], 'fillOpacity': 0.3},
                    tooltip=f"Zona {idx+1}"
                ).add_to(result_map)
                
                folium.Marker(
                    location=centroid_coords,
                    popup=f"<b>Uzorak #{idx+1}</b>",
                    icon=folium.Icon(color="red", icon="info-sign")
                ).add_to(result_map)

            folium.LayerControl().add_to(result_map)
            st_folium(result_map, width=1000, height=500, key="result_map")
else:
    st.info("💡 Koristite alat za crtanje (ikonica poligona u gornjem lijevom uglu mape) da ocrtate granice parcele.")
