# SNCB Frequency Explorer

A multi-page Streamlit application that analyzes the Belgian rail network using SNCB/NMBS GTFS timetable data and Infrabel infrastructure geometry.

**Powered by [MobilityTwin.Brussels](https://api.mobilitytwin.brussels) (ULB)**

## Pages

### Home
Overview of the application with navigation to the two analysis tools.

### Segment Frequency Analysis
Visualizes how many trains pass through each rail segment per day.

- **Segment view**: Interactive map with line thickness and color proportional to train frequency. Station circles sized by frequency.
- **Province view**: Choropleth map aggregating segment frequencies by province.
- **Region view**: Same aggregation for Belgium's three regions (Brussels, Flanders, Wallonia).

The "mergure" algorithm resolves overlapping segments:
- Segments of similar size that overlap (500m buffer) are merged.
- When one segment is contained in another, the larger is cut and frequencies are redistributed, resulting in up to 3 non-overlapping segments.

### Station Reach Analysis
For every station in Belgium, computes how many other stations are reachable within a configurable time budget (including transfers).

- **Reachability BFS**: Uses a time-expanded Dijkstra/BFS over the GTFS timetable, accounting for transfer penalties.
- **Interactive map**: Stations colored and sized by number of reachable destinations. Click to highlight all connections.
- **Aggregated stats**: Bar charts by province and region showing average connectivity.

## Data Pipeline

1. **GTFS fetch**: Downloads the SNCB GTFS zip from the MobilityTwin API for the selected date range.
2. **Station matching**: Each GTFS stop is matched to the nearest Infrabel operational point using lat/lon proximity (1km buffer, Shapely STRtree spatial index). Achieves 99.8% match rate.
3. **Frequency computation**: For each consecutive stop pair in active trips, counts daily average frequency.
4. **Infrastructure mapping**: GTFS segment frequencies are resolved onto Infrabel track geometry via direct matching or BFS through the Infrabel graph.
5. **Network validation**: Verifies the Infrabel graph is fully connected (single component).

## Filters

All pages share common sidebar filters:
- **Date range**: Start/end dates for the analysis period.
- **Days of the week**: Select which weekdays to include.
- **Holidays**: Option to exclude public and/or school holidays.
- **Time of day**: Filter by departure hour window.

The Reach Analysis page adds:
- **Time budget**: How many hours of travel to consider (supports fractional, e.g. 1.5).
- **Departure hour**: What time to start the reachability search.
- **Transfer penalty**: Minimum minutes required for a transfer between trains.

## Project Structure

```
app.py                  # Entry point (Home page)
pages/
  1_Segment_Frequency.py  # Segment frequency analysis page
  2_Station_Reach.py      # Station reach analysis page
logic/
  __init__.py
  api.py                # MobilityTwin API calls (GTFS, Infrabel)
  geo.py                # Geographic utilities (Shapely-based)
  gtfs.py               # GTFS data processing
  holidays.py           # Belgian holidays calendar
  matching.py           # Station matching & segment mergure
  reachability.py       # BFS reachability computation
  rendering.py          # Folium map rendering
  shared.py             # Shared sidebar, CSS, data loading
provinces.geojson       # Belgian province boundaries
requirements.txt
```

## Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set API token
echo "BRUSSELS_MOBILITY_TWIN_KEY=your_token_here" > .env

# Run
streamlit run app.py
```

## Requirements

- Python 3.10+
- A valid MobilityTwin Brussels API token

## Dependencies

- `streamlit` - Web framework
- `folium` / `streamlit-folium` - Interactive maps
- `shapely` - Efficient geometric operations (spatial indexing, overlap detection)
- `pandas` / `numpy` - Data processing
- `requests` - API calls
- `branca` - Colormaps
- `python-dotenv` - Environment variable management
