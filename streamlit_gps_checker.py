import streamlit as st
import gpxpy
import requests
from shapely.geometry import Point
from geopy.distance import geodesic
import pandas as pd
import pydeck as pdk
import time
from datetime import datetime
import altair as alt

st.set_page_config(page_title="GPS Interference & Precision Analyzer", layout="wide")

# Sidebar
st.sidebar.title("🔍 Parámetros de análisis")
uploaded_file = st.sidebar.file_uploader("Sube tu archivo GPX", type="gpx")
radius_m = st.sidebar.slider("Distancia de búsqueda (m)", 10, 200, 50)
min_height = st.sidebar.slider("Altura mínima edificio (m)", 5, 100, 15)
skip_downsample = st.sidebar.checkbox("No reducir puntos (usar todos)", value=False)
add_randomness = st.sidebar.checkbox("Añadir pequeña aleatoriedad al riesgo", value=False)
skip_weather = st.sidebar.checkbox("Omitir análisis meteorológico (más rápido)", value=True)

# Funciones
def downsample(points, step):
    return points[::step] if step > 1 else points

def read_gpx_points(file):
    gpx = gpxpy.parse(file)
    return [(p.latitude, p.longitude, p.time) for track in gpx.tracks
            for segment in track.segments
            for p in segment.points if p.time]

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
    r = requests.get("http://overpass-api.de/api/interpreter", params={"data": query})
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
                        dist = geodesic(point, (center["lat"], center["lon"])).meters
                        if dist <= radius:
                            close.append({
                                "lat": center["lat"],
                                "lon": center["lon"],
                                "height": h
                            })
            except:
                continue
    return close

def build_colored_segments(points, danger_indices):
    segments = []
    for i in range(len(points) - 1):
        lat1, lon1 = points[i][:2]
        lat2, lon2 = points[i + 1][:2]
        is_danger = i in danger_indices or i + 1 in danger_indices
        color = [200, 30, 0] if is_danger else [50, 200, 50]
        segments.append({
            "path": [[lon1, lat1], [lon2, lat2]],
            "color": color
        })
    return segments

def estimate_gps_quality(danger_ratio):
    if danger_ratio > 0.5:
        return "❌ Baja"
    elif danger_ratio > 0.2:
        return "⚠️ Media"
    else:
        return "✅ Alta"

def get_weather_data(lat, lon, dt):
    iso_time = dt.strftime('%Y-%m-%dT%H:%M')
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=cloudcover,precipitation,visibility&start={iso_time}&end={iso_time}&timezone=UTC"
    try:
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()
        clouds = data.get("hourly", {}).get("cloudcover", [None])[0]
        rain = data.get("hourly", {}).get("precipitation", [None])[0]
        vis = data.get("hourly", {}).get("visibility", [None])[0]
        return {"clouds": clouds, "precip": rain, "visibility": vis}
    except:
        return {"clouds": None, "precip": None, "visibility": None}

def compute_weather_score(clouds, precip, visibility):
    if clouds is None or precip is None or visibility is None:
        return None
    score = 100 - (clouds * 0.3 + precip * 5 + (10 - min(visibility, 10)) * 5)
    return max(0, min(100, score))

