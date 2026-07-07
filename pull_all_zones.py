"""
ORBITAL EHI — Full pipeline: pulls real satellite indicators for all 6 zones
via Google Earth Engine and writes data/ehi_live.json in the exact shape the
dashboard (ehi_demo.html) expects.

Run this either:
  - Locally:  python pull_all_zones.py   (interactive ee.Authenticate() the
    first time; after that it reuses your cached credentials)
  - In GitHub Actions: uses a service account key from the EE_SERVICE_ACCOUNT_KEY
    secret instead of interactive auth (see .github/workflows/update_ehi.yml)

Requires: earthengine-api, requests
    pip install earthengine-api requests
"""

import datetime
import json
import os
import statistics
import sys

import ee
import requests

# =========================================================
# 1. AUTH — interactive locally, service account in CI
# =========================================================
def init_earth_engine():
    service_account_json = os.environ.get('EE_SERVICE_ACCOUNT_KEY')
    project_id = os.environ.get('EE_PROJECT_ID', 'your-project-id')

    if service_account_json:
        # CI / automated environment: use the service account key
        key_dict = json.loads(service_account_json)
        credentials = ee.ServiceAccountCredentials(
            key_dict['client_email'], key_data=service_account_json
        )
        ee.Initialize(credentials, project=project_id)
        print('Earth Engine initialized with service account.')
    else:
        # Local/interactive environment
        try:
            ee.Initialize(project=project_id)
        except Exception:
            ee.Authenticate()
            ee.Initialize(project=project_id)
        print('Earth Engine initialized interactively.')


# =========================================================
# 2. ZONE DEFINITIONS — id must match the dashboard's REGIONS ids
# =========================================================
ZONES = [
    {
        'id': 'adcity', 'name': 'Abu Dhabi City',
        'bbox': (24.40, 54.30, 24.52, 54.42),
        'osm_names': None,  # dense urban core — bounding box is fine, OSM landuse tagging too fragmented
    },
    {
        'id': 'kizad', 'name': 'KIZAD Industrial Zone',
        'bbox': (24.72, 54.55, 24.85, 54.75),
        'osm_names': 'Khalifa|KIZAD|KEZAD|Taweelah',
    },
    {
        'id': 'masdar', 'name': 'Masdar City',
        'bbox': (24.42, 54.60, 24.45, 54.63),
        'osm_names': 'Masdar',
    },
    {
        'id': 'alain', 'name': 'Al Ain',
        'bbox': (24.15, 55.70, 24.26, 55.82),
        'osm_names': None,
    },
    {
        'id': 'dhafra', 'name': 'Al Dhafra Region',
        'bbox': (24.05, 52.65, 24.20, 52.85),
        'osm_names': None,
    },
    {
        'id': 'yas', 'name': 'Yas Island / Saadiyat',
        'bbox': (24.47, 54.58, 24.55, 54.65),
        'osm_names': 'Yas|Saadiyat',
    },
]

OVERPASS_ENDPOINTS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://lz4.overpass-api.de/api/interpreter',
    'https://overpass.private.coffee/api/interpreter',
]


def fetch_osm_geometry(zone):
    """Try to find a real OSM landuse polygon; fall back to the bounding box."""
    s, w, n, e = zone['bbox']
    bbox_geom = ee.Geometry.Polygon([[[w, s], [e, s], [e, n], [w, n], [w, s]]])

    if not zone['osm_names']:
        return bbox_geom, 'bounding_box'

    query = f'''
    [out:json][timeout:60];
    (
      way["landuse"~"industrial|commercial|residential"]["name"~"{zone['osm_names']}",i]({s},{w},{n},{e});
      relation["landuse"~"industrial|commercial|residential"]["name"~"{zone['osm_names']}",i]({s},{w},{n},{e});
    );
    out geom;
    '''
    headers = {'User-Agent': 'orbital-ehi-pipeline/1.0'}

    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.get(endpoint, params={'data': query}, headers=headers, timeout=90)
            if resp.status_code != 200:
                continue
            elements = resp.json().get('elements', [])
            polygons = []
            for el in elements:
                if el.get('type') == 'way' and 'geometry' in el:
                    coords = [[pt['lon'], pt['lat']] for pt in el['geometry']]
                    if len(coords) >= 4:
                        polygons.append(coords)
            if polygons:
                best = max(polygons, key=len)
                return ee.Geometry.Polygon([best]), f'osm ({endpoint})'
        except Exception:
            continue

    return bbox_geom, 'bounding_box (osm fetch failed or empty)'


# =========================================================
# 3. PULL FUNCTIONS
# =========================================================
def month_range(m):
    start = ee.Date(m + '-01')
    end = start.advance(1, 'month')
    return start, end


def get_viirs(geom, m):
    start, end = month_range(m)
    coll = (ee.ImageCollection('NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG')
            .filterDate(start, end).select('avg_rad'))
    img = coll.mean()
    return img.reduceRegion(ee.Reducer.mean(), geom, 500, maxPixels=1e9).get('avg_rad')


def get_ndbi(geom, m):
    start, end = month_range(m)
    coll = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
            .filterDate(start, end).filterBounds(geom)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30)))

    def ndbi(img):
        return img.normalizedDifference(['B11', 'B8']).rename('NDBI')

    img = coll.map(ndbi).mean()
    return img.reduceRegion(ee.Reducer.mean(), geom, 10, maxPixels=1e9).get('NDBI')


