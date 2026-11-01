import streamlit as st
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely.ops import transform
from shapely import affinity
from pyproj import CRS, Transformer
import folium
from folium.plugins import Draw
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
            st.session_state.drawn_polygon = detected_poly
            st.rerun()
        else:
            st.info("💡 Kliknite na ikonicu poligona u gornjem lijevom uglu mape i nacrtajte granicu parcele.")

if st.session_state.drawn_polygon is not None:
    try:
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
        project_to_wgs84 = Transformer.from_crs(crs_utm, crs_wgs84, always_xy=True).transform
        
        poly_utm = transform(project_to_utm, poly_wgs84)
        orig_area_ha = poly_utm.area / 10000.0

        if poly_utm.is_empty or poly_utm.area <= 0:
            st.error("⚠️ Unijeti poligon nije validan u UTM projekciji.")
            if st.button("Pokušaj ponovo"):
                st.session_state.drawn_polygon = None
                st.rerun()
        else:
            st.success("✔ Granica uspješno obrađena!")
            st.info(f"📊 **Izvještaj o parceli:** | UTM zona: **EPSG:{epsg_utm}** | Površina parcele: **{orig_area_ha:.2f} ha**")

            mbr = poly_utm.minimum_rotated_rectangle
            rect_coords = list(mbr.exterior.coords)
            v1 = np.array(rect_coords[1]) - np.array(rect_coords[0])
            v2 = np.array(rect_coords[2]) - np.array(rect_coords[1])
            l1 = np.linalg.norm(v1)
            l2 = np.linalg.norm(v2)
            
            if l1 > l2:
                angle = np.degrees(np.arctan2(v1[1], v1[0]))
            else:
                angle = np.degrees(np.arctan2(v2[1], v2[0]))
            
            angle += 45
            
            centroid_buf = poly_utm.centroid
            rotated_poly = affinity.rotate(poly_utm, -angle, origin=centroid_buf)
            minx, miny, maxx, maxy = rotated_poly.bounds
            
            total_area = rotated_poly.area
            target_third_area = total_area / 3.0
            
            low, high = miny, maxy
            y_mid1 = maxy
            for _ in range(40):
                mid = (low + high) / 2.0
                box = Polygon([(minx - 1000, miny - 1000), (maxx + 1000, miny - 1000), (maxx + 1000, mid), (minx - 1000, mid)])
                area = rotated_poly.intersection(box).area
                if area < target_third_area:
                    low = mid
                else:
                    high = mid
                    y_mid1 = mid

            low, high = y_mid1, maxy
            y_mid2 = maxy
            target_two_thirds = target_third_area * 2.0
            for _ in range(40):
                mid = (low + high) / 2.0
                box = Polygon([(minx - 1000, miny - 1000), (maxx + 1000, miny - 1000), (maxx + 1000, mid), (minx - 1000, mid)])
                area = rotated_poly.intersection(box).area
                if area < target_two_thirds:
                    low = mid
                else:
                    high = mid
                    y_mid2 = mid
            
            box_bottom = Polygon([(minx - 1000, miny - 1000), (maxx + 1000, miny - 1000), (maxx + 1000, y_mid1), (minx - 1000, y_mid1)])
            poly_bottom = rotated_poly.intersection(box_bottom)

            box_middle = Polygon([(minx - 1000, y_mid1), (maxx + 1000, y_mid1), (maxx + 1000, y_mid2), (minx - 1000, y_mid2)])
            poly_middle = rotated_poly.intersection(box_middle)

            box_top = Polygon([(minx - 1000, y_mid2), (maxx + 1000, y_mid2), (maxx + 1000, maxy + 1000), (minx - 1000, maxy + 1000)])
            poly_top = rotated_poly.intersection(box_top)

            sub_polygons_rotated = []

            def split_into_columns(region_poly, r_minx, r_maxx, r_miny, r_maxy):
                cols = []
                if region_poly.is_empty:
                    return cols
                target_col_area = region_poly.area / 5.0
                x_cursor = r_minx
                for j in range(4):
                    low_x, high_x = x_cursor, r_maxx
                    best_x = r_maxx
                    for _ in range(30):
                        mid_x = (low_x + high_x) / 2.0
                        vbox = Polygon([(x_cursor, r_miny - 1000), (mid_x, r_miny - 1000), (mid_x, r_maxy + 1000), (x_cursor, r_maxy + 1000)])
                        area = region_poly.intersection(vbox).area
                        if area < target_col_area:
                            low_x = mid_x
                        else:
                            high_x = mid_x
                            best_x = mid_x
                    
                    vbox = Polygon([(x_cursor, r_miny - 1000), (best_x, r_miny - 1000), (best_x, r_maxy + 1000), (x_cursor, r_maxy + 1000)])
                    col_part = region_poly.intersection(vbox)
                    if not col_part.is_empty:
                        cols.append(col_part)
                    x_cursor = best_x
                
                vbox = Polygon([(x_cursor, r_miny - 1000), (r_maxx + 1000, r_miny - 1000), (r_maxx + 1000, r_maxy + 1000), (x_cursor, r_maxy + 1000)])
                col_part = region_poly.intersection(vbox)
                if not col_part.is_empty:
                    cols.append(col_part)
                return cols

            sub_polygons_rotated.extend(split_into_columns(poly_bottom, minx, maxx, miny, y_mid1))
            sub_polygons_rotated.extend(split_into_columns(poly_middle, minx, maxx, y_mid1, y_mid2))
            sub_polygons_rotated.extend(split_into_columns(poly_top, minx, maxx, y_mid2, maxy))

            sub_polygons_wgs84 = []
            centroids_wgs84 = []
            
            for strip in sub_polygons_rotated:
                if strip.is_empty:
                    continue
                strip_orig = affinity.rotate(strip, angle, origin=centroid_buf)
                
                if isinstance(strip_orig, MultiPolygon):
                    largest_part = max(strip_orig.geoms, key=lambda p: p.area)
                    c_local = largest_part.centroid
                else:
                    c_local = strip_orig.centroid
                
                strip_wgs84 = transform(project_to_wgs84, strip_orig)
                c_wgs84 = transform(project_to_wgs84, c_local)
                
                sub_polygons_wgs84.append(strip_wgs84)
                centroids_wgs84.append((c_wgs84.y, c_wgs84.x))

            st.subheader(f"2. Rezultat: Ukupno {len(centroids_wgs84)} tačaka uzorkovanja (3 reda × 5 kolona)")
            
            result_map = folium.Map(location=[lat, lon], zoom_start=16)
            
            folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Satelitska mapa', show=True).add_to(result_map)
            folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Nazivi i granice', overlay=True).add_to(result_map)
            
            folium.GeoJson(poly_wgs84.__geo_interface__, style_function=lambda x: {'color': 'red', 'weight': 2, 'fillColor': 'none', 'dashArray': '5, 5'}, tooltip="Originalna granica").add_to(result_map)
            
            colors = ['#3388ff', '#ff3333', '#33ff33', '#ffff33', '#ff33ff', '#33ffff', '#ffa500', '#800080', '#008080', '#808000', '#ff66b2', '#9933ff', '#009933', '#ff9900', '#666666']
            for idx, p_wgs in enumerate(sub_polygons_wgs84):
                color_code = colors[idx % len(colors)]
                folium.GeoJson(p_wgs.__geo_interface__, style_function=lambda x, col=color_code: {'color': 'green', 'weight': 1, 'fillColor': col, 'fillOpacity': 0.3}, tooltip=f"Zona {idx+1}").add_to(result_map)
                
            for idx, centroid_coords in enumerate(centroids_wgs84):
                folium.Marker(location=centroid_coords, popup=f"<b>Uzorak #{idx+1}</b>", icon=folium.Icon(color="red", icon="info-sign")).add_to(result_map)

            folium.LayerControl().add_to(result_map)
            st_folium(result_map, width=700, height=500, key="result_map")
            
    except Exception as e:
        st.error(f"⚠️ Došlo je do greške u obradi geometrije: {e}")
        if st.button("Pokušaj ponovo sa drugom parcelom"):
            st.session_state.drawn_polygon = None
            st.rerun()
