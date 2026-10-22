import json
from datetime import date, timedelta
from unittest.mock import patch

import pytest
import app
import purchase_locations as locations


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
    assert [r['id'] for r in response.json['locations']] == ['winery', 'online']
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
    assert 'not yet have a confirmed physical store listing' in result['response']
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
