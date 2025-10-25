import os
import sys
import argparse
import requests
import datetime
import statistics
import json
from typing import Optional, Tuple, Dict, Any, List

BASE_CURR = "https://api.openweathermap.org/data/2.5/weather"
BASE_FORECAST = "https://api.openweathermap.org/data/2.5/forecast"
BASE_GEOCODING = "http://api.openweathermap.org/geo/1.0/direct"  # to get lat/lon from city name


def get_api_key(cli_key: Optional[str] = None) -> str:
    key = cli_key or os.environ.get("OPENWEATHER_API_KEY")
    if not key:
        raise RuntimeError("OpenWeather API key not provided. Set OPENWEATHER_API_KEY or use --api-key.")
    return key


def geocode_city(city: str, api_key: str, limit: int = 1) -> Tuple[float, float, str]:
    """
    Use OpenWeatherMap geocoding to translate city name to lat/lon.
    Returns (lat, lon, resolved_name)
    """
    params = {"q": city, "limit": limit, "appid": api_key}
    r = requests.get(BASE_GEOCODING, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"Could not find location for '{city}'")
    item = data[0]
    lat = float(item["lat"])
    lon = float(item["lon"])
    name_parts = [item.get("name", "")]
    if item.get("state"):
        name_parts.append(item["state"])
    if item.get("country"):
        name_parts.append(item["country"])
    resolved = ", ".join([p for p in name_parts if p])
    return lat, lon, resolved


