import streamlit as st
import geopandas as gpd
from shapely.geometry import Polygon, LineString
from pyproj import CRS, Transformer
import folium
from streamlit_folium import st_folium
from streamlit_drawable_geojson import st_drawable_geojson

# Podešavanje stranice
st.set_page_config(page_title="WebGIS Šema Uzorkovanja", layout="wide")

st.title("🌾 WebGIS Alat za Automatsku Šemu Uzorkovanja Tla")
st.markdown("Nacrtajte parcelu na mapi ispod, a aplikacija će automatski izračunati površinu, prebaciti koordinate u UTM metarski sistem, podijeliti je na 10 jednakih dijelova i izračunati centroide.")

# 1. Inicijalna mapa (Centrirana oko Banja Luke / regije)
m = folium.Map(location=[44.7722, 17.1910], zoom_start=14)
folium.TileLayer('CartoDB positron').add_to(m)

# Dodavanje alata za crtanje poligona direktno na mapi
# Koristimo streamlit-drawable-geojson za unos konture
st.subheader("1. Nacrtajte granicu parcele na mapi:")
drawing_mode = "polygon"

# Prikaz interaktivne mape sa opcijom crtanja
drawn_data = st_drawable_geojson(
    m,
    drawing_modes=[drawing_mode],
    key="canvas"
)

