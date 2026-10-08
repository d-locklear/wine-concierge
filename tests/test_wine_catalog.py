import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psycopg
import pytest

import app as concierge
import wine_catalog as catalog


@pytest.fixture
def portfolio():
    return json.loads((Path(__file__).resolve().parents[1] / 'data/wine_catalog_2026.json').read_text())


def test_portfolio_facts_and_unknown_commercial_fields(portfolio):
    wines = catalog.validate_catalog(portfolio)
    assert len(wines) == 13
    autumn = next(w for w in wines if w['slug'] == 'autumn-in-a-bottle')
    assert autumn['abv_percent'] == 12
    lumbee = next(w for w in wines if w['slug'] == 'lumbee-river-red')
    assert 'wine_type' not in lumbee
    assert 'blueberry, blackberry and strawberry' in lumbee['description']
    for wine in wines:
        public = catalog.public_wine(wine)
        assert public['availability'] == 'unknown'
        assert public['retail_price_cents'] is None
        assert public['purchase_url'] is None
        assert 'review_notes' not in public
        assert 'source_document' not in public


@pytest.mark.parametrize('field,value', [
    ('unitCost', 6.25), ('retail_price_cents', -1), ('abv_percent', float('nan')),
    ('abv_percent', True), ('purchase_url', 'https://vinoshipper.com.evil.test/buy'),
    ('purchase_url', 'javascript:alert(1)'), ('availability', 'maybe'),
    ('active', 'false'), ('upc', '670541954929'), ('source_page', 0),
])
def test_rejects_unsafe_or_invalid_imports(portfolio, field, value):
    portfolio['wines'][0][field] = value
    with pytest.raises(ValueError):
        catalog.validate_catalog(portfolio)


def test_rejects_duplicates_before_connecting(portfolio):
    portfolio['wines'].append(copy.deepcopy(portfolio['wines'][0]))
    with patch.object(catalog.psycopg, 'connect') as connect:
        with pytest.raises(ValueError):
            catalog.import_catalog(portfolio)
    connect.assert_not_called()


def test_bootstrap_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv('WINE_CATALOG_BOOTSTRAP', raising=False)
    with patch.object(catalog, 'import_catalog') as importer:
        assert catalog.bootstrap_catalog() is None
    importer.assert_not_called()


def test_bootstrap_imports_bundled_portfolio_once(monkeypatch, portfolio):
    monkeypatch.setenv('WINE_CATALOG_BOOTSTRAP', '1')
    with patch.object(catalog, 'import_catalog', return_value={'verified': 13}) as importer:
        assert catalog.bootstrap_catalog() == {'verified': 13}
    importer.assert_called_once_with(portfolio, skip_if_imported=True)


def test_bootstrap_failure_hides_credentials(monkeypatch):
    monkeypatch.setenv('WINE_CATALOG_BOOTSTRAP', '1')
    with patch.object(catalog, 'import_catalog', side_effect=RuntimeError('secret-db-password')):
        with pytest.raises(RuntimeError, match='deployment import failed') as failure:
            catalog.bootstrap_catalog()
    assert 'secret' not in str(failure.value)
    assert failure.value.__suppress_context__


def test_completed_bootstrap_does_not_overwrite_later_edits(monkeypatch, portfolio):
    monkeypatch.setenv('WINE_DATABASE_URL', 'postgresql://unused')
    conn = MagicMock()
    conn.execute.side_effect = [
        MagicMock(), MagicMock(),
        MagicMock(fetchone=lambda: {'id': 1}),
        MagicMock(fetchall=lambda: [{'slug': w['slug']} for w in portfolio['wines']]),
    ]
    with patch.object(catalog.psycopg, 'connect') as connect:
        connect.return_value.__enter__.return_value = conn
        assert catalog.import_catalog(portfolio, skip_if_imported=True)['imported'] == 0
    assert not any('INSERT' in call.args[0] for call in conn.execute.call_args_list)


