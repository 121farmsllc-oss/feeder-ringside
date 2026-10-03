# Feeder Cattle P&L — Ring-side

Feeder cattle profit/loss and max-bid calculator, one self-contained web page.

- Calculator: https://121farmsllc-oss.github.io/feeder-ringside/
- Ring-side mode (live auction bidding): https://121farmsllc-oss.github.io/feeder-ringside/#ring

Your numbers are saved only in your own browser on that device (`localStorage`). Nothing is sent anywhere.
The page has only default example numbers and public market data. Not financial advice.

## Live Cattle futures

- `index.html` has a built-in CME Live Cattle (LE) strip, so it works offline and straight from a file.
- When it's opened from the website, the page also loads `futures.json` from this repo. If that file is newer than the built-in strip, the page uses it and keeps a copy on the phone for offline use. If the file is missing or the phone is offline, the page quietly uses what it already has.
- The workflow (`ops/update-futures.yml`; see "Turning on auto-refresh" below) runs `scripts/update_futures.py` on weekdays after the close (22:30 UTC) and again the next morning (11:30 UTC, to pick up the final settlements). It commits `futures.json` when prices change. You can also run it by hand from the Actions tab ("Run workflow").
- Sources: CME Group settlements first. That source often blocks cloud servers, so Yahoo Finance per-contract daily closes are the fallback. Once the session is final, those closes match the CME settlements. The script leaves out any contract it can't get a fresh price for, and it never writes the file with fewer than 6 contracts.

Run it locally with `python3 scripts/update_futures.py --dry-run` (standard library only, Python 3.9+).

## Turning on auto-refresh (one-time)

The publishing token didn't have GitHub's `workflow` permission, so the workflow is stored at `ops/update-futures.yml` and isn't active yet. To turn it on, do either of these:

- **On github.com:** open this repo, choose **Add file → Create new file**, name it `.github/workflows/update-futures.yml`, paste in the contents of `ops/update-futures.yml`, and commit.
- **From a terminal:** run `gh auth refresh -h github.com -s workflow`, then `git mv ops/update-futures.yml .github/workflows/update-futures.yml && git commit -m "Enable futures workflow" && git push`.

Until then, `futures.json` holds the Oct 2, 2026 settlements, entered by hand.
