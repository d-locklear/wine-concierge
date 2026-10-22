"""Reviewed public buying locations; listing is never a live stock claim."""
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlencode, urlparse

DIRECTORY = Path(__file__).parent / 'data' / 'purchase_locations.json'
ALLOWED_HOSTS = {'locklearwinery.com', 'www.locklearwinery.com', 'vinoshipper.com'}
FIELDS = {'id', 'name', 'kind', 'address', 'city', 'state', 'postal_code', 'phone',
          'url', 'source_url', 'checked_on', 'active'}


def _safe_url(value):
    url = urlparse(value)
    return (url.scheme == 'https' and url.hostname in ALLOWED_HOSTS
            and not url.username and not url.password)


def load_locations(query=''):
    rows, seen = [], set()
    for record in json.loads(DIRECTORY.read_text())['locations']:
        if (set(record) - FIELDS or record.get('kind') not in {'winery', 'retailer', 'market', 'online'}
                or not all(isinstance(record.get(k), str) and record[k].strip()
                           for k in ('id', 'name', 'url', 'source_url', 'checked_on'))
                or record['id'] in seen or not _safe_url(record['url'])
                or not _safe_url(record['source_url']) or type(record.get('active')) is not bool):
            raise ValueError('Invalid public location record')
        seen.add(record['id'])
        checked = date.fromisoformat(record['checked_on'])
        # Expired locations disappear until their public details are reconfirmed.
        if not record['active'] or not 0 <= (date.today() - checked).days <= 180:
            continue
        if record['kind'] != 'online' and not all(isinstance(record.get(k), str) and record[k].strip()
                for k in ('address', 'city', 'state', 'postal_code')):
            raise ValueError('Physical location requires a full public address')
        searchable = ' '.join(record.get(k, '') for k in ('name', 'address', 'city', 'state', 'postal_code')).casefold()
        if query and record['kind'] != 'online' and query.casefold() not in searchable:
            continue
        row = {k: v for k, v in record.items() if k not in {'source_url', 'active'}}
        if record['kind'] != 'online':
            address = ', '.join(record[k] for k in ('name', 'address', 'city', 'state', 'postal_code'))
            row['directions_url'] = 'https://www.google.com/maps/search/?' + urlencode({'api': 1, 'query': address})
        rows.append(row)
    return rows


def is_location_question(prompt):
    return bool(re.search(
        r'\bwhere\b.*\b(buy|find|get|purchase|sold|available)\b|'
        r'\b(near me|nearest|closest|retailers?|stockists?|where to buy)\b|'
        r'\b(stores?|shops?|locations?)\b.*\b(carry|carries|sell|stock|wines?)\b|'
        r'\b(buy|purchase|sold|available|carry|carries|sell|find)\b.*\b(near|in|at|stores?|shops?)\b',
        prompt, re.I))


def location_answer(query=''):
    locations = load_locations(query)
    physical = [r for r in locations if r['kind'] != 'online']
    lines = []
    if query and not physical:
        lines.append(f'I do not yet have a confirmed physical store listing matching "{query}" in our directory.')
    for row in physical:
        lines.append(f"Find our wines at {row['name']}, {row['address']}, {row['city']}, {row['state']} {row['postal_code']}.")
    if any(r['kind'] == 'online' for r in locations):
        lines.append('You can also browse our online shop; check shipping eligibility and availability there.')
    lines.append('Call the winery at 910-316-0767 for help finding another retailer. Call ahead for the wine you want; a location listing does not confirm current bottle stock.')
    return {'response': ' '.join(lines), 'wines': [], 'locations': locations}
