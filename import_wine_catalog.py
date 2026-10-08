"""Run from the repository root: python import_wine_catalog.py FILE [--apply]."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from wine_catalog import import_catalog, validate_catalog


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Validate or import the winery catalog into Postgres')
    parser.add_argument('file', type=Path)
    parser.add_argument('--apply', action='store_true', help='Write to database; default is validation only')
    args = parser.parse_args()
    try:
        document = json.loads(args.file.read_text(encoding='utf-8'))
        items = validate_catalog(document)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Catalog validation failed: {exc}\n')
    if not args.apply:
        print(json.dumps({'validated': len(items), 'database_written': False, 'wines': [w['name'] for w in items]}))
        return
    try:
        result = import_catalog(document)
    except Exception as exc:
        parser.exit(1, f'Import failed ({type(exc).__name__}); no partial import was committed. Check database configuration and permissions.\n')
    print(json.dumps({**result, 'database_written': True}))


if __name__ == '__main__':
    main()
