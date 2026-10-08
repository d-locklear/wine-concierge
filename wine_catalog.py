"""Customer-safe wine records, kept separate from private assistant memory."""

import hashlib
import json
import math
import os
import re
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS wine_concierge;
CREATE TABLE IF NOT EXISTS wine_concierge.wines (
    slug TEXT PRIMARY KEY,
    data JSONB NOT NULL CHECK (jsonb_typeof(data) = 'object'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS wines_upc_unique
    ON wine_concierge.wines ((data->>'upc'));
CREATE TABLE IF NOT EXISTS wine_concierge.catalog_imports (
    id BIGSERIAL PRIMARY KEY,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_sha256 TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    source_documents JSONB NOT NULL
);
"""

PUBLIC_FIELDS = (
    'slug', 'name', 'description', 'wine_type', 'style', 'sweetness',
    'flavor_profile', 'tasting_notes', 'abv_percent', 'bottle_ml', 'serving',
    'pairings', 'retail_price_cents', 'purchase_url', 'availability',
)
TEXT_FIELDS = (
    'name', 'description', 'wine_type', 'style', 'sweetness', 'flavor_profile',
    'tasting_notes', 'serving', 'pairings', 'source_document', 'source_version', 'review_notes',
)
ALLOWED_FIELDS = set(PUBLIC_FIELDS) | {
    'upc', 'source_document', 'source_version', 'source_page', 'review_notes', 'active',
}


class CatalogUnavailable(Exception):
    pass


def public_wine(item):
    """An explicit allowlist prevents provenance or private data entering /ask."""
    result = {k: item[k] for k in PUBLIC_FIELDS if k in item}
    result.setdefault('availability', 'unknown')
    result.setdefault('retail_price_cents', None)
    result.setdefault('purchase_url', None)
    return result


def validate_catalog(document):
    if not isinstance(document, dict) or set(document) != {'wines'}:
        raise ValueError("Catalog must contain only a 'wines' array")
    items = document['wines']
    if not isinstance(items, list) or not 1 <= len(items) <= 1000:
        raise ValueError('Catalog must contain 1–1000 wines')
    slugs, upcs, names, cleaned = set(), set(), set(), []
    for index, raw in enumerate(items, 1):
        label = f'Wine {index}'
        if not isinstance(raw, dict) or set(raw) - ALLOWED_FIELDS:
            raise ValueError(f'{label}: unknown fields; do not import wholesale or private data')
        item = dict(raw)
        slug = item.get('slug')
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) or len(slug) > 100:
            raise ValueError(f'{label}: invalid slug')
        if slug in slugs:
            raise ValueError(f'{label}: duplicate slug {slug}')
        slugs.add(slug)
        for key in TEXT_FIELDS:
            if key not in item:
                continue
            value = item[key]
            if not isinstance(value, str) or not value.strip() or len(value) > 6000:
                raise ValueError(f'{label}: invalid {key}')
            item[key] = value.strip()
        for key in ('name', 'description', 'source_document'):
            if key not in item:
                raise ValueError(f'{label}: {key} is required')
        name = item['name'].casefold()
        if name in names:
            raise ValueError(f'{label}: duplicate name')
        names.add(name)
        upc = item.get('upc')
        if upc is not None:
            if not isinstance(upc, str) or not re.fullmatch(r'\d{12}', upc):
                raise ValueError(f'{label}: UPC must be a 12-digit string')
            check = (10 - sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(upc[:11])) % 10) % 10
            if int(upc[-1]) != check or upc in upcs:
                raise ValueError(f'{label}: invalid or duplicate UPC')
            upcs.add(upc)
        if 'abv_percent' in item:
            abv = item['abv_percent']
            if isinstance(abv, bool) or not isinstance(abv, (int, float)) or not math.isfinite(abv) or not 0 <= abv <= 100:
                raise ValueError(f'{label}: invalid ABV')
        for key in ('bottle_ml', 'source_page', 'retail_price_cents'):
            value = item.get(key)
            if value is not None and (type(value) is not int or value < (0 if key == 'retail_price_cents' else 1)):
                raise ValueError(f'{label}: invalid {key}')
        if 'availability' in item and item['availability'] not in ('unknown', 'available', 'unavailable'):
            raise ValueError(f'{label}: invalid availability')
        if 'active' in item and type(item['active']) is not bool:
            raise ValueError(f'{label}: active must be boolean')
        url = item.get('purchase_url')
        if url is not None:
            if not isinstance(url, str):
                raise ValueError(f'{label}: invalid purchase URL')
            parsed = urlparse(url)
            host = parsed.hostname or ''
            if parsed.scheme != 'https' or parsed.username or parsed.password or not (
                host in ('vinoshipper.com', 'locklearwinery.com', 'www.locklearwinery.com')
                or host.endswith('.vinoshipper.com')
            ):
                raise ValueError(f'{label}: purchase URL must be an approved HTTPS winery or Vinoshipper link')
        cleaned.append(item)
    return cleaned


def database_url():
    url = os.getenv('WINE_DATABASE_URL') or os.getenv('DATABASE_URL')
    if not url:
        raise CatalogUnavailable('Wine database is not configured')
    return url


def import_catalog(document):
    """Validate first, then atomically upsert and verify. Never delete absent wines."""
    items = validate_catalog(document)
    checksum = hashlib.sha256(json.dumps(items, sort_keys=True, allow_nan=False).encode()).hexdigest()
    with psycopg.connect(database_url(), connect_timeout=10, row_factory=dict_row, prepare_threshold=None) as conn:
        conn.execute(SCHEMA)
        conn.execute('LOCK TABLE wine_concierge.wines IN SHARE ROW EXCLUSIVE MODE')
        for item in items:
            conn.execute(
                """INSERT INTO wine_concierge.wines (slug, data) VALUES (%s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                    data = wine_concierge.wines.data || EXCLUDED.data, updated_at = now()""",
                (item['slug'], Jsonb(item)),
            )
        rows = conn.execute(
            'SELECT slug, data FROM wine_concierge.wines WHERE slug = ANY(%s)',
            ([w['slug'] for w in items],),
        ).fetchall()
        stored = {r['slug']: r['data'] for r in rows}
        if len(stored) != len(items) or any(
            any(stored[w['slug']].get(k) != v for k, v in w.items()) for w in items
        ):
            raise RuntimeError('Catalog verification failed; transaction rolled back')
        conn.execute(
            """INSERT INTO wine_concierge.catalog_imports
            (content_sha256, record_count, source_documents) VALUES (%s, %s, %s)""",
            (checksum, len(items), Jsonb(sorted({w['source_document'] for w in items}))),
        )
    return {'imported': len(items), 'verified': len(items), 'sha256': checksum}


def load_postgres_catalog():
    # Runtime reads never create tables and never access assistant memory.
    with psycopg.connect(database_url(), connect_timeout=10, row_factory=dict_row, prepare_threshold=None) as conn:
        rows = conn.execute('SELECT data FROM wine_concierge.wines ORDER BY slug').fetchall()
    return [public_wine(r['data']) for r in rows
            if r['data'].get('active', True) and r['data'].get('availability') != 'unavailable']


def load_google_sheets_catalog():
    # Explicit migration fallback, initialized only when requested.
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    credentials = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if not credentials:
        raise CatalogUnavailable('Google Sheets is not configured')
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(credentials), [
        'https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive',
    ])
    records = gspread.authorize(creds).open('Locklear Wine Data').sheet1.get_all_records()
    wines, seen = [], set()
    for row in records:
        name = str(row.get('Wine Name') or '').strip()
        if not name:
            continue
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        if not slug or slug in seen:
            raise CatalogUnavailable('Google Sheets contains duplicate wine names')
        seen.add(slug)
        wines.append(public_wine({
            'slug': slug, 'name': name, 'flavor_profile': str(row.get('Flavor Profile') or ''),
            'sweetness': str(row.get('Sweetness') or ''), 'pairings': str(row.get('Pairings') or ''),
        }))
    return wines


def catalog_source():
    source = os.getenv('WINE_CATALOG_SOURCE', 'google_sheets')
    if source not in ('postgres', 'google_sheets'):
        raise CatalogUnavailable('Invalid catalog source')
    return source


def load_catalog():
    try:
        wines = load_postgres_catalog() if catalog_source() == 'postgres' else load_google_sheets_catalog()
        if not wines:
            raise CatalogUnavailable('Wine catalog is empty')
        return wines
    except CatalogUnavailable:
        raise
    except Exception as exc:
        raise CatalogUnavailable('Wine catalog is unavailable') from exc
