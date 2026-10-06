"""Weekly showtime scrape orchestrator.

Runs each theater scraper, merges into showtimes.json:
{
  "generated": "<ISO UTC>",
  "showtimes": [
    {"theater": ..., "theater_id": ..., "movie": ..., "date": "YYYY-MM-DD",
     "times": [{"time": "HH:MM", "format": ..., "ticket_url": ...}],
     "format": ..., "ticket_url": ...},
    ...
  ],
  "blocked": {theater_id: {name, blocked, detail}},
  "stats": {"theaters_ok": n, "listings": n}
}

Usage: python run_all.py [--out PATH] [--cmx-days N] [--pw]
  --pw   also run the Playwright scrapers for the Cloudflare-blocked chains
         (needs the movie-tickets venv + playwright chromium; on CI this is
         installed by the workflow. On the dev VM these stay blocked.)
Writes showtimes.json next to the repo root by default.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cmx
import rooftop
import ocinema
import gables
import blocked

REPO_ROOT = Path(__file__).parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO_ROOT / "showtimes.json"))
    ap.add_argument("--cmx-days", type=int, default=7)
    ap.add_argument("--oc-max", type=int, default=25)
    ap.add_argument("--pw", action="store_true",
                    help="run Playwright scrapers for blocked chains")
    args = ap.parse_args()

    showtimes = []
    print("Scraping CMX Brickell...", flush=True)
    try:
        showtimes.extend(cmx.scrape(days=args.cmx_days))
    except Exception as e:
        print(f"CMX failed: {e}", flush=True)

    print("Scraping Rooftop Cinema Club...", flush=True)
    try:
        showtimes.extend(rooftop.scrape())
    except Exception as e:
        print(f"Rooftop failed: {e}", flush=True)

    print("Scraping O Cinema...", flush=True)
    try:
        showtimes.extend(ocinema.scrape(max_events=args.oc_max))
    except Exception as e:
        print(f"O Cinema failed: {e}", flush=True)

    print("Scraping Coral Gables Art Cinema...", flush=True)
    try:
        showtimes.extend(gables.scrape())
    except Exception as e:
        print(f"Gables failed: {e}", flush=True)

    blocked_info = {}
    if args.pw:
        print("Running Playwright scrapers for blocked chains...", flush=True)
        try:
            import playwright_scrape
            pw_st, pw_blocked = playwright_scrape.scrape_all_pw(headless=True)
            showtimes.extend(pw_st)
            blocked_info.update(pw_blocked)
            print(f"  Playwright: {len(pw_st)} listings", flush=True)
        except Exception as e:
            print(f"  Playwright run failed: {e}", flush=True)

    print("Probing blocked theaters...", flush=True)
    for tid, info in blocked.check_all().items():
        # don't overwrite fresh Playwright results
        blocked_info.setdefault(tid, info)
        print(f"  {info['name']}: {'BLOCKED' if info['blocked'] else 'UNBLOCKED?!'}",
              flush=True)

    # Drop entries with no usable date
    showtimes = [s for s in showtimes if s.get("date")]

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "showtimes": showtimes,
        "blocked": blocked_info,
        "stats": {
            "theaters_ok": len({s["theater_id"] for s in showtimes}),
            "listings": len(showtimes),
        },
    }
    Path(args.out).write_text(json.dumps(payload, indent=1))
    print(f"Wrote {args.out}: {len(showtimes)} listings, "
          f"{payload['stats']['theaters_ok']} theaters", flush=True)


if __name__ == "__main__":
    main()
