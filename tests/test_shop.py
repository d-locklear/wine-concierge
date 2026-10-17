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


def test_structured_output_restricts_model_to_current_catalog(monkeypatch, snapshot):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    monkeypatch.delenv('CONCIERGE_MODEL', raising=False)
    api = MagicMock()
    api.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"response":"Try Raspberry Rosé.","wine_slugs":["raspberry-rose"]}'))])
    wines = [catalog.public_wine(snapshot['wines'][-1])]
    with patch.object(app, 'OpenAI', return_value=api):
        answer = app.recommend_wine('Wine for salmon?', wines)
    arguments = api.chat.completions.create.call_args.kwargs
    assert arguments['model'] == 'gpt-4o-mini'
    schema = arguments['response_format']['json_schema']
    assert schema['strict'] is True
    assert schema['schema']['additionalProperties'] is False
    assert schema['schema']['properties']['wine_slugs']['items']['enum'] == ['raspberry-rose']
    assert answer['wines'] == wines


def test_legacy_model_override_does_not_receive_unsupported_schema(monkeypatch, snapshot):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    monkeypatch.setenv('CONCIERGE_MODEL', 'gpt-4')
    api = MagicMock()
    api.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"response":"Please contact us.","wine_slugs":[]}'))])
    with patch.object(app, 'OpenAI', return_value=api):
        app.recommend_wine('A dry wine?', [catalog.public_wine(snapshot['wines'][0])])
    assert 'response_format' not in api.chat.completions.create.call_args.kwargs
