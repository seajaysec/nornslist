# API key setup

Two keys are involved. Both are **optional** — the scraper falls back to
unauthenticated paths if either is missing — but each gives you noticeably
better coverage.

| Key | Purpose | Without it |
|-----|---------|------------|
| **GitHub token** | Authenticates GitHub API calls for the *Last Updated* column (one call per script repo) | Drops to 60 req/hr anonymous; only ~17% of *Last Updated* cells populate per run |
| **YouTube Data API key** | Returns video descriptions, used to disambiguate short-name scripts (e.g. `ufo`) | Falls back to HTML scrape of YouTube search; ~5–10 short-name scripts stay in "Missing Demo" |
| **Vimeo API token** | Enables Vimeo external video search (Path 3 of external_video_search) | Vimeo search step is skipped — anonymous Vimeo search returns JS-rendered HTML that isn't parseable |

---

## Local setup (running the scraper offline)

The scraper reads keys from two locations, in priority order:
1. **Environment variable** (`GITHUB_TOKEN`, `YOUTUBE_API_KEY`)
2. **Local file** (`gh.api`, `yt.api`) — same directory as the script

Two example files are committed: `gh.api.example` and `yt.api.example`.
Each contains step-by-step instructions in `#`-prefixed comments. To use:

```bash
cp gh.api.example gh.api
cp yt.api.example yt.api
# edit each file: replace the placeholder line with your real token/key
```

The loader skips `#`-comment lines, so you don't need to delete the
instructions — just append (or replace) the placeholder line with your key.
Both `gh.api` and `yt.api` are gitignored, so your secrets won't be committed.

### Getting a GitHub Personal Access Token

1. Go to https://github.com/settings/tokens
2. **Generate new token → Generate new token (classic)**
3. Note: `norns-scraper`
4. Expiration: your call (90 days is reasonable)
5. Scope: **`public_repo`** (or none — only public repos are queried)
6. Click **Generate token** and copy

### Getting a YouTube Data API v3 key

The free tier gives you 10,000 units/day. Each search costs 100 units, so
you get **100 free searches/day** — more than enough for the daily scrape
(~80 searches per run).

1. Open https://console.cloud.google.com/
2. Top-left dropdown → **New Project** (name it whatever, e.g. "norns-scraper")
3. Once the project is selected, navigate to **APIs & Services → Library**
4. Search for **YouTube Data API v3** → click it → **Enable**
5. Go to **APIs & Services → Credentials**
6. Click **+ CREATE CREDENTIALS → API key**
7. Copy the key
8. **Recommended**: click the new key → **Edit API key** → under
   *API restrictions*, select **Restrict key** and check only
   *YouTube Data API v3*. (Limits damage if the key ever leaks.)

That's it. Paste the key into `yt.api`.

---

## GitHub Actions setup (auto-deploy)

The `.github/workflows/daily-scrape-discourse.yml` workflow runs the scraper
daily and commits the updated xlsx + sidecars back to the repo.

**No `gh.api` file needed.** Actions provides `secrets.GITHUB_TOKEN`
automatically; the workflow passes it through as the `GITHUB_TOKEN` env var.

**`YOUTUBE_API_KEY` is opt-in.** To enable:

1. Get a YouTube Data API key (steps above).
2. In your repo, go to **Settings → Secrets and variables → Actions**.
3. Click **New repository secret**.
4. Name: `YOUTUBE_API_KEY`. Value: paste your key. Save.

The workflow file already references `${{ secrets.YOUTUBE_API_KEY }}` and
will pick it up next run. If the secret isn't set, the scraper falls back
to HTML scraping with no errors.

---

## Quick verification

To confirm your local keys are loaded correctly:

```bash
python -c "
from norns_scraper_discourse import NornsScraper
s = NornsScraper(max_workers=1)
print('GitHub token loaded:', bool(s._load_github_token()))
print('YouTube key loaded: ', bool(s._load_youtube_api_key()))
"
```

Both should print `True` after you've populated `gh.api` and `yt.api`.
