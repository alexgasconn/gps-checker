import streamlit as st
import gpxpy
import requests
from shapely.geometry import Point
from geopy.distance import geodesic
import pandas as pd
import pydeck as pdk

# Configuración de página
st.set_page_config(page_title="GPS Interference Checker", layout="wide")

# Sidebar
st.sidebar.title("🔍 Parámetros de análisis")
uploaded_file = st.sidebar.file_uploader("Sube tu archivo GPX", type="gpx")
radius_m = st.sidebar.slider("Distancia de búsqueda (m)", 10, 200, 50)
min_height = st.sidebar.slider("Altura mínima edificio (m)", 5, 100, 15)

# Funciones
def downsample(points, step):
    """
    Reduce la lista de puntos GPS tomando solo 1 de cada 'step' puntos.
    """
    return points[::step] if step > 1 else points


def read_gpx_points(file):
    gpx = gpxpy.parse(file)
    return [(p.latitude, p.longitude) for track in gpx.tracks
            for segment in track.segments
            for p in segment.points]


def overpass_query(lat, lon, radius_m):
    radius_deg = radius_m / 111000
    lat1, lon1 = lat - radius_deg, lon - radius_deg
    lat2, lon2 = lat + radius_deg, lon + radius_deg

    query = f"""
    [out:json][timeout:25];
    (
      way["building"]["height"]({lat1},{lon1},{lat2},{lon2});
    );
    out center;
    """
    r = requests.get("http://overpass-api.de/api/interpreter",
                     params={"data": query})
    r.raise_for_status()
    return r.json()


def buildings_near(point, buildings, radius, height_thresh):
    close = []
    for b in buildings.get("elements", []):
        if "tags" in b and "height" in b["tags"]:
            try:
                h = float(b["tags"]["height"])
                if h >= height_thresh:
                    center = b.get("center")
                    if center:
                        dist = geodesic(
                            point, (center["lat"], center["lon"])).meters
                        if dist <= radius:
                            close.append({
                                "lat": center["lat"],
                                "lon": center["lon"],
                                "height": h
                            })
            except:
                continue
    return close


# Main
if uploaded_file:
    st.title("📍 Zonas con posible interferencia GPS")
    points = read_gpx_points(uploaded_file)
    step = st.sidebar.slider("Reducir puntos (1 = sin filtro)", 1, 20, 5)
    points = downsample(points, step)


    danger_zones = []

    with st.spinner("Procesando puntos del recorrido..."):
        for i, point in enumerate(points):
            lat, lon = point
            try:
                buildings = overpass_query(lat, lon, radius_m)
                nearby = buildings_near(point, buildings, radius_m, min_height)
                if nearby:
                    danger_zones.append({
                        "index": i,
                        "lat": lat,
                        "lon": lon,
                        "num_buildings": len(nearby),
                        "buildings": nearby
                    })
            except Exception as e:
                st.warning(f"Error en punto #{i}: {e}")

    if danger_zones:
        df = pd.DataFrame([{
            "Punto": dz["index"],
            "Latitud": dz["lat"],
            "Longitud": dz["lon"],
            "Edificios Altos Cerca": dz["num_buildings"]
        } for dz in danger_zones])

        st.success(
            f"Se encontraron {len(danger_zones)} puntos con edificios altos cerca.")
        st.dataframe(df)

        # Mapa
        st.subheader("🗺️ Mapa de puntos conflictivos")
        map_df = pd.DataFrame([{
            "lat": dz["lat"],
            "lon": dz["lon"],
            "elev": dz["num_buildings"] * 5  # Para dar volumen
        } for dz in danger_zones])

        st.pydeck_chart(pdk.Deck(
            initial_view_state=pdk.ViewState(
                latitude=map_df["lat"].mean(),
                longitude=map_df["lon"].mean(),
                zoom=15,
                pitch=45,
            ),
            layers=[
                pdk.Layer(
                    "ColumnLayer",
                    data=map_df,
                    get_position='[lon, lat]',
                    get_elevation='elev',
                    elevation_scale=10,
                    radius=15,
                    get_fill_color='[200, 30, 0, 160]',
                    pickable=True,
                    auto_highlight=True,
                )
            ],
        ))
    else:
        st.info("✅ No se encontraron zonas con edificios altos cerca del recorrido.")
else:
    st.info("📂 Sube un archivo GPX para comenzar.")
