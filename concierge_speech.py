"""Bounded speech playback for server-signed public concierge replies."""

import hashlib
import os
import re
import subprocess
import threading
import time
from collections import OrderedDict, deque

import imageio_ffmpeg
import requests
from flask import Blueprint, Response, jsonify, request
from itsdangerous import BadData, URLSafeTimedSerializer

speech_bp = Blueprint('concierge_speech', __name__)
MAX_TEXT = 1800
MAX_AUDIO = 2 * 1024 * 1024
TOKEN_SECONDS = 900
PITCH_RATIO = 0.971531941  # Half a semitone lower, without slowing speech.
_lock = threading.Lock()
_requests = deque()
_cache = OrderedDict()


class SpeechUnavailable(Exception):
    pass


def configured():
    return bool(os.getenv('ELEVENLABS_API_KEY') and re.fullmatch(
        r'[A-Za-z0-9]{10,64}', os.getenv('ELEVENLABS_VOICE_ID', '')))


def _signer():
    # Domain separation keeps these tokens independent of provider authentication.
    secret = hashlib.sha256(('concierge-playback:' + os.environ['ELEVENLABS_API_KEY']).encode()).digest()
    return URLSafeTimedSerializer(secret, salt='public-wine-reply-v1:' + os.environ['ELEVENLABS_VOICE_ID'])


def speech_token(text):
    if not configured() or not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT:
        return None
    return _signer().dumps({'text': text})


def lower_pitch(audio):
    """Use the same Rubber Band adjustment as the reviewed welcome sample."""
    try:
        result = subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-i', 'pipe:0', '-af',
            f'rubberband=pitch={PITCH_RATIO}:tempo=1:pitchq=quality:formant=shifted',
            '-t', '120', '-codec:a', 'libmp3lame', '-b:a', '128k', '-f', 'mp3', 'pipe:1',
        ], input=audio, capture_output=True, timeout=5, check=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SpeechUnavailable() from exc
    if not result.stdout or len(result.stdout) > MAX_AUDIO:
        raise SpeechUnavailable()
    return result.stdout


def _generate(text):
    try:
        started = time.monotonic()
        with requests.post(
            'https://api.elevenlabs.io/v1/text-to-speech/' + os.environ['ELEVENLABS_VOICE_ID'],
            params={'output_format': 'mp3_44100_128'},
            headers={'xi-api-key': os.environ['ELEVENLABS_API_KEY'], 'Accept': 'audio/mpeg'},
            json={'text': text, 'model_id': os.getenv('ELEVENLABS_MODEL_ID', 'eleven_v4'),
                  'voice_settings': {'stability': 0.5, 'similarity_boost': 0.75}},
            timeout=(3, 18), stream=True, allow_redirects=False,
        ) as response:
            if response.status_code != 200 or 'audio/' not in response.headers.get('Content-Type', ''):
                raise SpeechUnavailable()
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > MAX_AUDIO or time.monotonic() - started > 22:
                    raise SpeechUnavailable()
                chunks.append(chunk)
        if not size:
            raise SpeechUnavailable()
        return lower_pitch(b''.join(chunks))
    except (requests.RequestException, KeyError) as exc:
        raise SpeechUnavailable() from exc


@speech_bp.post('/speech')
def speak():
    request.max_content_length = 8 * 1024
    if not configured():
        return jsonify(error='Voice playback is not configured. You can read the answer below.'), 503
    data = request.get_json(silent=True)
    token = data.get('token') if isinstance(data, dict) else None
    if not isinstance(token, str) or len(token) > 7000:
        return jsonify(error='Ask for a fresh recommendation before playing it.'), 400
    try:
        reply = _signer().loads(token, max_age=TOKEN_SECONDS)
        if (not isinstance(reply, dict) or not isinstance(reply.get('text'), str)
                or not 1 <= len(reply['text']) <= MAX_TEXT):
            raise BadData('invalid reply')
    except BadData:
        return jsonify(error='This playback has expired. Ask your question again.'), 400
    key = hashlib.sha256((os.environ['ELEVENLABS_VOICE_ID'] +
        os.getenv('ELEVENLABS_MODEL_ID', 'eleven_v4') + reply['text']).encode()).hexdigest()
    # Non-blocking lock prevents concurrent provider calls and duplicate charges.
    if not _lock.acquire(blocking=False):
        return jsonify(error='Charlie is preparing another answer. Please try playback again shortly.'), 429
    try:
        now = time.monotonic()
        cached = _cache.get(key)
        if cached and now - cached[0] < TOKEN_SECONDS:
            _cache.move_to_end(key)
            audio = cached[1]
        else:
            while _requests and now - _requests[0] >= 60:
                _requests.popleft()
            if len(_requests) >= 6:
                return jsonify(error='Voice playback is busy. Please try again in a minute.'), 429
            _requests.append(now)
            audio = _generate(reply['text'])
            _cache[key] = (now, audio)
            _cache.move_to_end(key)
            while len(_cache) > 16:
                _cache.popitem(last=False)
    except SpeechUnavailable:
        return jsonify(error='Voice playback is unavailable right now. You can read the answer below.'), 502
    finally:
        _lock.release()
    return Response(audio, mimetype='audio/mpeg', headers={'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff'})
