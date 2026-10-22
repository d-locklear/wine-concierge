import json
from datetime import date, timedelta
from unittest.mock import patch

import pytest
import app
import purchase_locations as locations

PUBLIC_DIRECTORY = locations.DIRECTORY


@pytest.fixture(autouse=True)
def isolated_directory(tmp_path, monkeypatch):
    data = json.loads(PUBLIC_DIRECTORY.read_text())
    data["locations"] = [r for r in data["locations"] if r["id"] in {"winery", "online"}]
    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(locations, "DIRECTORY", path)


@pytest.mark.parametrize('question', [
    'Where can I buy your wines?', 'Where can I find Peach wine in Cary?',
    'Which stores carry your wines?', 'Do you sell at Food Lion?',
    'Where is your wine available?', 'What is the nearest retailer?',
])
def test_buying_questions_use_verified_directory_without_model(question, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with patch.object(app, 'recommend_wine') as model, patch.object(app, 'load_catalog') as catalog:
        response = app.app.test_client().post('/ask', json={'prompt': question})
    assert response.status_code == 200
    assert response.json['wines'] == []
    expected = ['online'] if 'Cary' in question or 'Food Lion' in question else ['winery', 'online']
    assert [r['id'] for r in response.json['locations']] == expected
    assert 'current bottle stock' in response.json['response']
    assert not any(r['kind'] == 'retailer' for r in response.json['locations'])
    model.assert_not_called()
    catalog.assert_not_called()


@pytest.mark.parametrize('question', ['What pairs with barbecue?', 'Where are your grapes grown?',
    'I like peach flavors', 'Help me choose a holiday wine to buy online.'])
def test_taste_and_product_questions_keep_recommendation_path(question):
    assert not locations.is_location_question(question)


def test_city_zip_and_uncovered_area_do_not_invent_nearby_stores():
    for query in ('Maxton', '28364', 'MAxTON'):
        assert len(locations.location_answer(query)['locations']) == 2
    result = locations.location_answer('Cary')
    assert [r['id'] for r in result['locations']] == ['online']
    assert 'not yet have a separate confirmed street-address match' in result['response']
    assert 'Cary' in result['response']
    assert 'not confirm current bottle stock' in result['response']


def test_location_input_validation_and_voice_token(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-secret')
    monkeypatch.setenv('ELEVENLABS_VOICE_ID', 'testVoice12345')
    client = app.app.test_client()
    for value in ({}, 123, 'x'*121):
        assert client.post('/ask', json={'prompt':'Where to buy?', 'location':value}).status_code == 400
    result = client.post('/ask', json={'prompt':'Looking for wine', 'location':'28364'}).json
    from concierge_speech import _signer
    assert _signer().loads(result['speech_token'])['text'] == result['response']
    assert 'test-secret' not in json.dumps(result)


def test_stale_inactive_and_unsafe_records(tmp_path, monkeypatch):
    data = json.loads(locations.DIRECTORY.read_text())
    path = tmp_path / 'locations.json'
    monkeypatch.setattr(locations, 'DIRECTORY', path)
    data['locations'][0]['checked_on'] = (date.today()-timedelta(days=181)).isoformat()
    data['locations'][1]['active'] = False
    path.write_text(json.dumps(data))
    assert locations.load_locations() == []
    data['locations'][0]['url'] = 'https://locklearwinery.com.evil.example'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        locations.load_locations()
    response = app.app.test_client().post('/ask', json={'prompt':'Where can I buy wine?'})
    assert response.status_code == 503
    assert 'evil.example' not in response.text


def test_live_directory_is_public_and_owner_confirmed_food_lion_is_statewide(monkeypatch):
    monkeypatch.setattr(locations, 'DIRECTORY', PUBLIC_DIRECTORY)
    all_rows = locations.load_locations()
    assert len(all_rows) == 549
    assert sum(r["url"].startswith("https://stores.foodlion.com/nc/") for r in all_rows) == 509
    assert not any('Johnson Brothers' in r['name'] for r in all_rows)
    result = locations.location_answer('Cary')
    assert [r['id'] for r in result['locations'][:2]] == ['food-lion-nc', 'online']
    assert len([r for r in result['locations'] if r['kind'] == 'retailer']) == 3
    assert {r['city'] for r in result['locations'] if r['kind'] == 'retailer'} == {'Cary'}
    assert 'all Food Lion stores in North Carolina' in result['response']
    assert 'stock vary' in result['response']
    assert len(result['response']) <= 1800
    for query in ('Fayetteville', 'Sanford', 'Lumberton', 'Maxton', 'Goldsboro', '28372', ''):
        assert len(locations.location_answer(query)['response']) <= 1800
    assert 'all Walmart' not in result['response']


def test_prompt_city_filter_and_existing_stock_caveat(monkeypatch):
    monkeypatch.setattr(locations, 'DIRECTORY', PUBLIC_DIRECTORY)
    result = app.app.test_client().post('/ask', json={'prompt':'Where can I buy your wine in Lumberton?'}).json
    assert {r['city'] for r in result['locations'] if r['kind']=='retailer'} == {'Lumberton'}
    assert 'not confirm current bottle stock' in result['response']
    assert 'winery' not in [r['id'] for r in result['locations']]
    assert locations.load_locations('Lumberton, NC')
    assert any(r.get('city') == 'Saint Pauls' for r in locations.load_locations('St. Pauls'))


def test_large_directory_returns_bounded_cards_and_all_records_are_searchable(monkeypatch):
    monkeypatch.setattr(locations, 'DIRECTORY', PUBLIC_DIRECTORY)
    result = locations.location_answer()
    assert len(result['locations']) == 24
    assert result['location_count'] == 549
    assert '24 of 549' in result['response']
    rows = locations.load_locations()
    for row in rows:
        if row['url'].startswith('https://stores.foodlion.com/nc/'):
            matches = locations.load_locations(row['postal_code'])
            assert row['id'] in {r['id'] for r in matches}
    assert not any(r.get('city') != 'Cary' for r in locations.load_locations('Cary, North Carolina') if r['kind']=='retailer')
