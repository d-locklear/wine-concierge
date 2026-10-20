import io
import math
import struct
import subprocess
import wave
from unittest.mock import patch

import imageio_ffmpeg
import pytest
from itsdangerous import TimestampSigner

import app
import concierge_speech as speech


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-provider-secret')
    monkeypatch.setenv('ELEVENLABS_VOICE_ID', 'testVoice1234567890')
    speech._cache.clear()
    speech._requests.clear()
    return app.app.test_client()


def test_only_signed_recommendations_can_generate_audio(client):
    with patch.object(speech, '_generate') as generate:
        for payload in ({'text': 'Read arbitrary text'}, {'token': 'invalid'}):
            assert client.post('/speech', json=payload).status_code == 400
        generate.assert_not_called()
    token = speech.speech_token('Try a sweet peach wine.')
    with patch.object(speech, '_generate', return_value=b'MP3-audio') as generate:
        for _ in range(2):
            result = client.post('/speech', json={'token': token})
            assert result.status_code == 200
            assert result.mimetype == 'audio/mpeg'
            assert result.headers['Cache-Control'] == 'no-store'
        generate.assert_called_once_with('Try a sweet peach wine.')


def test_expired_or_changed_voice_token_is_rejected(client, monkeypatch):
    token = speech.speech_token('Try a sweet peach wine.')
    with patch.object(TimestampSigner, 'get_timestamp', return_value=0):
        expired = speech.speech_token('Expired reply')
    assert client.post('/speech', json={'token': expired}).status_code == 400
    monkeypatch.setenv('ELEVENLABS_VOICE_ID', 'differentVoice123456')
    assert client.post('/speech', json={'token': token}).status_code == 400


def test_provider_failure_does_not_expose_secrets(client):
    with patch.object(speech, '_generate', side_effect=speech.SpeechUnavailable('test-provider-secret')):
        response = client.post('/speech', json={'token': speech.speech_token('Try Peach.')})
    assert response.status_code == 502
    assert b'test-provider-secret' not in response.data
    assert b'read the answer' in response.data


def test_rate_limit_and_concurrent_generation(client):
    with patch.object(speech, '_generate', return_value=b'MP3') as generate:
        for i in range(6):
            assert client.post('/speech', json={'token': speech.speech_token(f'Reply {i}')}).status_code == 200
        assert client.post('/speech', json={'token': speech.speech_token('Reply 7')}).status_code == 429
        assert generate.call_count == 6
    with speech._lock:
        assert client.post('/speech', json={'token': speech.speech_token('Busy')}).status_code == 429


def test_unconfigured_voice_keeps_existing_ask_contract(client, monkeypatch):
    monkeypatch.delenv('ELEVENLABS_API_KEY')
    assert speech.speech_token('Try Peach.') is None
    assert client.post('/speech', json={}).status_code == 503
    with patch.object(app, 'load_catalog', return_value=[{'slug': 'peach'}]), \
         patch.object(app, 'recommend_wine', return_value={'response': 'Try Peach.', 'wines': []}):
        monkeypatch.setenv('OPENAI_API_KEY', 'test')
        assert client.post('/ask', json={'prompt': 'Peach?'}).json == {'response': 'Try Peach.', 'wines': []}


def test_configured_ask_signs_only_the_generated_answer(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test')
    with patch.object(app, 'load_catalog', return_value=[{'slug': 'peach'}]), \
         patch.object(app, 'recommend_wine', return_value={'response': 'Try Peach.', 'wines': []}):
        result = client.post('/ask', json={'prompt': 'User question'}).json
    assert speech._signer().loads(result['speech_token'])['text'] == 'Try Peach.'
    assert speech.speech_token('x' * (speech.MAX_TEXT + 1)) is None
    page = client.get('/embed').data
    assert b'data-custom-voice="true"' in page
    assert b'test-provider-secret' not in page


def test_provider_contract_and_size_bounds(client):
    from unittest.mock import MagicMock
    response = MagicMock()
    response.__enter__.return_value = response
    response.status_code = 200
    response.headers = {'Content-Type': 'audio/mpeg'}
    response.iter_content.return_value = [b'original audio']
    with patch.object(speech.requests, 'post', return_value=response) as post, \
         patch.object(speech, 'lower_pitch', return_value=b'lower audio'):
        assert speech._generate('Try Peach.') == b'lower audio'
    assert post.call_args.kwargs['allow_redirects'] is False
    assert post.call_args.kwargs['json']['text'] == 'Try Peach.'
    response.iter_content.return_value = [b'x' * (speech.MAX_AUDIO + 1)]
    with patch.object(speech.requests, 'post', return_value=response), pytest.raises(speech.SpeechUnavailable):
        speech._generate('Too large')


def test_pitch_is_lowered_without_slowing_speech():
    import numpy as np
    rate, duration = 44100, 2
    source = io.BytesIO()
    with wave.open(source, 'wb') as output:
        output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        output.writeframes(b''.join(struct.pack('<h', int(10000 * math.sin(2 * math.pi * 440 * i / rate)))
                                  for i in range(rate * duration)))
    lowered = speech.lower_pitch(source.getvalue())
    decoded = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', 'pipe:0',
        '-f', 's16le', '-ac', '1', '-ar', str(rate), 'pipe:1'], input=lowered,
        capture_output=True, timeout=5, check=True).stdout
    samples = np.frombuffer(decoded, dtype='<i2')
    assert abs(len(samples) / rate - duration) < 0.08
    center = samples[rate // 2:rate * 3 // 2]
    frequency = np.fft.rfftfreq(len(center), 1 / rate)[np.argmax(abs(np.fft.rfft(center)))]
    assert abs(frequency - 440 * speech.PITCH_RATIO) < 2