def test_missing_bootstrap_record_is_restored(monkeypatch, portfolio):
    monkeypatch.setenv('WINE_DATABASE_URL', 'postgresql://unused')
    conn = MagicMock()
    conn.execute.side_effect = [
        MagicMock(), MagicMock(), MagicMock(fetchone=lambda: {'id': 1}),
        MagicMock(fetchall=lambda: []),
        *[MagicMock() for _ in portfolio['wines']],
        MagicMock(fetchall=lambda: [{'slug': w['slug'], 'data': w} for w in portfolio['wines']]),
        MagicMock(),
    ]
    with patch.object(catalog.psycopg, 'connect') as connect:
        connect.return_value.__enter__.return_value = conn
        assert catalog.import_catalog(portfolio, skip_if_imported=True)['imported'] == 13


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('WINE_CATALOG_SOURCE', 'postgres')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    return concierge.app.test_client()


@pytest.mark.parametrize('body', [None, [], 'hello', {}, {'prompt': 1}, {'prompt': '   '}, {'prompt': 'x' * 2001}])
def test_invalid_questions_do_not_load_data_or_bill_api(client, body):
    with patch.object(concierge, 'load_catalog') as load, patch.object(concierge, 'OpenAI') as api:
        assert client.post('/ask', json=body).status_code == 400
    load.assert_not_called()
    api.assert_not_called()


def test_database_failure_is_sanitized_and_does_not_call_openai(client):
    with patch.object(catalog.psycopg, 'connect', side_effect=RuntimeError('postgres://secret:password@host')):
        with patch.object(concierge, 'OpenAI') as api:
            response = client.post('/ask', json={'prompt': 'Wine for barbecue?'})
            assert response.status_code == 503
            assert b'password' not in response.data
            assert client.get('/health').status_code == 503
    api.assert_not_called()


def test_question_body_limit_does_not_limit_assistant_audio(client):
    assert concierge.app.config['MAX_CONTENT_LENGTH'] is None
    assert client.post('/ask', json={'prompt': 'x' * 20000}).status_code == 413


def model_result(answer):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])


def test_recommendation_returns_catalog_links_and_compatible_text(client, portfolio):
    wine = catalog.public_wine(portfolio['wines'][0])
    wine['purchase_url'] = 'https://vinoshipper.com/shop/test-winery/test-wine'
    wine['retail_price_cents'] = 1000
    api = MagicMock()
    api.chat.completions.create.return_value = model_result({'response': 'Try Love in a Bottle.', 'wine_slugs': [wine['slug']]})
    with patch.object(concierge, 'load_catalog', return_value=[wine]), patch.object(concierge, 'OpenAI', return_value=api):
        response = client.post('/ask', json={'prompt': 'I like peach.'})
    assert response.status_code == 200
    assert response.json == {'response': 'Try Love in a Bottle.', 'wines': [wine]}
    assert 'source_document' not in api.chat.completions.create.call_args.kwargs['messages'][1]['content']


@pytest.mark.parametrize('answer', [
    {'response': 'Try a made-up wine.', 'wine_slugs': ['imaginary-wine']},
    {'response': 'Try Love.', 'wine_slugs': ['love-in-a-bottle', 'love-in-a-bottle']},
    {'response': '', 'wine_slugs': []}, {'response': 'Try Love.', 'wine_slugs': [None]},
    {'response': 'Try Love.', 'wine_slugs': [], 'purchase_url': 'https://evil.test'},
])
def test_rejects_invalid_model_recommendations(client, portfolio, answer):
    api = MagicMock()
    api.chat.completions.create.return_value = model_result(answer)
    with patch.object(concierge, 'load_catalog', return_value=[catalog.public_wine(portfolio['wines'][0])]), patch.object(concierge, 'OpenAI', return_value=api):
        assert client.post('/ask', json={'prompt': 'Suggest wine.'}).status_code == 502


