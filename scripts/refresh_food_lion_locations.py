"""Refresh NC Food Lion addresses from the public official directory, fail closed."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

ROOT = 'https://stores.foodlion.com/nc'


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs)


def clean(value):
    return ' '.join(unescape(re.sub('<[^>]+>', ' ', value)).split())


def extract_store(html, url, checked_on):
    def field(name):
        match = re.search(r'<(?:span|abbr)[^>]*class="[^"]*Address-' + name + r'\b[^\"]*"[^>]*>(.*?)</(?:span|abbr)>', html, re.S)
        if not match:
            raise ValueError(f'Missing {name}: {url}')
        return clean(match[1])
    address = re.search(r'<address[^>]*itemprop="address"[^>]*>.*?</address>', html, re.S)
    if not address:
        raise ValueError(f'Missing primary address: {url}')
    primary = address[0]
    # Restrict field extraction to the primary store, excluding nearby-store teasers.
    original = html
    html = primary
    street, city, state, postal = [field(k) for k in ('line1', 'city', 'region', 'postalCode')]
    html = original
    phone = re.search(r'itemprop="telephone"[^>]*>(.*?)<', html, re.S)
    title = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    if state != 'NC' or not re.fullmatch(r'\d{5}(?:-\d{4})?', postal) or not phone or not title:
        raise ValueError(f'Invalid NC store: {url}')
    return {'id': 'food-lion-' + hashlib.sha256(url.encode()).hexdigest()[:12],
            'name': clean(title[1]), 'kind': 'retailer', 'address': street, 'city': city,
            'state': state, 'postal_code': postal, 'phone': clean(phone[1]),
            'url': url, 'source_url': url, 'checked_on': checked_on, 'active': True}


def refresh(cache, workers):
    cache = cache / date.today().isoformat()
    cache.mkdir(parents=True, exist_ok=True)
    def fetch(url):
        if urlparse(url).hostname != 'stores.foodlion.com' or not urlparse(url).path.startswith('/nc'):
            raise ValueError('Only official NC directory URLs may be fetched')
        path = cache / (hashlib.sha256(url.encode()).hexdigest() + '.html')
        if path.exists():
            return path.read_text()
        for attempt in range(2):
            try:
                with urlopen(url, timeout=30) as response:
                    if urlparse(response.url).hostname != 'stores.foodlion.com':
                        raise ValueError('Unexpected redirect host')
                    html = response.read().decode()
                if 'Food Lion' not in html:
                    raise ValueError('Unexpected directory document')
                path.write_text(html)
                return html
            except Exception:
                if attempt:
                    raise
    root = fetch(ROOT)
    parser = Links(); parser.feed(root)
    entries = [(urljoin('https://stores.foodlion.com/', a['href']),
                int(a['data-count'].strip('()')))
               for a in parser.links if 'Directory-listLink' in a.get('class', '').split()]
    if not entries or any(n < 1 for _, n in entries):
        raise ValueError('Empty or invalid city directory')
    print(f'Official directory: {len(entries)} city entries, {sum(n for _, n in entries)} store/department pages', flush=True)
    details = {}
    def city_stores(entry):
        url, expected = entry
        if expected == 1:
            return [(url, None)]
        html = fetch(url)
        links = Links(); links.feed(html)
        urls = sorted(set(urljoin(url, a['href']) for a in links.links
                          if 'Teaser-titleLink' in a.get('class', '').split()))
        if len(urls) != expected:
            raise ValueError(f'City listing count mismatch: {url}: {len(urls)} vs {expected}')
        return [(u, None) for u in urls]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, future in enumerate(as_completed([pool.submit(city_stores, e) for e in entries]), 1):
            for url, _ in future.result():
                details[url] = None
            if i % 40 == 0:
                print(f'City entries checked: {i}/{len(entries)}', flush=True)
    expected = sum(n for _, n in entries)
    if len(details) != expected:
        raise ValueError(f'Duplicate/missing store URLs: {len(details)} vs {expected}')
    rows, pharmacies = [], []
    def store(url):
        html = fetch(url)
        row = extract_store(html, url, date.today().isoformat())
        page_title = re.search(r'<title>(.*?)</title>', html, re.S)
        pharmacy = bool(page_title and 'food lion pharmacy' in clean(page_title[1]).casefold())
        return row, pharmacy
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, future in enumerate(as_completed([pool.submit(store, u) for u in details]), 1):
            row, pharmacy = future.result()
            (pharmacies if pharmacy else rows).append(row)
            if i % 40 == 0:
                print(f'Store addresses checked: {i}/{expected}', flush=True)
    rows.sort(key=lambda r: (r['city'].casefold(), r['address'].casefold()))
    addresses = {(r['address'], r['city'], r['postal_code']) for r in rows}
    if len(addresses) != len(rows) or len(rows) + len(pharmacies) != expected:
        raise ValueError('Duplicate or missing grocery records require review')
    return rows, {'city_entries': len(entries), 'directory_pages': expected, 'store_count': len(rows),
                  'excluded_pharmacy_pages': len(pharmacies),
                  'source_url': ROOT, 'checked_on': date.today().isoformat()}


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument('--cache', type=Path, required=True)
    args.add_argument('--output', type=Path, required=True)
    args.add_argument('--workers', type=int, default=6)
    options = args.parse_args()
    records, summary = refresh(options.cache, max(1, min(options.workers, 8)))
    options.output.write_text(json.dumps({'summary': summary, 'locations': records}, indent=2) + '\n')
    print(json.dumps(summary), flush=True)