# Main
if uploaded_file:
    st.title("📍 Análisis de Precisión GPS")

    raw_points = read_gpx_points(uploaded_file)
    num_raw = len(raw_points)

    # Downsampling
    if skip_downsample:
        step = 1
    elif num_raw <= 300:
        step = 1
    elif num_raw <= 1000:
        step = 3
    elif num_raw <= 3000:
        step = 7
    else:
        step = 12

    points = downsample(raw_points, step)
    st.sidebar.markdown(f"🔢 Puntos originales: {num_raw}")
    st.sidebar.markdown(f"📉 Tras reducción: {len(points)} (cada {step} puntos)")

    danger_zones = []
    danger_indices = set()
    weather_scores = []

    progress_bar = st.progress(0, text="⏳ Analizando puntos...")
    status_text = st.empty()

    with st.spinner("Procesando puntos del recorrido..."):
        for i, (lat, lon, t) in enumerate(points):
            try:
                buildings = overpass_query(lat, lon, radius_m)
                nearby = buildings_near((lat, lon), buildings, radius_m, min_height)

                if not skip_weather:
                    weather = get_weather_data(lat, lon, t)
                    score = compute_weather_score(weather["clouds"], weather["precip"], weather["visibility"])
                    if score is not None:
                        weather_scores.append(score)
                else:
                    weather = {"clouds": None, "precip": None, "visibility": None}

                if nearby:
                    danger_zones.append({
                        "index": i,
                        "lat": lat,
                        "lon": lon,
                        "time": t,
                        "num_buildings": len(nearby),
                        "weather": weather
                    })
                    danger_indices.add(i)
            except Exception as e:
                st.warning(f"Error en punto #{i}: {e}")

            percent = int((i + 1) / len(points) * 100)
            progress_bar.progress((i + 1) / len(points), text=f"⏳ Analizando puntos... {percent}%")
            status_text.text(f"{i + 1}/{len(points)} puntos analizados")
            time.sleep(0.01)

    status_text.empty()
    progress_bar.empty()

    danger_ratio = len(danger_indices) / len(points)
    quality = estimate_gps_quality(danger_ratio)

    if weather_scores and not skip_weather:
        avg_weather_score = sum(weather_scores) / len(weather_scores)
        st.sidebar.markdown(f"🌦️ Clima estimado: {avg_weather_score:.1f}/100")

    st.subheader(f"📡 Calificación estimada de precisión GPS: {quality}")

    if danger_zones:
        df = pd.DataFrame([{**dz, **dz['weather']} for dz in danger_zones])
        df = df.drop(columns=["weather"])
        st.success(f"Se encontraron {len(danger_zones)} puntos con condiciones adversas.")
        st.dataframe(df)

        st.subheader("🗺️ Mapa de zonas peligrosas")
        map_df = pd.DataFrame([{
            "lat": dz["lat"],
            "lon": dz["lon"],
            "elev": dz["num_buildings"] * 5
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

        st.subheader("📍 Recorrido completo con color de riesgo")
        segments = build_colored_segments(points, danger_indices)
        segment_df = pd.DataFrame(segments)

        st.pydeck_chart(pdk.Deck(
            initial_view_state=pdk.ViewState(
                latitude=sum(p[0] for p in points) / len(points),
                longitude=sum(p[1] for p in points) / len(points),
                zoom=15,
                pitch=0,
            ),
            layers=[
                pdk.Layer(
                    "PathLayer",
                    data=segment_df,
                    get_path="path",
                    get_color="color",
                    width_scale=3,
                    width_min_pixels=2,
                    pickable=True,
                )
            ],
        ))

        # Gráficas
        st.subheader("📈 Calidad GPS (%) vs. Puntos del recorrido")
        quality_series = [1 if i in danger_indices else 0 for i in range(len(points))]
        df_quality = pd.DataFrame({
            "Punto": list(range(len(points))),
            "Riesgo": quality_series
        })

        st.altair_chart(
            alt.Chart(df_quality).mark_line().encode(
                x="Punto",
                y=alt.Y("Riesgo", title="Riesgo de interferencia (1 = sí)"),
            ).properties(title="Calidad GPS a lo largo del recorrido", height=200),
            use_container_width=True
        )

        st.subheader("📊 Histograma de puntos con riesgo GPS")
        st.altair_chart(
            alt.Chart(df_quality).mark_bar().encode(
                x=alt.X("Riesgo:O", title="Riesgo de interferencia"),
                y=alt.Y("count():Q", title="Número de puntos")
            ).properties(title="Distribución de calidad GPS", height=200),
            use_container_width=True
        )

    else:
        st.info("✅ No se encontraron zonas con edificios altos o clima adverso.")
else:
    st.info("📂 Sube un archivo GPX para comenzar.")
