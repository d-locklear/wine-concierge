from unittest.mock import Mock, patch
import pytest
import requests
import preview_app


def test_preview_serves_charlie_and_only_guest_routes():
    client = preview_app.app.test_client()
    for route in ('/', '/embed'):
        response = client.get(route)
        assert response.status_code == 200
        assert b'Charlie, our AI wine concierge' in response.data
        assert b'Test preview' in response.data
        assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert client.get('/health').json == {'status': 'ready', 'mode': 'guest-preview'}
    assert not any(rule.rule.startswith('/assistant') for rule in preview_app.app.url_map.iter_rules())


@pytest.mark.parametrize('data', [None, [], {}, {'prompt':''}, {'prompt':1}, {'prompt':'x'*2001}])
def test_invalid_questions_never_reach_backend(data):
    with patch('preview_app.requests.post') as post:
        assert preview_app.app.test_client().post('/ask', json=data).status_code == 400
        post.assert_not_called()


def test_forwards_only_guest_question_to_fixed_backend():
    backend = Mock(status_code=200)
    backend.json.return_value = {'response':'Try peach.', 'wines':[]}
    with patch('preview_app.requests.post', return_value=backend) as post:
        response = preview_app.app.test_client().post('/ask', json={'prompt':' peach ', 'private':'ignore'}, headers={'Authorization':'Bearer never-forward'})
    assert response.status_code == 200
    assert response.json == {'response':'Try peach.', 'wines':[]}
    post.assert_called_once_with('https://wine-concierge.onrender.com/ask', json={'prompt':'peach'}, timeout=(5,55))


@pytest.mark.parametrize('failure', ['network','malformed','unavailable'])
def test_backend_failure_keeps_preview_available(failure):
    response = Mock(status_code=200)
    response.json.return_value = []
    if failure == 'unavailable': response.status_code=502
    with patch('preview_app.requests.post', return_value=response, side_effect=requests.Timeout() if failure=='network' else None):
        result=preview_app.app.test_client().post('/ask', json={'prompt':'peach'})
    assert result.status_code == 503
    assert 'error' in result.json


def test_catalog_uses_public_backend_only():
    response=Mock();response.json.return_value={'wines':[{'slug':'peach'}]}
    with patch('preview_app.requests.get', return_value=response) as get:
        result=preview_app.app.test_client().get('/wines')
    assert result.json=={'wines':[{'slug':'peach'}]}
    get.assert_called_once_with('https://wine-concierge.onrender.com/wines', timeout=(5,15))
