# Daily procedure (scheduled task)

1. `python3 tools/update_auto.py` — refreshes the DeepState zones (diff of the latest cyterat GeoJSON against
   the stored date) and the Ukrainian unit positions (latest owlmaps daily file). It prints a JSON summary.
   It refuses (and leaves `auto.json` untouched) when a sanity check fails; read the message and report it.
2. Loss counters (General Staff, "Blood Loss of Russia"): find the latest daily figures with a web search,
   open at least TWO independent outlets (e.g. Ukrinform, Ukrainska Pravda, Ukrmedia, UNIAN) and accept the numbers
   only if every one of the 15 values matches between them for the same date. Write `losses.json`:
   `{"date":"YYYY-MM-DD","dateLabel":"22 NOV 2026","srcDate":"22.11.2026","via":"via A, B and C (identical).",
     "bulletin":"22 November bulletin (1,6xx,xxx)","items":[{"label":"PERSONNEL","value":"1.622.860","delta":"+2.230"}, … 15 items in the
   order of `LABELS` in the script]}` then `python3 tools/update_auto.py --skip-deepstate --skip-units --losses losses.json`.
   Numbers use dots as thousands separators; delta is the daily increase as reported. If the outlets disagree, or no
   second source is found, do NOT update the counters — say so in the commit message.
3. `git add auto.json && git commit -m "Daily auto update <date>: <one-line summary>" && git push`.
   Never edit `data.json` (it is the editor's file and is written from the site).
