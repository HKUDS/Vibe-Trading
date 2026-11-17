"""Archive clone observations; rebuild daily totals without overlapping-window sums."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request


def request_json(path):
    """Read GitHub JSON with bounded retries and without logging credentials."""
    token = os.environ.get('GH_TOKEN')
    if not token:
        raise ValueError('Configure TRAFFIC_READ_TOKEN (Administration: read) in Actions secrets')
    for attempt in range(3):
        request = urllib.request.Request('https://api.github.com/' + path, headers={
            'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'clone-archive'})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == 2:
                raise ValueError(f'GitHub HTTP {error.code}; check token access/expiry and API availability') from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise ValueError('GitHub request failed after three attempts') from None
        time.sleep(2 ** attempt)


def validate(data):
    """Reject malformed or inconsistent observations before writing anything."""
    if not isinstance(data.get('clones'), list) or not data['clones']:
        raise ValueError('Missing daily clone records; missing is not zero')
    seen = set()
    for row in [data, *data['clones']]:
        if any(type(row.get(key)) is not int or row[key] < 0 for key in ('count', 'uniques')):
            raise ValueError('Invalid clone counts')
        if row['uniques'] > row['count']:
            raise ValueError('Unique cloners exceed clones')
    for row in data['clones']:
        stamp = dt.datetime.strptime(row['timestamp'], '%Y-%m-%dT%H:%M:%SZ')
        if stamp.time() != dt.time() or row['timestamp'] in seen:
            raise ValueError('Duplicate or non-midnight UTC bucket')
        seen.add(row['timestamp'])
    if sum(row['count'] for row in data['clones']) != data['count']:
        raise ValueError('Window total differs from daily sum')


def write_json(path, data):
    """Replace a derived JSON file atomically."""
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2) + '\n')
    temp.replace(path)


def rebuild(root, repo_id, now):
    """Merge observations by repository ID and UTC date, newest observation wins."""
    observations = [json.loads(path.read_text()) for path in (root / 'snapshots').glob('*.json')]
    observations.sort(key=lambda item: dt.datetime.fromisoformat(item['retrieved_at']))
    daily = {}
    for observation in observations:
        if observation['repository_id'] != repo_id:
            raise ValueError('Archive contains a different repository ID')
        validate(observation['data'])
        for row in observation['data']['clones']:
            day = row['timestamp'][:10]
            daily[day] = {'date': day, 'count': row['count'], 'daily_unique_cloners': row['uniques'],
                          'last_observed_at': observation['retrieved_at']}
    days = sorted(daily)
    first, last = dt.date.fromisoformat(days[0]), dt.date.fromisoformat(days[-1])
    missing = [(first + dt.timedelta(days=n)).isoformat() for n in range((last-first).days+1)
               if (first + dt.timedelta(days=n)).isoformat() not in daily]
    lag = (now.date() - last).days
    latest = observations[-1]
    summary = {
        'repository_id': repo_id, 'repository': latest['repository'],
        'last_successful_collection': latest['retrieved_at'],
        'coverage_start': days[0], 'coverage_end': days[-1], 'observed_days': len(days),
        'missing_dates': missing, 'source_lag_days': lag,
        'archived_clone_count': sum(row['count'] for row in daily.values()),
        'latest_window_unique_cloners': latest['data']['uniques'],
        'attention_required': bool(missing) or lag > 3,
        'note': 'Observed UTC dates only, not lifetime history. Latest values may revise earlier counts. '
                'Daily uniques must not be summed as people. Missing dates are not zero.'}
    write_json(root / 'daily.json', [daily[day] for day in days])
    write_json(root / 'summary.json', summary)
    return summary


def main():
    """Collect the complete available window and retain an immutable response."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    meta = request_json(f'repos/{args.repository}')
    data = request_json(f'repos/{args.repository}/traffic/clones?per=day')
    validate(data)
    now = dt.datetime.now(dt.timezone.utc)
    snapshots = args.output / 'snapshots'
    snapshots.mkdir(parents=True, exist_ok=True)
    observation = {'repository': meta['full_name'], 'repository_id': meta['id'],
                   'retrieved_at': now.isoformat(), 'data': data}
    path = snapshots / (now.strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    with path.open('x') as handle:
        json.dump(observation, handle, indent=2)
        handle.write('\n')
    summary = rebuild(args.output, meta['id'], now)
    print(json.dumps(summary, indent=2))
    # The workflow commits valid observations before failing the health check.


if __name__ == '__main__':
    main()
