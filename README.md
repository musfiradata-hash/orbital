# ORBITAL — Economic Health Platform (live pilot)

This is the complete, wired-together system: a data pipeline that pulls real
satellite data for 6 Abu Dhabi economic zones, and a dashboard that displays it.
No manual copy-pasting between the two — once set up, it runs itself.

## What's in here

- `index.html` — the dashboard. Fetches `data/ehi_live.json` on load. Falls
  back to illustrative synthetic data for any zone it can't find real data
  for, so it never looks broken.
- `pull_all_zones.py` — the pipeline. Pulls VIIRS, Sentinel-2, Sentinel-5P,
  and MODIS data for all 6 zones via Google Earth Engine, computes the EHI,
  and writes `data/ehi_live.json`.
- `.github/workflows/update_ehi.yml` — runs the pipeline automatically once a
  month and commits the fresh data.

## One-time setup (~20 minutes)

### 1. Create a GitHub repository
Create a new repo (public or private) and push these files into it, keeping
the folder structure exactly as-is (the `.github/workflows` folder must stay
where it is).

### 2. Create an Earth Engine service account
GitHub Actions can't do the interactive browser login you used in Colab, so
it needs a service account instead:

1. Go to **console.cloud.google.com**, open the same project you registered
   for Earth Engine.
2. Go to **IAM & Admin → Service Accounts → Create Service Account**. Give it
   any name (e.g. `orbital-ehi-pipeline`).
3. Grant it the **Earth Engine Resource Viewer** role (or broader Earth
   Engine access if that role isn't sufficient for your project).
4. Open the new service account → **Keys → Add Key → Create new key → JSON**.
   This downloads a `.json` file — keep it private, don't commit it to the repo.
5. Go to **code.earthengine.google.com → register**, and make sure this
   service account's email (looks like `name@project.iam.gserviceaccount.com`)
   is registered for Earth Engine access under the same Cloud project.

### 3. Add secrets to the GitHub repo
In your repo: **Settings → Secrets and variables → Actions → New repository secret**

- `EE_SERVICE_ACCOUNT_KEY` — paste the entire contents of the JSON key file
  from step 2.
- `EE_PROJECT_ID` — your Google Cloud project ID.

### 4. Enable GitHub Pages
**Settings → Pages → Source → Deploy from a branch → main → / (root)**.
GitHub will give you a URL like `https://yourusername.github.io/reponame/` —
that's your live dashboard link.

### 5. Run the pipeline for the first time
Don't wait for the monthly schedule — trigger it manually once to populate
real data immediately:
**Actions tab → "Update EHI live data" → Run workflow.**

Watch the run log. If it fails, the log will tell you which step (auth,
Earth Engine pull, or git commit) — paste that error back to me and I'll
help you fix it.

### 6. Check the dashboard
Once the workflow finishes (few minutes), open your GitHub Pages URL. The
header badge should say "LIVE DATA — N ZONES FROM EARTH ENGINE" instead of
"SYNTHETIC DEMO DATA". Any zone not yet marked "● LIVE" in the zone list
just hasn't been fetched successfully yet — check the workflow log for that
zone's entry.

## Notes on realism

- Not every zone will get a real OSM boundary automatically — `pull_all_zones.py`
  only tries this for zones with well-tagged names in OpenStreetMap (KIZAD,
  Masdar, Yas/Saadiyat). The others use a hand-picked bounding box, which is
  fine for a pilot but worth tightening with real GIS boundaries later.
- The monthly schedule matches how often the underlying satellite composites
  actually refresh — this was never going to be a real-time feed, and
  shouldn't be presented as one.
- First live pull will look rougher than the polished demo. That's expected —
  more history and tighter boundaries improve it over time, not the code.
