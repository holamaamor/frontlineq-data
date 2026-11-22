# frontlineq-data

Data files for the **Frontlines** site. They live here, outside the site repo, so that updating
them never triggers a Netlify production deploy (each one costs 15 of the 300 monthly free credits).

| file | written by | content |
|---|---|---|
| `data.json` | the site's editor → **PUBLISH** button | events, desk posts, ambargo records, loss counters |
| `auto.json` | the daily scheduled task (`tools/update_auto.py`) | DeepState zones, Ukrainian unit positions, loss counters |

The site reads both files from `https://raw.githubusercontent.com/holamaamor/frontlineq-data/main/`
(GitHub caches raw files for ~5 minutes) and falls back to the copies shipped with the site.

Sources: DeepStateMap.live (via cyterat/deepstate-map-data), Ukraine Control Map (owlmaps/map-data),
Ukrainian General Staff daily briefing (loss counters). See `tools/DAILY.md` for the daily procedure.
