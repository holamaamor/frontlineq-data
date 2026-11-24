# Ambargo media pipeline (how January 2026 was done; repeat month by month)

Goal: every Ambargo record without images gets real, openable photo/video links (like the editor's own event media), stored here in `amb/media/`.
Records are enriched through `ambargo.json` (overlay applied by the site at load; fill-only, see `flApplyAmbPatch` in the site source), never by editing `data.json`.

1. Worker branch `amb-media` (temporary) carries `.github/workflows/amb-media.yml` (copy: `tools/amb-media.workflow.yml.txt`) and `tools/amb_media.py`.
   Push a changed `tools/amb_jobs.json` to that branch → GitHub Actions (runner has open internet, the cloud sandbox does not) runs the script and commits
   `amb/result.json` + `amb/media/*` back to the branch. Job file: `get` = public Telegram post URLs to download (photos, videos Telegram releases, poster for big videos),
   `probe` = `{id, ch, q}` search of a public channel (t.me/s/<ch>?q=…) or `{id, ch, from, to}` id range → metadata only.
   Exilenova+ (`exilenova_plus`) covers most of the records; ASTRA, Shot, RusNews, Atesh, LSR post their own claims.
2. Look at the result: text/date must match the record; contact sheet of photos + video frames (ffmpeg -ss 1) to check content.
3. Copy only the chosen files to `main` (`git checkout amb-media -- amb/media/<file>`), re-encode videos >2.5 MB locally:
   `ffmpeg -i in.mp4 -t 90 -vf "scale='if(gt(iw,ih),-2,480)':'if(gt(iw,ih),480,-2)'" -c:v libx264 -crf 31 -preset medium -c:a aac -b:a 48k -movflags +faststart out.mp4`
   (480p, usually 5 MB → <1 MB). Photos are already ≤1280 px JPEG.
4. Overlay record: `media` = `https://raw.githubusercontent.com/holamaamor/frontlineq-data/main/amb/media/<file>` (videos first, then photos), `sources` += the t.me post.
   LSR videos are too big for Telegram's public preview: record `https://t.me/<ch>/<id>#flposter=<url-encoded raw poster>` (poster card "WATCH ON TELEGRAM").
   Records that already have media are left alone. Never attach a post that does not describe the record (check text + date).
5. Delete nothing in `amb/media/`; verify every URL answers 200 after pushing.
