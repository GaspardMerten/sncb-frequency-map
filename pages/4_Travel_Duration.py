"""Travel Duration page.

Shows travel time from every station to selected destination(s).
Supports multiple destinations: one map per destination + an average map.
"""

import pandas as pd
import folium
import streamlit as st
from streamlit_folium import st_folium

from logic.shared import CUSTOM_CSS, render_sidebar_filters, load_all_data, render_footer
from logic.geo import build_region_geojson, get_province, PROVINCE_TO_REGION
from logic.reachability import compute_reachability_single, compute_reachability_to_dest
from logic.rendering import make_step_colormap, render_reach_choropleth, duration_color

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="sidebar-section">View</p>', unsafe_allow_html=True)
    view_mode = st.radio("Display", ["Stations", "Provinces", "Regions"],
                         label_visibility="collapsed", horizontal=True)
    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Duration settings</p>', unsafe_allow_html=True)
    direction = st.radio("Direction", ["To destination", "From destination"],
                         horizontal=True,
                         help="**To destination**: how long from each station to reach the selected station. "
                              "**From destination**: how far you can go from the selected station.")
    max_hours = st.number_input("Time budget (hours)", min_value=0.5, max_value=6.0,
                                value=3.0, step=0.5, format="%.1f")
    departure_window = st.slider("Departure window", 0, 24, (7, 9), step=1)
    transfer_penalty = st.slider("Min transfer time (min)", 0, 15, 5)
    max_transfers = st.slider("Max transfers", 0, 5, 3)

filters = render_sidebar_filters()
data = load_all_data(filters)

station_departures = data["station_departures"]
reverse_departures = data["reverse_departures"]
stop_lookup = data["stop_lookup"]

# ── Destination selector (multi) ─────────────────────────────────────────────

name_to_id: dict[str, str] = {}
for sid, info in stop_lookup.items():
    if info["name"] not in name_to_id:
        name_to_id[info["name"]] = sid
station_name_list = sorted(name_to_id.keys())

# Find default (Bruxelles-Central)
default_names = []
for name in station_name_list:
    if "Central" in name and "Bruxelles" in name:
        default_names.append(name)
        break

destination_names = st.multiselect(
    "Destination station(s)", station_name_list,
    default=default_names,
)
if not destination_names:
    st.warning("Select at least one destination.")
    st.stop()

destination_ids = [name_to_id[n] for n in destination_names]

# ── Compute travel times ─────────────────────────────────────────────────────

@st.cache_data(show_spinner="Computing travel durations...", ttl=3600)
def _cached_durations_from(dest_id, _departures, max_hours, departure_window,
                           transfer_penalty, max_transfers):
    return compute_reachability_single(
        dest_id, _departures, max_hours * 60,
        max_transfers=max_transfers,
        transfer_penalty_min=transfer_penalty,
        departure_window=departure_window,
    )


@st.cache_data(show_spinner="Computing travel durations...", ttl=3600)
def _cached_durations_to(dest_id, _reverse_departures, max_hours, arrival_window,
                         transfer_penalty, max_transfers):
    return compute_reachability_to_dest(
        dest_id, _reverse_departures, max_hours * 60,
        max_transfers=max_transfers,
        transfer_penalty_min=transfer_penalty,
        arrival_window=arrival_window,
    )


# Compute for each destination
all_reachable = {}
for dest_id in destination_ids:
    if direction == "To destination":
        all_reachable[dest_id] = _cached_durations_to(
            dest_id, reverse_departures, max_hours,
            departure_window, transfer_penalty, max_transfers,
        )
    else:
        all_reachable[dest_id] = _cached_durations_from(
            dest_id, station_departures, max_hours,
            departure_window, transfer_penalty, max_transfers,
        )


def _station_base(sid, info):
    """Build common station fields for duration DataFrames."""
    province = get_province(info["lat"], info["lon"], data["prov_geo"])
    region = PROVINCE_TO_REGION.get(province, "Unknown") if province else "Unknown"
    return {
        "station_id": sid, "station_name": info["name"],
        "lat": info["lat"], "lon": info["lon"],
        "province": province or "Unknown", "region": region,
    }


def _build_duration_df(reachable, dest_id):
    """Build DataFrame for one destination."""
    rows = []
    for sid, info in stop_lookup.items():
        if sid == dest_id:
            tt, tr = 0.0, 0
        elif sid in reachable:
            tt = reachable[sid]["travel_time"]
            tr = reachable[sid]["transfers"]
        else:
            tt, tr = None, None
        rows.append({**_station_base(sid, info), "travel_time": tt, "transfers": tr})
    return pd.DataFrame(rows)


def _build_average_df():
    """Build DataFrame averaging travel times across all destinations."""
    rows = []
    for sid, info in stop_lookup.items():
        times = []
        transfers_list = []
        for dest_id in destination_ids:
            if sid == dest_id:
                times.append(0.0)
                transfers_list.append(0)
            elif sid in all_reachable[dest_id]:
                times.append(all_reachable[dest_id][sid]["travel_time"])
                transfers_list.append(all_reachable[dest_id][sid]["transfers"])

        avg_time = sum(times) / len(times) if times else None
        avg_transfers = sum(transfers_list) / len(transfers_list) if transfers_list else None
        rows.append({**_station_base(sid, info), "travel_time": avg_time, "transfers": avg_transfers})
    return pd.DataFrame(rows)


# ── Station map rendering ────────────────────────────────────────────────────


