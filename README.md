# frontlineq-data

Data files for the **Frontlines** site. They live here, outside the site repo, so that updating
them never triggers a Netlify production deploy (each one costs 15 of the 300 monthly free credits).

| file | written by | content |
|---|---|---|
| `data.json` | the site's editor → **PUBLISH** button | events, desk posts, ambargo records, loss counters |
| `auto.json` | the daily scheduled task (`tools/`) | DeepState zones, Ukrainian unit positions, loss counters (Blood Loss of Russia), Mediazona figures (`cargo200`) |
| `cargo200/*.json` | one-off builds (`tools/` + the iStories scrape) | CARGO200 map data: where the dead lived, places of death, the modelled remainder of the estimate |
| `cargo200/front/` | `python3 tools/build_front.py` (`--update` adds the days up to today) | front-line history for the CARGO200 map: `index.json` (all frame dates), `pre.json` (schematic frames 2022-02-24 – 2024-07-01, redrawn from ISW assessments, about 5–10 km accurate), `YYYY-MM.json` (DeepState daily frames from 2024-07-08, simplified to ~200 m) |
| `state/` | the daily scheduled task | Militaryland unit ids already reviewed (`ml_seen.json`) and new ones waiting to be added to the site (`ml_pending.json`) |
| `reports/YYYY-MM-DD.md` | the daily scheduled task | short Turkish report of what each daily run updated |

The site reads both files from `https://raw.githubusercontent.com/holamaamor/frontlineq-data/main/`
(GitHub caches raw files for ~5 minutes) and falls back to the copies shipped with the site.

Sources: DeepStateMap.live (via cyterat/deepstate-map-data, GPL-3.0), schematic 2022–2024 front frames (longlinecode/russo-ukrainian-front-daily), Ukraine Control Map (owlmaps/map-data),
Ukrainian General Staff daily briefing (loss counters), Mediazona / BBC Russian named list (CARGO200), Militaryland.net (new unit pages). See `tools/DAILY.md` for the daily procedure.
