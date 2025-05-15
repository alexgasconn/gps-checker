import streamlit as st
import gpxpy
import requests
from shapely.geometry import Point
from geopy.distance import geodesic
import pandas as pd
import pydeck as pdk

st.set_page_config(page_title="GPS Interference Checker", layout="wide")

# Sidebar
st.sidebar.title("🔍 Parámetros de análisis")
uploaded_file = st.sidebar.file_uploader("Sube tu archivo GPX", type="gpx")
radius_m = st.sidebar.slider("Distancia de búsqueda (m)", 10, 200, 50)
min_height = st.sidebar.slider("Altura mínima edificio (m)", 5, 100, 15)

# Funciones
def downsample(points, step):
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
        lat1, lon1 = points[i]
        lat2, lon2 = points[i + 1]
        is_danger = i in danger_indices or i + 1 in danger_indices
        color = [200, 30, 0] if is_danger else [50, 200, 50]
        segments.append({
            "path": [[lon1, lat1], [lon2, lat2]],
            "color": color
        })
    return segments

import time  # al principio del archivo

if uploaded_file:
    st.title("📍 Zonas con posible interferencia GPS")

    raw_points = read_gpx_points(uploaded_file)
    num_raw = len(raw_points)

    # Downsampling más agresivo
    if num_raw <= 300:
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
    total_points = len(points)

    progress_bar = st.progress(0, text="⏳ Analizando puntos...")
    status_text = st.empty()

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
                    danger_indices.add(i)
            except Exception as e:
                st.warning(f"Error en punto #{i}: {e}")

            percent = int((i + 1) / total_points * 100)
            progress_bar.progress((i + 1) / total_points, text=f"⏳ Analizando puntos... {percent}%")
            status_text.text(f"{i+1}/{total_points} puntos analizados")
            time.sleep(0.1)  # suaviza carga y evita abuso de API

    status_text.empty()
    progress_bar.empty()

else:
    st.info("📂 Sube un archivo GPX para comenzar.")