def fetch_current_weather(lat: float, lon: float, api_key: str, units: str = "metric") -> Dict[str, Any]:
    params = {"lat": lat, "lon": lon, "appid": api_key, "units": units}
    r = requests.get(BASE_CURR, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_forecast(lat: float, lon: float, api_key: str, units: str = "metric") -> Dict[str, Any]:
    params = {"lat": lat, "lon": lon, "appid": api_key, "units": units}
    r = requests.get(BASE_FORECAST, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def pretty_time_from_unix(ts: int, tz_shift: int = 0) -> str:
    # tz_shift in seconds
    dt = datetime.datetime.utcfromtimestamp(ts + tz_shift)
    return dt.strftime("%Y-%m-%d %H:%M")


def summarize_forecast(forecast_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Summarize 3-hourly forecast into daily buckets (date, min, max, avg temps and weather icons)
    Returns list sorted by date (str YYYY-MM-DD).
    """
    items = forecast_json.get("list", [])
    buckets = {}
    for entry in items:
        ts = entry.get("dt")
        dt = datetime.datetime.utcfromtimestamp(ts)
        date_key = dt.date().isoformat()
        temp = entry["main"]["temp"]
        desc = entry["weather"][0]["description"]
        icon = entry["weather"][0].get("icon")
        buckets.setdefault(date_key, {"temps": [], "descs": [], "icons": []})
        buckets[date_key]["temps"].append(temp)
        buckets[date_key]["descs"].append(desc)
        buckets[date_key]["icons"].append(icon)

    summary = []
    for d in sorted(buckets.keys()):
        temps = buckets[d]["temps"]
        descs = buckets[d]["descs"]
        icons = buckets[d]["icons"]
        most_common_desc = max(set(descs), key=descs.count)
        most_common_icon = max(set(icons), key=icons.count) if icons else None
        summary.append({
            "date": d,
            "min_temp": min(temps),
            "max_temp": max(temps),
            "avg_temp": statistics.mean(temps),
            "typical_weather": most_common_desc,
            "icon": most_common_icon
        })
    return summary


def print_current_weather(current_json: Dict[str, Any], units_label: str = "°C"):
    name = current_json.get("name", "")
    sys_info = current_json.get("sys", {})
    country = sys_info.get("country", "")
    print(f"\nCurrent weather — {name}{(', ' + country) if country else ''}")
    weather = current_json.get("weather", [{}])[0]
    main = current_json.get("main", {})
    wind = current_json.get("wind", {})
    tz_shift = current_json.get("timezone", 0)  # seconds
    ts = current_json.get("dt", 0)
    print(f"  As of: {pretty_time_from_unix(ts, tz_shift)} (local)")
    print(f"  Condition : {weather.get('main','')} — {weather.get('description','')}")
    print(f"  Temperature: {main.get('temp', 'N/A')}{units_label} (feels like {main.get('feels_like', 'N/A')}{units_label})")
    print(f"  Min / Max : {main.get('temp_min', 'N/A')}{units_label} / {main.get('temp_max', 'N/A')}{units_label}")
    print(f"  Humidity  : {main.get('humidity', 'N/A')}%")
    print(f"  Pressure  : {main.get('pressure', 'N/A')} hPa")
    print(f"  Wind      : {wind.get('speed', 'N/A')} m/s, gust {wind.get('gust','N/A')}")
    coord = current_json.get("coord", {})
    if coord:
        print(f"  Coordinates: lat={coord.get('lat')}, lon={coord.get('lon')}")
    print("")


def print_forecast_summary(summary: List[Dict[str, Any]], units_label: str = "°C", days: int = 5):
    print(f"Forecast summary (next {min(days, len(summary))} days):")
    for day in summary[:days]:
        date = day["date"]
        mi = round(day["min_temp"], 1)
        ma = round(day["max_temp"], 1)
        av = round(day["avg_temp"], 1)
        desc = day["typical_weather"].capitalize()
        print(f"  {date} — {desc:20}  min:{mi}{units_label}  max:{ma}{units_label}  avg:{av}{units_label}")
    print("")


def run_cli(args):
    api_key = get_api_key(args.api_key)
    units = args.units.lower()
    units_label = "°C" if units == "metric" else ("°F" if units == "imperial" else "K")
    try:
        if args.lat is not None and args.lon is not None:
            lat, lon = float(args.lat), float(args.lon)
            resolved_name = f"{lat},{lon}"
        else:
            lat, lon, resolved_name = geocode_city(args.city, api_key)
        print(f"[i] Resolved location: {resolved_name} (lat={lat}, lon={lon})")
        curr = fetch_current_weather(lat, lon, api_key, units=units)
        forecast = fetch_forecast(lat, lon, api_key, units=units)
        if args.save_json:
            out = {"resolved": resolved_name, "current": curr, "forecast": forecast}
            with open(args.save_json, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2, ensure_ascii=False)
            print(f"[i] Saved raw data to {args.save_json}")
        print_current_weather(curr, units_label=units_label)
        summary = summarize_forecast(forecast)
        print_forecast_summary(summary, units_label=units_label, days=args.days)
    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        sys.exit(1)


# -----------------------
# Minimal Streamlit UI
# -----------------------
def run_streamlit_app(args):
    try:
        import streamlit as st
    except Exception as e:
        print("[!] Streamlit not installed. pip install streamlit", file=sys.stderr)
        sys.exit(2)

    st.set_page_config(page_title="Weather App", layout="centered")
    st.title("Weather App (OpenWeatherMap)")
    api_key = get_api_key(args.api_key)

    with st.form("location_form"):
        mode = st.radio("Search by", ["City name", "Coordinates"])
        if mode == "City name":
            city = st.text_input("City (e.g. Hyderabad,IN)", value=args.city or "")
            lat = lon = None
        else:
            lat = st.text_input("Latitude", value=str(args.lat) if args.lat is not None else "")
            lon = st.text_input("Longitude", value=str(args.lon) if args.lon is not None else "")
            city = None
        units = st.selectbox("Units", ["metric", "imperial", "standard"], index=0 if args.units == "metric" else (1 if args.units == "imperial" else 2))
        submitted = st.form_submit_button("Get Weather")

    if submitted:
        try:
            if mode == "City name":
                if not city:
                    st.error("Enter a city name.")
                    return
                lat_v, lon_v, resolved = geocode_city(city, api_key)
            else:
                if not lat or not lon:
                    st.error("Enter latitude and longitude.")
                    return
                lat_v, lon_v = float(lat), float(lon)
                resolved = f"{lat_v},{lon_v}"
            st.write(f"**Location:** {resolved} (lat={lat_v}, lon={lon_v})")
            curr = fetch_current_weather(lat_v, lon_v, api_key, units=units)
            forecast = fetch_forecast(lat_v, lon_v, api_key, units=units)
            st.subheader("Current Weather")
            weather = curr.get("weather", [{}])[0]
            main = curr.get("main", {})
            wind = curr.get("wind", {})
            tz_shift = curr.get("timezone", 0)
            ts = curr.get("dt", 0)
            st.write(f"**As of:** {pretty_time_from_unix(ts, tz_shift)}")
            c1, c2 = st.columns([2, 3])
            with c1:
                st.write(f"**{weather.get('main','')}** — {weather.get('description','')}")
                st.write(f"Temp: {main.get('temp')}  Feels: {main.get('feels_like')}")
                st.write(f"Humidity: {main.get('humidity')}%")
                st.write(f"Pressure: {main.get('pressure')} hPa")
                st.write(f"Wind: {wind.get('speed')} m/s")
            with c2:
                icon_code = weather.get("icon")
                if icon_code:
                    icon_url = f"http://openweathermap.org/img/wn/{icon_code}@2x.png"
                    st.image(icon_url, width=100)
            st.subheader("Forecast summary")
            summary = summarize_forecast(forecast)
            for day in summary[: args.days]:
                st.write(f"**{day['date']}** — {day['typical_weather'].title()}  min:{round(day['min_temp'],1)}  max:{round(day['max_temp'],1)}  avg:{round(day['avg_temp'],1)}")
        except Exception as e:
            st.error(f"Error: {e}")


def parse_args():
    p = argparse.ArgumentParser(description="Weather App using OpenWeatherMap")
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument("--city", type=str, help='City name, e.g. "Hyderabad,IN" or "London"')
    g.add_argument("--lat", type=float, help="Latitude (decimal)")
    p.add_argument("--lon", type=float, help="Longitude (decimal) -- required if --lat used")
    p.add_argument("--api-key", type=str, help="OpenWeatherMap API key (defaults to OPENWEATHER_API_KEY env var)")
    p.add_argument("--units", type=str, choices=["metric", "imperial", "standard"], default="metric", help="Units: metric (°C), imperial (°F), standard (K)")
    p.add_argument("--save-json", type=str, help="Save raw responses to JSON file")
    p.add_argument("--days", type=int, default=5, help="Number of forecast days to show (up to 5)")
    p.add_argument("--streamlit", action="store_true", help="Run a minimal Streamlit UI")
    return p.parse_args()


def main():
    args = parse_args()

    # If lat provided, require lon
    if args.lat is not None and args.lon is None:
        print("[!] --lon is required when --lat is provided.", file=sys.stderr)
        sys.exit(2)

    if args.streamlit:
        # Run Streamlit UI
        run_streamlit_app(args)
    else:
        # Default: require city if lat not provided
        if args.lat is None and not args.city:
            print("Usage: provide --city 'City,COUNTRY' OR --lat LAT --lon LON", file=sys.stderr)
            print("Example: python Weather_App.py --city 'Hyderabad,IN' --units metric")
            sys.exit(2)
        run_cli(args)


if __name__ == "__main__":
    main()
