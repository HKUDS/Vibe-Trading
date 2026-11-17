# Clone traffic utility

Daily collection now runs in the private `HKUDS/Vibe-Trading-metrics` repository.
The collector, Actions logs and raw observations are stored there. The public
repository no longer runs the archive workflow or publishes a traffic data branch.
Authorized maintainers can use the private repository's **Archive adoption metrics**
workflow to inspect health or request a manual retry. Its schedule is daily at
02:23 UTC (10:23 Singapore); scheduled Actions can be delayed.

The scripts in this directory remain a standalone utility for clone data:

```sh
python3 -m unittest discover -s tools/github_traffic -p 'test_*.py'
# Supply GH_TOKEN through your environment, never a committed file.
python3 tools/github_traffic/archive.py --repository HKUDS/Vibe-Trading --output /private/archive/path
```

The Traffic API requires Administration: read access. The private collector also
archives views, referrers, popular paths, repository counters, release assets,
PyPI downloads and ClawHub statistics. Complete Traffic JSON responses are retained.

Daily buckets are deduplicated by UTC date, with the newest observation winning.
Fetching the full rolling window allows missed days to be recovered while still
available from GitHub (14 days). Missing dates are reported, not filled with zeros.
Clone counts are events, not people; daily uniques cannot be added to get lifetime
unique users. Referrer/path rolling snapshots likewise cannot be summed.