if drawn_data and drawn_data["features"]:
    # Uzimamo posljednji nacrtani poligon
    latest_feature = drawn_data["features"][-1]
    geom_type = latest_feature["geometry"]["type"]
    coords = latest_feature["geometry"]["coordinates"]

    if geom_type == "Polygon":
        # 2. Provjera da li je kontura zatvorena i kreiranje Shapely poligona
        ring = coords[0]
        if ring[0] != ring[-1]:
            # Automatsko zatvaranje ako nije zatvoreno
            ring.append(ring[0])
            
        poly_wgs84 = Polygon(ring)
        
        # Provjera validnosti konture
        if not poly_wgs84.is_valid or len(ring) < 4:
            st.error("⚠️ Nacrtana kontura nije validan zatvoreni poligon. Molimo nacrtajte ponovo.")
        else:
            st.success("✔ Kontura parcele je uspešno zatvorena!")

            # 3. Određivanje odgovarajuće UTM zone na osnovu geografske dužine (WGS84)
            # Uzimamo centar parcele da odredimo zonu
            centroid_wgs84 = poly_wgs84.centroid
            lon = centroid_wgs84.x
            lat = centroid_wgs84.y
            
            utm_zone = int((lon + 180) / 6) + 1
            hemisphere = 'north' if lat >= 0 else 'south'
            
            # Formiranje EPSG koda za UTM (npr. EPSG za WGS 84 / UTM zone)
            epsg_utm = 32600 + utm_zone if hemisphere == 'north' else 32700 + utm_zone
            
            # 4. Transformacija iz WGS84 (EPSG:4326) u lokalni UTM (metarski sistem)
            crs_wgs84 = CRS.from_epsg(4326)
            crs_utm = CRS.from_epsg(epsg_utm)
            
            project_to_utm = Transformer.from_crs(crs_wgs84, crs_utm, always_xy=True).transform
            project_to_wgs84 = Transformer.from_crs(crs_utm, crs_wgs84, always_xy=True).transform
            
            from shapely.ops import transform
            poly_utm = transform(project_to_utm, poly_wgs84)
            
            # Proračun površine u metrima kvadratnim i hektarima
            area_m2 = poly_utm.area
            area_ha = area_m2 / 10000.0
            
            st.info(detalji := f"📊 **Izvještaj o parceli:**\n- Detektovana UTM zona: **EPSG:{epsg_utm}**\n- Ukupna površina: **{area_m2:,.2f} m²** ({area_ha:.2f} ha)")

            # 5. Podjela parcele na 10 površinski jednakih poligona (horizontalnim rezovima / trakama)
            # Koristimo aproksimaciju dijeljenja po X ili Y osi u UTM sistemu
            minx, miny, maxx, maxy = poly_utm.bounds
            total_height = maxy - miny
            
            sub_polygons_wgs84 = []
            centroids_wgs84 = []
            
            # Dijelimo opseg po Y osi na 10 jednakih dijelova
            step = total_height / 10.0
            
            current_ymin = miny
            for i in range(10):
                current_ymax = current_ymin + step
                # Kreiramo horizontalnu traku (Bounding box trake)
                box_polygon = Polygon([(minx - 1000, current_ymin), (maxx + 1000, current_ymin), 
                                       (maxx + 1000, current_ymax), (minx - 1000, current_ymax)])
                
                # Sječemo traku sa originalnim UTM poligonom
                intersection = poly_utm.intersection(box_polygon)
                
                if not intersection.is_empty:
                    # Ako je presjek multigeometrija ili poligon
                    if intersection.geom_type == 'Polygon':
                        geoms = [intersection]
                    else:
                        geoms = list(intersection.geoms)
                        
                    for g in geoms:
                        if g.area > 1.0: # Zanemarujemo mikro ostatke
                            # Vraćamo natrag u WGS84 za prikaz na mapi
                            g_wgs84 = transform(project_to_wgs84, g)
                            sub_polygons_wgs84.append(g_wgs84)
                            
                            # 6. Pronalaženje centroida svakog dijela
                            c_utm = g.centroid
                            c_wgs84 = transform(project_to_wgs84, c_utm)
                            centroids_wgs84.append((c_wgs84.y, c_wgs84.x)) # (lat, lon)
                            
                current_ymin = current_ymax

            # 7. Vizuelni prikaz rezultata na mapi
            st.subheader("2. Rezultat: Granica parcele i tačke uzorkovanja (centroidi)")
            
            result_map = folium.Map(location=[centroid_wgs84.y, centroid_wgs84.x], zoom_start=15)
            folium.TileLayer('CartoDB positron', name="Light Map").add_to(result_map)
            folium.TileLayer('OpenStreetMap', name="OSM").add_to(result_map)
            
            # Prikaz granice originalne parcele (crvena linija)
            folium.GeoJson(
                poly_wgs84.__geo_interface__,
                style_function=lambda x: {'color': 'red', 'weight': 3, 'fillColor': 'blue', 'fillOpacity': 0.1},
                tooltip="Granica parcele"
            ).add_to(result_map)
            
            # Prikaz podijeljenih zona i njihovih centroida
            for idx, (p_wgs, centroid_coords) in enumerate(zip(sub_polygons_wgs84, centroids_wgs84)):
                # Prikaz pod-poligona
                folium.GeoJson(
                    p_wgs.__geo_interface__,
                    style_function=lambda x, i=idx: {
                        'color': 'green', 
                        'weight': 1, 
                        'fillColor': ['#3388ff', '#ff3333', '#33ff33', '#ffff33', '#ff33ff', '#33ffff', '#ffa500', '#800080', '#008080', '#808000'][i % 10], 
                        'fillOpacity': 0.3
                    },
                    tooltip=f"Zona {idx+1}"
                ).add_to(result_map)
                
                # Dodavanje tačke centroida (mjesto uzorkovanja)
                folium.Marker(
                    location=centroid_coords,
                    popup=f"<b>Uzorak #{idx+1}</b>",
                    icon=folium.Icon(color="red", icon="info-sign")
                ).add_to(result_map)

            folium.LayerControl().add_to(result_map)
            st_folium(result_map, width=1000, height=600)
            
    else:
        st.warning("Molimo nacrtajte zatvoreni poligon, a ne liniju ili tačku.")
else:
    st.info("💡 Koristite alat za crtanje (poligon) na gornjoj mapi da ocrtate granice svoje parcele.")
