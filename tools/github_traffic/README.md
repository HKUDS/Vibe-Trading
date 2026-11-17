# Clone traffic archive

The `Archive clone traffic` workflow collects the entire available 14-day window
daily at 02:23 UTC (10:23 Singapore).
It also supports manual dispatch. Scheduling starts once the workflow is on main.

## One-time credential setup

Create a fine-grained PAT owned by HKUDS, restricted to Vibe-Trading, with
**Administration: Read-only** (Metadata read is implicit). If organization approval
is required, obtain it. Save it as the repository Actions secret
`TRAFFIC_READ_TOKEN`. Never commit it. Set an expiry reminder and replace the secret
before expiry. A GitHub App with the same read permission can replace this later.
The built-in GITHUB_TOKEN writes the data branch; the PAT only reads traffic.

Data is published on the **public `traffic-archive` branch**:

- `snapshots/`: immutable complete API responses with repository ID and retrieval time.
- `daily.json`: one row per UTC date, newest observation replaces the old count,
  including downward revisions. Repository ID guards against mixing repositories.
- `summary.json`: covered interval, cumulative clone events, missing dates and freshness.

Counts are not users. Daily unique-cloner counts are never added together.
This is the observed interval, not lifetime history. Missing dates are not zero.
Each run re-fetches all 14 days, so a missed run normally repairs itself later.
Current/recent days remain provisional; GitHub can revise the source.
Valid data is committed before a missing-day/stale-source failure is reported.
Malformed responses fail without replacing daily totals. A failed push fails the run.
Concurrency serializes archive writers; no force push is used.

Watch failed Actions runs and configure GitHub Actions notifications. Actions cron
can be delayed/dropped or disabled after inactivity: failure notifications alone
cannot detect a run that never starts. An independent external monitor should check
`last_successful_collection` every 6 hours and alert after 24 hours without success.
That external monitor is **not deployed by this workflow**. An outage beyond the
14-day source window, or missing data at GitHub, can cause unrecoverable gaps.
Keep an independent backup of the archive branch for protection against deletion.

Run tests: `python3 -m unittest discover -s tools/github_traffic -p 'test_*.py'`
Run manually: `GH_TOKEN=<read-token> python3 tools/github_traffic/archive.py --repository HKUDS/Vibe-Trading --output /path/to/archive`
