"""Reviewed public buying locations; listing is never a live stock claim."""
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlencode, urlparse

DIRECTORY = Path(__file__).parent / 'data' / 'purchase_locations.json'
ALLOWED_HOSTS = {'locklearwinery.com', 'www.locklearwinery.com', 'vinoshipper.com', 'stores.foodlion.com', 'www.walmart.com', 'www.lowesfoods.com',
                 'www.carliecs.com', 'freshfoods.us', 'www.pigglywiggly.com', 'www.welltravelledbeer.com'}
FIELDS = {'id', 'name', 'kind', 'address', 'city', 'state', 'postal_code', 'phone',
          'url', 'source_url', 'checked_on', 'active', 'coverage'}


def _safe_url(value):
    url = urlparse(value)
    return (url.scheme == 'https' and url.hostname in ALLOWED_HOSTS
            and not url.username and not url.password)


def load_locations(query=''):
    rows, seen = [], set()
    records = json.loads(DIRECTORY.read_text())['locations']
    city_queries = {normalize(r.get('city', '')) for r in records if r.get('city')}
    for record in records:
        if (set(record) - FIELDS or record.get('kind') not in {'winery', 'retailer', 'market', 'online', 'chain'}
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
        if record['kind'] not in {'online', 'chain'} and not all(isinstance(record.get(k), str) and record[k].strip()
                for k in ('address', 'city', 'state')):
            raise ValueError('Physical location requires a full public address')
        if query and record['kind'] not in {'online', 'chain'} and not matches_query(record, query, city_queries):
            continue
        row = {k: v for k, v in record.items() if k not in {'source_url', 'active'}}
        if record['kind'] not in {'online', 'chain'}:
            address = ', '.join(record.get(k, '') for k in ('name', 'address', 'city', 'state', 'postal_code'))
            row['directions_url'] = 'https://www.google.com/maps/search/?' + urlencode({'api': 1, 'query': address})
        rows.append(row)
    return rows


def normalize(text):
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', text.casefold().replace('st.', 'saint').replace('st pauls', 'saint pauls')).split())


def matches_query(record, query, city_queries=None):
    # Match complete city/state/ZIP fields or store/address text; never rank as nearest.
    query = normalize(query)
    city = normalize(record.get('city', ''))
    city_query = re.sub(r' (?:nc|north carolina)$', '', query)
    if city_queries and city_query in city_queries:
        return city == city_query
    if query == city or query in {city + ' nc', city + ' north carolina'}:
        return True
    if re.fullmatch(r'\d{5}(?: \d{4})?', query):
        return record.get('postal_code', '').split('-')[0] == query[:5]
    searchable = normalize(' '.join(record.get(k, '') for k in ('name', 'address', 'city', 'state')))
    return query in searchable


def query_from_prompt(prompt):
    match = re.search(r'\b(?:near|around|in)\s+([a-zA-Z0-9][a-zA-Z0-9 ,.-]{0,60})[?!.]*$', prompt, re.I)
    if match:
        query = match.group(1).strip(' .?!')
        return '' if query.casefold() in {'me', 'my area'} else query
    for pattern, query in [(r'food\s*lions?', 'Food Lion'), (r'walmart', 'Walmart'), (r'lowe.?s foods?', 'Lowes Foods'), (r'carlie', 'Carlie'), (r'piggly', 'Piggly Wiggly')]:
        if re.search(pattern, prompt, re.I):
            return query
    return ''


def is_location_question(prompt):
    return bool(re.search(
        r'\bfood\s*lions?\b|\bwhere\b.*\b(buy|find|get|purchase|sell|sold|available)\b|'
        r'\b(near me|nearest|closest|retailers?|stockists?|where to buy)\b|'
        r'\b(stores?|shops?|locations?)\b.*\b(carry|carries|sell|stock|wines?)\b|'
        r'\b(buy|get|have|purchase|sold|available|carry|carries|sell|find)\b.*\b(near|in|at|stores?|shops?)\b',
        prompt, re.I))


def location_answer(query=''):
    all_locations = load_locations(query)
    chains = [r for r in all_locations if r['kind'] == 'chain']
    physical = [r for r in all_locations if r['kind'] not in {'online', 'chain'}]
    lines = []
    if chains:
        lines.append('Our wines are carried at all Food Lion stores in North Carolina. Selection and stock vary by store; use the North Carolina store finder below and call ahead for your wine.')
    if query and not physical:
        lines.append(f'I do not yet have a separate confirmed street-address match for "{query}" in our directory. The Food Lion listing covers North Carolina only.')
    if physical:
        lines.append('Other listed buying options include:')
        for row in physical[:3]:
            address = ', '.join(row.get(k, '') for k in ('address', 'city', 'state') if row.get(k))
            lines.append(f"{row['name']}, {address}.")
        if len(physical) > 3:
            lines.append('More locations are shown below. Enter a city, ZIP code or store name to narrow the list.')
    if any(r['kind'] == 'online' for r in all_locations):
        lines.append('You can also browse our online shop; check shipping eligibility and availability there.')
    lines.append('Call 910-316-0767 for help. Call ahead for the wine you want; a location listing does not confirm current bottle stock.')
    displayed = all_locations[:24]
    if len(all_locations) > len(displayed):
        lines.append(f'Showing {len(displayed)} of {len(all_locations)} matching buying options. Enter a city or ZIP code to narrow the list.')
    return {'response': ' '.join(lines), 'wines': [], 'locations': displayed, 'location_count': len(all_locations)}
