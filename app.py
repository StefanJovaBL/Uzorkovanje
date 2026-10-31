import streamlit as st
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
from pyproj import CRS, Transformer
import folium
from streamlit_folium import st_folium
import json

st.set_page_config(page_title="WebGIS Šema Uzorkovanja", layout="wide")

st.title("🌾 WebGIS Alat za Automatsku Šemu Uzorkovanja Tla")
st.markdown("Učitajte GeoJSON fajl sa granicom parcele, a aplikacija će automatski izračunati površinu, prebaciti koordinate u UTM metarski sistem, podijeliti je na 10 jednakih dijelova i izračunati centroide.")

uploaded_file = st.file_uploader("1. Učitajte granicu parcele (GeoJSON fajl):", type=["geojson", "json"])

if uploaded_file is not None:
    try:
        # Čitanje fajla direktno preko geopandas-a (najstabilniji način za sve tipove GeoJSON-a)
        gdf = gpd.read_file(uploaded_file)
        
        if gdf.empty:
            st.error("⚠️ Učitani fajl je prazan.")
        else:
            # Uzimamo prvu geometriju iz fajla i osiguravamo da je u WGS84 (EPSG:4326)
            if gdf.crs is not None and gdf.crs != "EPSG:4326":
                gdf = gdf.to_crs("EPSG:4326")
                
            geom = gdf.geometry.iloc[0]
            
            # Ako je MultiPolygon, uzimamo najveći dio ili prvi poligon
            if isinstance(geom, MultiPolygon):
                poly_wgs84 = max(geom.geoms, key=lambda a: a.area)
            elif isinstance(geom, Polygon):
                poly_wgs84 = geom
            else:
                poly_wgs84 = None
                
            if poly_wgs84 is None or not poly_wgs84.is_valid:
                st.error("⚠️ Geometrija u fajlu nije validan poligon.")
            else:
                st.success("✔ Granica parcele je uspješno učitana i prepoznata!")
                
                # Određivanje UTM zone
                centroid_wgs84 = poly_wgs84.centroid
                lon = centroid_wgs84.x
                lat = centroid_wgs84.y
                
                utm_zone = int((lon + 180) / 6) + 1
                hemisphere = 'north' if lat >= 0 else 'south'
                epsg_utm = 32600 + utm_zone if hemisphere == 'north' else 32700 + utm_zone
                
                # Transformacija u UTM (metarski sistem)
                crs_wgs84 = CRS.from_epsg(4326)
                crs_utm = CRS.from_epsg(epsg_utm)
                
                project_to_utm = Transformer.from_crs(crs_wgs84, crs_utm, always_xy=True).transform
                project_to_wgs84 = Transformer.from_crs(crs_utm, crs_wgs84, always_xy=True).transform
                
                from shapely.ops import transform
                poly_utm = transform(project_to_utm, poly_wgs84)
                
                area_m2 = poly_utm.area
                area_ha = area_m2 / 10000.0
                
                st.info(f"📊 **Izvještaj o parceli:**\n- UTM zona: **EPSG:{epsg_utm}**\n- Ukupna površina: **{area_m2:,.2f} m²** ({area_ha:.2f} ha)")
                
                # Podjela na 10 jednakih traka po Y osi
                minx, miny, maxx, maxy = poly_utm.bounds
                total_height = maxy - miny
                step = total_height / 10.0
                
                sub_polygons_wgs84 = []
                centroids_wgs84 = []
                
                current_ymin = miny
                for i in range(10):
                    current_ymax = current_ymin + step
                    box_polygon = Polygon([(minx - 1000, current_ymin), (maxx + 1000, current_ymin), 
                                           (maxx + 1000, current_ymax), (minx - 1000, current_ymax)])
                    
                    intersection = poly_utm.intersection(box_polygon)
                    
                    if not intersection.is_empty:
                        geoms = [intersection] if intersection.geom_type == 'Polygon' else list(intersection.geoms)
                        for g in geoms:
                            if g.area > 1.0:
                                g_wgs84 = transform(project_to_wgs84, g)
                                sub_polygons_wgs84.append(g_wgs84)
                                
                                c_utm = g.centroid
                                c_wgs84 = transform(project_to_wgs84, c_utm)
                                centroids_wgs84.append((c_wgs84.y, c_wgs84.x))
                                
                    current_ymin = current_ymax

                # Prikaz na mapi
                st.subheader("2. Rezultat: Granica parcele i tačke uzorkovanja")
                result_map = folium.Map(location=[lat, lon], zoom_start=15)
                folium.TileLayer('CartoDB positron', name="Light Map").add_to(result_map)
                
                # Originalna granica
                folium.GeoJson(
                    poly_wgs84.__geo_interface__,
                    style_function=lambda x: {'color': 'red', 'weight': 3, 'fillColor': 'blue', 'fillOpacity': 0.1},
                    tooltip="Granica parcele"
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

                st_folium(result_map, width=1000, height=600)
    except Exception as e:
        st.error(f"Greška pri čitanju fajla: {e}")
else:
    st.info("💡 Savjet: Granicu parcele možete besplatno nacrtati i preuzeti kao GeoJSON fajl sa stranice **geojson.io**, a zatim je ovdje učitati.")
