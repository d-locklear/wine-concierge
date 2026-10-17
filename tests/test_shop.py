import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import app
import wine_catalog as catalog


@pytest.fixture
def snapshot():
    return json.loads((Path(__file__).resolve().parents[1] / 'data/wine_shop_2026-10-17.json').read_text())


def test_shop_snapshot_keeps_winery_stock_and_prices_unknown(snapshot):
    wines = catalog.validate_catalog(snapshot)
    assert len(wines) == 9
    for wine in wines:
        public = catalog.public_wine(wine)
        assert public['availability'] == 'unknown'
        assert public['retail_price_cents'] is None
        assert public['online_checked_on'] == '2026-10-17'
        assert public['purchase_url'] == wine['online_source_url']
        assert 'online_source_url' not in public
    christmas = next(w for w in wines if w['slug'] == 'christmas-in-a-bottle')
    assert christmas['online_status'] == 'sold_out'
    raspberry = next(w for w in wines if w['slug'] == 'raspberry-rose')
    assert raspberry['online_price_cents'] == 1500
    assert raspberry['abv_percent'] == 9


@pytest.mark.parametrize('field,value', [
    ('online_price_cents', -1), ('online_price_cents', True),
    ('online_status', 'available-at-winery'), ('online_checked_on', 'tomorrow'),
    ('online_checked_on', '2099-01-01'), ('online_checked_on', None),
    ('online_source_url', 'https://evil.test/wine'),
])
def test_shop_snapshot_validation(snapshot, field, value):
    snapshot['wines'][0][field] = value
    with pytest.raises(ValueError):
        catalog.validate_catalog(snapshot)


def test_online_price_requires_source_and_date(snapshot):
    for field in ('online_source_url', 'online_checked_on'):
        bad = copy.deepcopy(snapshot)
        del bad['wines'][0][field]
        with pytest.raises(ValueError):
            catalog.validate_catalog(bad)


def test_shop_bootstrap_explicit_and_idempotent(monkeypatch):
    monkeypatch.delenv('WINE_SHOP_BOOTSTRAP', raising=False)
    with patch.object(catalog, 'import_catalog') as importer:
        catalog.bootstrap_shop_catalog()
        importer.assert_not_called()
        monkeypatch.setenv('WINE_SHOP_BOOTSTRAP', '1')
        catalog.bootstrap_shop_catalog()
        assert importer.call_args.kwargs == {'skip_if_imported': True}
        assert len(importer.call_args.args[0]['wines']) == 9


def test_shop_bootstrap_sanitizes_failures(monkeypatch):
    monkeypatch.setenv('WINE_SHOP_BOOTSTRAP', '1')
    with patch.object(catalog, 'import_catalog', side_effect=RuntimeError('postgres://secret')):
        with pytest.raises(RuntimeError, match='Wine shop deployment import failed') as error:
            catalog.bootstrap_shop_catalog()
    assert error.value.__suppress_context__
    assert 'secret' not in str(error.value)


def test_customer_pages_and_assets():
    client = app.app.test_client()
    for route in ('/', '/embed'):
        response = client.get(route)
        assert response.status_code == 200
        assert b'Find your next favorite' in response.data
        assert b'join-our-club' in response.data
        assert b'concierge.js' in response.data
    assert b'embedded' in client.get('/embed').data
    for asset in ('concierge.js', 'concierge.css'):
        assert client.get('/static/' + asset).status_code == 200