def test_no_match_is_an_explicit_answer(client, portfolio):
    api = MagicMock()
    api.chat.completions.create.return_value = model_result({'response': 'No dry wines are confirmed in this catalog.', 'wine_slugs': []})
    with patch.object(concierge, 'load_catalog', return_value=[catalog.public_wine(portfolio['wines'][0])]), patch.object(concierge, 'OpenAI', return_value=api):
        response = client.post('/ask', json={'prompt': 'A dry wine?'})
    assert response.status_code == 200
    assert response.json['wines'] == []


def test_postgres_mode_never_falls_back_to_sheets(monkeypatch):
    monkeypatch.setenv('WINE_CATALOG_SOURCE', 'postgres')
    with patch.object(catalog, 'load_postgres_catalog', side_effect=CatalogError), patch.object(catalog, 'load_google_sheets_catalog') as sheets:
        with pytest.raises(catalog.CatalogUnavailable):
            catalog.load_catalog()
    sheets.assert_not_called()


class CatalogError(Exception):
    pass


@pytest.fixture
def test_database(monkeypatch):
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a disposable Postgres database')
    monkeypatch.setenv('WINE_DATABASE_URL', url)
    monkeypatch.setenv('WINE_CATALOG_SOURCE', 'postgres')
    with psycopg.connect(url) as conn:
        if conn.execute("SELECT to_regnamespace('wine_concierge')").fetchone()[0] is not None:
            pytest.fail('Integration tests require a fresh disposable database; schema already exists')
    yield url
    with psycopg.connect(url) as conn:
        conn.execute('DROP SCHEMA IF EXISTS wine_concierge CASCADE')


def test_real_postgres_import_repeat_preserve_fields_filter_and_atomic_rollback(test_database, portfolio):
    # A private memory table sentinel must stay outside every public response.
    with psycopg.connect(test_database) as conn:
        conn.execute('CREATE TABLE public.catalog_test_private (secret TEXT)')
        conn.execute("INSERT INTO public.catalog_test_private VALUES ('private customer details')")
    try:
        result = catalog.import_catalog(portfolio)
        assert result['verified'] == 13
        assert len(catalog.load_catalog()) == 13
        update = copy.deepcopy(portfolio)
        update['wines'][0]['retail_price_cents'] = 1000
        update['wines'][0]['purchase_url'] = 'https://vinoshipper.com/shop/test-winery/test-wine'
        catalog.import_catalog(update)
        catalog.import_catalog(portfolio)
        with psycopg.connect(test_database) as conn:
            assert conn.execute('SELECT count(*) FROM wine_concierge.wines').fetchone()[0] == 13
            assert conn.execute('SELECT count(*) FROM wine_concierge.catalog_imports').fetchone()[0] == 3
            assert conn.execute('SELECT secret FROM public.catalog_test_private').fetchone()[0] == 'private customer details'
        love = next(w for w in catalog.load_catalog() if w['slug'] == 'love-in-a-bottle')
        assert love['retail_price_cents'] == 1000
        assert 'source_document' not in love
        # The first change must roll back when the second row conflicts with an existing UPC.
        bad = copy.deepcopy(portfolio)
        bad['wines'] = bad['wines'][:2]
        bad['wines'][0]['description'] = 'Must roll back'
        bad['wines'][1]['upc'] = portfolio['wines'][2]['upc']
        with pytest.raises(psycopg.errors.UniqueViolation):
            catalog.import_catalog(bad)
        assert next(w for w in catalog.load_catalog() if w['slug'] == 'love-in-a-bottle')['description'] == portfolio['wines'][0]['description']
        with psycopg.connect(test_database) as conn:
            assert conn.execute('SELECT count(*) FROM wine_concierge.catalog_imports').fetchone()[0] == 3
        update['wines'][0]['availability'] = 'unavailable'
        update['wines'][1]['active'] = False
        catalog.import_catalog(update)
        assert len(catalog.load_catalog()) == 11
    finally:
        with psycopg.connect(test_database) as conn:
            conn.execute('DROP TABLE public.catalog_test_private')