def _render_station_map(df, dest_name, max_time, key_suffix):
    """Render a station-level duration map."""
    df_ok = df[df["travel_time"].notna()]
    df_na = df[df["travel_time"].isna()]

    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    for _, row in df_na.iterrows():
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=3, color="#ccc", fill=True, fill_color="#ccc",
            fill_opacity=0.5, weight=0.5,
            tooltip=f"<b>{row['station_name']}</b><br/>Not reachable",
        ).add_to(m)

    for _, row in df_ok.iterrows():
        t = row["travel_time"]
        ratio = t / max_time if max_time > 0 else 0
        radius = 4 + 10 * (1 - ratio)
        color = duration_color(t, max_time)

        is_dest = (dest_name and row["station_name"] == dest_name)
        if is_dest:
            color = "#e31a1c"
            radius = 14
            tip = f"<b>{row['station_name']}</b><br/>DESTINATION"
        else:
            tr = row.get("transfers")
            tr_str = f"<br/>Transfers: {tr:.1f}" if tr is not None else ""
            tip = f"<b>{row['station_name']}</b><br/>Travel: {t:.0f} min{tr_str}"

        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius, color=color, fill=True, fill_color=color,
            fill_opacity=0.85, weight=1.5,
            tooltip=tip,
        ).add_to(m)

    st_folium(m, use_container_width=True, height=500, key=f"dur_{key_suffix}")


def _render_province_view(df, dest_label):
    df_ok = df[df["travel_time"].notna()]
    if df_ok.empty:
        st.warning("No reachable stations.")
        return
    prov_agg = df_ok.groupby("province").agg(
        avg_time=("travel_time", "mean"),
        station_count=("station_id", "count"),
    ).round(1).sort_values("avg_time")

    prov_totals = prov_agg["avg_time"].to_dict()
    prov_vals = [v for v in prov_totals.values() if v > 0]
    if prov_vals:
        pcmap = make_step_colormap(prov_vals, f"Avg travel time (min) to {dest_label}")
        pm = render_reach_choropleth(
            data["prov_geo"]["features"], prov_totals, pcmap, "name",
            lambda n, t: f"{n}: {t:.0f} min avg",
        )
        st_folium(pm, use_container_width=True, height=500, key=f"dur_prov_{dest_label}")
    st.dataframe(prov_agg, use_container_width=True)


def _render_region_view(df, dest_label):
    df_ok = df[df["travel_time"].notna()]
    if df_ok.empty:
        st.warning("No reachable stations.")
        return
    region_agg = df_ok.groupby("region").agg(
        avg_time=("travel_time", "mean"),
        station_count=("station_id", "count"),
    ).round(1).sort_values("avg_time")

    rc1, rc2, rc3 = st.columns(3)
    for col, reg in zip([rc1, rc2, rc3], ["Brussels", "Flanders", "Wallonia"]):
        with col:
            if reg in region_agg.index:
                st.metric(reg, f"{region_agg.loc[reg, 'avg_time']:.0f} min")
                st.caption(f"{int(region_agg.loc[reg, 'station_count'])} stations")
            else:
                st.metric(reg, "---")

    region_geo = build_region_geojson(data["prov_geo"])
    region_totals = region_agg["avg_time"].to_dict()
    region_vals = [v for v in region_totals.values() if v > 0]
    if region_vals:
        rcmap = make_step_colormap(region_vals, f"Avg travel time (min) to {dest_label}")
        rm = render_reach_choropleth(
            region_geo["features"], region_totals, rcmap, "region",
            lambda n, t: f"{n}: {t:.0f} min avg",
        )
        st_folium(rm, use_container_width=True, height=500, key=f"dur_reg_{dest_label}")
    st.dataframe(region_agg, use_container_width=True)


# ── Header ───────────────────────────────────────────────────────────────────

dest_str = ", ".join(destination_names)
dir_label = "to" if direction == "To destination" else "from"
window_label = "Arrivals" if direction == "To destination" else "Departures"
st.caption(
    f"**{filters['start_date'].strftime('%d %b %Y')} – {filters['end_date'].strftime('%d %b %Y')}** "
    f"— Travel {dir_label} **{dest_str}** — Budget {max_hours}h — "
    f"{window_label} {departure_window[0]}h–{departure_window[1]}h"
)

# Compute global max time for consistent coloring
all_times = []
for dest_id in destination_ids:
    for sid, info in all_reachable[dest_id].items():
        all_times.append(info["travel_time"])
global_max_time = max(all_times) if all_times else 1

# ── Render per destination + average ─────────────────────────────────────────

if len(destination_ids) > 1:
    # Average map first
    avg_df = _build_average_df()
    st.subheader(f"Average across {len(destination_names)} destinations")
    n_ok = avg_df["travel_time"].notna().sum()
    st.caption(f"{n_ok}/{len(avg_df)} stations reachable from at least one destination")

    if view_mode == "Stations":
        _render_station_map(avg_df, None, global_max_time, "avg")
    elif view_mode == "Provinces":
        _render_province_view(avg_df, "average")
    elif view_mode == "Regions":
        _render_region_view(avg_df, "average")

# Individual maps
for dest_name, dest_id in zip(destination_names, destination_ids):
    st.subheader(f"To {dest_name}")
    df = _build_duration_df(all_reachable[dest_id], dest_id)
    df_ok = df[df["travel_time"].notna()]
    st.caption(f"{len(df_ok)}/{len(df)} stations reachable")

    if view_mode == "Stations":
        _render_station_map(df, dest_name, global_max_time, dest_name.replace(" ", "_"))
    elif view_mode == "Provinces":
        _render_province_view(df, dest_name)
    elif view_mode == "Regions":
        _render_region_view(df, dest_name)

    with st.expander(f"Data table — {dest_name}"):
        display = df_ok[["station_name", "travel_time", "transfers", "province", "region"]].copy()
        display.columns = ["Station", "Travel Time (min)", "Transfers", "Province", "Region"]
        st.dataframe(display.sort_values("Travel Time (min)").reset_index(drop=True),
                     use_container_width=True, height=300)

render_footer()