def get_no2(geom, m):
    start, end = month_range(m)
    coll = (ee.ImageCollection('COPERNICUS/S5P/OFFL/L3_NO2')
            .filterDate(start, end).select('tropospheric_NO2_column_number_density'))
    img = coll.mean()
    return img.reduceRegion(ee.Reducer.mean(), geom, 1000, maxPixels=1e9).get(
        'tropospheric_NO2_column_number_density')


def get_ndvi(geom, m):
    start, end = month_range(m)
    coll = (ee.ImageCollection('MODIS/061/MOD13A2')
            .filterDate(start, end).select('NDVI'))
    img = coll.mean()
    return img.reduceRegion(ee.Reducer.mean(), geom, 500, maxPixels=1e9).get('NDVI')


# =========================================================
# 4. NORMALIZE / GAP-FILL / EHI / SMOOTH  (same methodology as the notebook)
# =========================================================
def normalize(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return [50.0] * len(values)
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1e-9
    return [None if v is None else round(100 * (v - lo) / span, 1) for v in values]


def forward_fill(values):
    filled, was_real = [], []
    last = None
    for v in values:
        if v is not None:
            last = v
            was_real.append(True)
        else:
            was_real.append(False)
        filled.append(last)
    first_real = next((v for v in filled if v is not None), 50.0)
    filled = [first_real if v is None else v for v in filled]
    return filled, was_real


def rolling_median(values, window=3):
    out = []
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        out.append(round(statistics.median(values[lo:i + 1]), 1))
    return out


WEIGHTS = {'activity': 0.30, 'built': 0.30, 'industrial': 0.25, 'agri': 0.15}


def process_zone(zone, months, display_months):
    geom, geom_source = fetch_osm_geometry(zone)
    print(f"[{zone['id']}] geometry source: {geom_source}")

    results = []
    for m in months:
        row = {'month': m}
        for key, fn in [('viirs_radiance', get_viirs), ('ndbi', get_ndbi),
                         ('no2', get_no2), ('ndvi', get_ndvi)]:
            try:
                row[key] = fn(geom, m).getInfo()
            except Exception:
                row[key] = None
        results.append(row)
        print(f"[{zone['id']}] {m}: {row}")

    viirs_vals = [r['viirs_radiance'] for r in results]
    ndbi_vals = [r['ndbi'] for r in results]
    no2_vals = [r['no2'] for r in results]
    ndvi_vals = [r['ndvi'] for r in results]

    n_viirs, real_viirs = forward_fill(normalize(viirs_vals))
    n_ndbi, real_ndbi = forward_fill(normalize(ndbi_vals))
    n_no2, real_no2 = forward_fill(normalize(no2_vals))
    n_ndvi, real_ndvi = forward_fill(normalize(ndvi_vals))

    raw_ehi, completeness = [], []
    for i in range(len(results)):
        score = (WEIGHTS['activity'] * n_viirs[i] + WEIGHTS['built'] * n_ndbi[i] +
                 WEIGHTS['industrial'] * n_no2[i] + WEIGHTS['agri'] * n_ndvi[i])
        raw_ehi.append(round(score, 1))
        completeness.append(round(100 * sum(
            [real_viirs[i], real_ndbi[i], real_no2[i], real_ndvi[i]]) / 4))

    ehi_smoothed = rolling_median(raw_ehi, window=3)
    cut = -display_months

    return {
        'zone_name': zone['name'],
        'geometry_source': geom_source,
        'months': months[cut:],
        'ehi': ehi_smoothed[cut:],
        'confidence_pct': completeness[cut:],
        'pillars': {
            'activity': n_viirs[cut:],
            'built': n_ndbi[cut:],
            'industrial': n_no2[cut:],
            'agri': n_ndvi[cut:],
        },
    }


# =========================================================
# 5. MAIN
# =========================================================
def main():
    init_earth_engine()

    baseline_months = int(os.environ.get('BASELINE_MONTHS', 30))
    display_months = int(os.environ.get('DISPLAY_MONTHS', 12))
    end_date = datetime.date.today().replace(day=1)

    months = []
    d = end_date
    for _ in range(baseline_months):
        months.append(d.strftime('%Y-%m'))
        prev_month = d.month - 1 or 12
        prev_year = d.year - 1 if d.month == 1 else d.year
        d = d.replace(year=prev_year, month=prev_month, day=1)
    months = sorted(months)

    output = {}
    for zone in ZONES:
        try:
            output[zone['id']] = process_zone(zone, months, display_months)
        except Exception as e:
            print(f"[{zone['id']}] FAILED: {e}", file=sys.stderr)

    output['_meta'] = {
        'pulled_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'baseline_months_used': baseline_months,
        'display_months': display_months,
    }
    # also stamp pulled_at per zone for the dashboard's per-zone display
    pulled_at = output['_meta']['pulled_at']
    for zid in list(output.keys()):
        if zid != '_meta':
            output[zid]['pulled_at'] = pulled_at

    os.makedirs('data', exist_ok=True)
    with open('data/ehi_live.json', 'w') as f:
        json.dump(output, f, indent=2)

    print('Saved data/ehi_live.json')


if __name__ == '__main__':
    main()
