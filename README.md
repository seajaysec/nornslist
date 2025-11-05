# Norns Community Script Scraper

A comprehensive Python tool for scraping and aggregating script information for **monome norns** scripts from multiple sources, providing filterable, amplified information to help users discover and explore the norns script ecosystem.

## Project Goal

This tool aggregates and enriches script metadata from multiple sources to create a comprehensive, filterable database of norns scripts. The goal is to provide **filterable, amplified information** about scripts for monome norns, sourced from:

- **[norns.community](https://norns.community)** - Primary script listing and metadata
- **[llllllll.co](http://llllllll.co)** - Discussion threads and community conversations
- **YouTube** - Demo videos and tutorials
- **Vimeo** - Demo videos and showcases
- **Instagram** - Visual demos and quick previews
- **GitHub** - Project repositories and code updates

## Features

### Core Scraping Capabilities

- **Comprehensive Script Discovery**: Scrapes all scripts listed on norns.community
- **Detailed Metadata Extraction**: Extracts name, author(s), tags, description, and all URLs
- **Incremental Updates**: Only updates missing information, preserves manual corrections
- **Parallel Processing**: Uses ThreadPoolExecutor for fast concurrent scraping (10x faster than sequential)
- **Smart Field Detection**: Automatically determines which fields need updating based on existing data

### Demo Video Discovery

- **Multi-Source Demo Discovery**: Automatically discovers demo videos from discussion URLs
- **Platform Support**: Detects demos from YouTube, Vimeo, SoundCloud, and Instagram
- **Dual Discovery Methods**:
  - **HTML Extraction**: Fast parsing of static HTML content
  - **Playwright Rendering**: JavaScript-heavy page rendering for dynamic content
- **Smart Conflict Resolution**: Compares results from both methods and tracks resolution status
- **Multiple Detection Methods**:
  - Direct links (`<a href="...">`)
  - Embedded videos (YouTube/Vimeo iframes)
  - Video containers (divs with data-video-id attributes)
  - JSON-LD structured data (VideoObject schema)
  - Instagram video posts
- **Automatic Retry**: Retries failed requests with increased delays to avoid rate limiting

### GitHub Integration

- **Last Updated Tracking**: Automatically fetches latest non-README commit date from GitHub repositories
- **Smart Filtering**: Ignores README-only commits to track actual code changes
- **API Integration**: Uses GitHub API with optional authentication for higher rate limits
- **Automatic URL Detection**: Identifies GitHub repositories from Project URLs

### Sync Tracking

- **Out of Sync Detection**: Automatically compares scraped data with existing Excel data
- **Field-Level Tracking**: Identifies which specific fields differ (Name, Author, Tags, Description, URLs)
- **Normalized Comparison**: Handles URL normalization, whitespace differences, and case variations
- **Standalone Sync Check**: Run sync check without full scraping

### Playwright Status Management

Tracks how demo URLs were discovered and resolved:

- **No Conflict**: Both methods found the same URL
- **Playwright Preferred**: Only Playwright found the demo (typically embed-only providers)
- **Extract Preferred**: Only HTML extraction found the demo
- **Manual Override**: User manually entered or existing demo doesn't match discovery
- **Missing Demo**: No demo found by either method

### Excel Output

- **Professional Formatting**: Font size 14, Orange Table Style Dark 11, frozen header row
- **Clickable Hyperlinks**: All URLs (Demo, Discussion URL, Project URL, Community URL) are clickable
- **Auto-Adjusted Columns**: Column widths automatically adjust to content
- **Alphabetical Sorting**: Automatically sorts scripts by name
- **Table Format**: Excel table with row striping for easy reading
- **Comprehensive Fields**:
  - Name
  - Author (supports multiple authors, comma-separated)
  - Tags (comma-separated)
  - Description
  - Demo (clickable hyperlink)
  - Discussion URL (clickable hyperlink)
  - Project URL (clickable hyperlink)
  - Community URL (clickable hyperlink)
  - Playwright Status
  - Last Updated (YYYY-MM-DD from GitHub)
  - Out of Sync (comma-separated list of changed fields)

## Requirements

- Python 3.7+
- Required packages listed in `requirements.txt`

## Installation

1. Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

Run the scraper to fetch all scripts and save to Excel:

```bash
python norns_scraper.py
```

This will:
- Scrape all scripts from norns.community
- Discover demo videos using both HTML extraction and Playwright
- Fetch GitHub last updated dates
- Compare with existing data and track sync status
- Save to `norns_scripts.xlsx`

### Command-Line Options

```bash
# Specify number of parallel workers (default: 10)
python norns_scraper.py --workers 15

# Control delay between demo discovery requests (default: 0.5 seconds)
python norns_scraper.py --demo-delay 1.0

# Test mode: process only a single script by Community URL
python norns_scraper.py --test https://norns.community/scriptname

# Specify custom Excel file path (default: norns_scripts.xlsx)
python norns_scraper.py --excel custom_output.xlsx

# Sync check only: compute and update 'Out of Sync' without full scraping
python norns_scraper.py --sync-check

# Deduplicate existing Excel file by Community URL path
python norns_scraper.py --dedupe

# Apply Playwright Status updates from a log file
python norns_scraper.py --status-log scraper.log
```

### Demo Discovery

Demo discovery runs automatically and uses two methods:

1. **HTML Extraction**: Fast parsing of static HTML content from discussion URLs
2. **Playwright Rendering**: Full browser rendering for JavaScript-heavy pages

Both methods run in parallel and results are compared. The scraper handles:
- Regular links (`<a href="...">`)
- Embedded videos (YouTube/Vimeo iframes)
- Video containers (divs with data-video-id attributes)
- JSON-LD structured data (VideoObject schema)
- Instagram video posts
- Automatic retry for rate-limited requests

**Note:** If the scraper encounters rate limiting errors during demo discovery, it will automatically retry failed requests at the end with increased delays to be more respectful to the server.

### Incremental Updates and Data Preservation

The scraper intelligently preserves your manual work:

- **New Scripts**: Added automatically if not present in existing Excel file
- **Missing Data**: Filled in from scraped data if fields are blank
- **Manual Corrections**: Preserved if existing data is already filled in
- **Existing Scripts**: Kept even if not found in current scraping run

**Example:** If you manually correct an author name in Excel from "tyler" to "trickyflemming", running the scraper again will:
- ✅ Preserve your manual correction ("trickyflemming")
- ✅ Fill in any missing description, URLs, or tags
- ✅ Add any new scripts found on the website
- ✅ Update "Last Updated" from GitHub if available
- ✅ Update "Out of Sync" field if any changes are detected

### GitHub Last Updated Tracking

The scraper automatically detects GitHub repositories from Project URLs and fetches the latest commit date (excluding README-only changes). 

**Setup (Optional):**

For higher GitHub API rate limits, you can provide authentication:

1. Set environment variable: `export GITHUB_TOKEN=your_token_here`
2. Or create a `gh.api` file in the project directory with your token

Without authentication, the scraper uses unauthenticated API calls (lower rate limits).

### Sync Check Mode

Run sync check independently to update the "Out of Sync" column without doing a full scrape:

```bash
python norns_scraper.py --sync-check
```

This will:
- Load existing Excel file
- Scrape each script's current state from norns.community
- Compare with existing data
- Update "Out of Sync" column with field names that differ
- Save back to Excel

### Deduplication Mode

Remove duplicate rows from an Excel file:

```bash
python norns_scraper.py --dedupe --excel norns_scripts.xlsx
```

Deduplicates by Community URL path (keeps first occurrence). For rows without Community URL, deduplicates by Name.

### Status Log Application

Apply Playwright Status updates from a previous run's log file:

```bash
python norns_scraper.py --status-log scraper.log --excel norns_scripts.xlsx
```

This parses status assignments from log messages and updates the Excel file without re-scraping.

## How It Works

### Scraping Workflow

1. **Main Page Scraping**: Fetches the main norns.community page and extracts all script links
2. **Efficiency Analysis**: Compares existing Excel data to determine which scripts need updating
3. **Parallel Processing**: Uses ThreadPoolExecutor to scrape multiple script pages concurrently
4. **Individual Page Scraping**: For each script, visits the individual page and extracts detailed information
5. **Demo Discovery**: Discovers demo videos using both HTML extraction and Playwright rendering
6. **GitHub Enrichment**: Fetches last updated dates from GitHub repositories
7. **Data Merging**: Merges new scraped data with existing data, preserving manual corrections
8. **Sync Comparison**: Compares scraped values with existing values to track changes
9. **Excel Export**: Saves all data to Excel with professional formatting and clickable hyperlinks

### Data Sources

The scraper aggregates information from multiple sources:

1. **norns.community**: Primary source for script metadata (name, author, tags, description, URLs)
2. **llllllll.co**: Discussion threads scanned for demo videos and additional context
3. **YouTube/Vimeo/SoundCloud/Instagram**: Demo videos discovered from discussion threads
4. **GitHub API**: Repository information and commit dates for last updated tracking

## Output Format

The script creates an Excel file (`norns_scripts.xlsx` by default) with the following columns:

- **Name**: The name of the script
- **Author**: The script author's username(s), comma-separated for multiple authors
- **Tags**: Comma-separated list of tags (e.g., "synth, midi")
- **Description**: Brief description of what the script does
- **Demo**: Demo video URL (clickable hyperlink) - discovered from discussion threads
- **Discussion URL**: Link to the discussion thread on llllllll.co (clickable hyperlink)
- **Project URL**: URL to the script's repository/project page (clickable hyperlink)
- **Community URL**: URL to the script's page on norns.community (clickable hyperlink)
- **Playwright Status**: How the demo URL was discovered (No Conflict, Playwright Preferred, etc.)
- **Last Updated**: Latest commit date from GitHub (YYYY-MM-DD format, excludes README-only changes)
- **Out of Sync**: Comma-separated list of fields that differ from scraped data

## Performance

- **Parallel Processing**: Scrapes multiple scripts simultaneously using ThreadPoolExecutor
- **Configurable Workers**: Default 10 workers (adjustable based on your system and network)
- **Speed**: Approximately 10x faster than sequential scraping
- **Efficiency**: Only scrapes scripts that need updates (missing fields or changed data)
- **Respectful**: Each thread uses its own session, with delays between requests to avoid rate limiting

## Error Handling

- Network errors are logged and individual script failures won't stop the entire process
- Missing or malformed data is handled gracefully
- Progress is logged throughout the scraping process
- Automatic retry for rate-limited requests with increased delays
- Graceful degradation when GitHub API rate limits are hit

## Example Output

The script successfully scrapes all scripts from norns.community and enriches them with data from multiple sources. Example entry:

- **Name**: grendy
- **Author**: cfd90 (single author) or argotechnica, infinitedigits, license, tyleretters (multiple authors)
- **Tags**: synth, midi
- **Description**: simple drone synth, grendel drone commander inspired
- **Demo**: https://www.youtube.com/watch?v=abc123 (clickable hyperlink, discovered automatically)
- **Discussion URL**: https://llllllll.co/t/31721 (clickable hyperlink)
- **Project URL**: https://github.com/cfdrake/grendy (clickable hyperlink)
- **Community URL**: https://norns.community/grendy (clickable hyperlink)
- **Playwright Status**: No Conflict (both discovery methods found the same URL)
- **Last Updated**: 2024-11-15 (from GitHub, excludes README-only commits)
- **Out of Sync**: (empty if up-to-date, or lists fields like "Name, Author" if changed)

## Performance Comparison

- **Sequential**: ~2.5 minutes for 323 scripts
- **Parallel (10 workers)**: ~15-20 seconds for 323 scripts
- **Speed improvement**: ~10x faster
- **Efficiency**: Subsequent runs only update changed or missing data, typically processing 10-50 scripts instead of all 323

## Filtering and Analysis

The Excel output format makes it easy to filter and analyze the norns script ecosystem:

- **Filter by Tags**: Use Excel's filter to find all "synth" or "midi" scripts
- **Sort by Last Updated**: Identify actively maintained scripts
- **Check Out of Sync**: Quickly see which scripts have changed on norns.community
- **Filter by Demo**: Find scripts with demo videos for quick previews
- **Filter by Playwright Status**: Review which demos needed special discovery methods
- **Clickable Links**: Direct access to discussion threads, project pages, and demo videos

This makes the tool ideal for:
- **Discovery**: Finding new scripts based on tags or features
- **Maintenance Tracking**: Monitoring which scripts are actively updated
- **Research**: Analyzing the norns script ecosystem
- **Documentation**: Creating curated lists of scripts with specific features
