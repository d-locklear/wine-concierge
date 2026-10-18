"""Guest-only review server; never loads owner assistant modules or credentials."""
import os
import time
from collections import defaultdict, deque
from io import BytesIO
from threading import Lock
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
PUBLIC_CONCIERGE = 'https://wine-concierge.onrender.com'
TRANSCRIPTION_URL = 'https://api.openai.com/v1/audio/transcriptions'
ALLOWED_AUDIO = {'audio/mp4': '.mp4', 'audio/webm': '.webm', 'audio/ogg': '.ogg'}
VOICE_ATTEMPTS = defaultdict(deque)
VOICE_LOCK = Lock()


@app.after_request
def preview_headers(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
@app.get('/embed')
def home():
    return render_template('concierge.html', embedded=request.path == '/embed', preview=True,
                           recording_enabled=bool(os.environ.get('OPENAI_API_KEY')))


@app.post('/transcribe')
def transcribe():
    key = os.environ.get('OPENAI_API_KEY')
    if not key:
        return jsonify(error='Recording is not configured. Please type your question.'), 503
    with VOICE_LOCK:
        attempts = VOICE_ATTEMPTS[request.remote_addr or 'unknown']
        now = time.monotonic()
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 6:
            return jsonify(error='Please wait a minute before recording again.'), 429
        attempts.append(now)
    audio = request.files.get('audio')
    if not audio:
        return jsonify(error='No recording received. Please try again.'), 400
    mime = audio.mimetype.split(';', 1)[0].lower()
    if mime not in ALLOWED_AUDIO:
        return jsonify(error='Unsupported recording format. Please try another browser.'), 415
    content = audio.stream.read(2 * 1024 * 1024 + 1)
    if len(content) < 500 or len(content) > 2 * 1024 * 1024:
        return jsonify(error='Recording must be between a moment and 20 seconds.'), 400
    try:
        response = requests.post(
            TRANSCRIPTION_URL,
            headers={'Authorization': f'Bearer {key}'},
            data={'model': 'gpt-transcribe', 'language': 'en'},
            files={'file': ('question' + ALLOWED_AUDIO[mime], BytesIO(content), mime)},
            timeout=(5, 35),
        )
        response.raise_for_status()
        words = response.json().get('text')
        if not isinstance(words, str) or not words.strip():
            return jsonify(error='No words were heard. Please try again.'), 422
        return jsonify(text=words.strip()[:2000])
    except (requests.RequestException, ValueError):
        return jsonify(error='Transcription could not finish. Please try again or type your question.'), 503


@app.get('/health')
def health():
    return jsonify(status='ready', mode='guest-preview')


@app.post('/ask')
def ask():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Send a JSON object with a prompt'), 400
    prompt = data.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        return jsonify(error='Prompt must contain 1–2000 characters'), 400
    try:
        # Forward only public guest text. Never forward cookies, auth or arbitrary URLs.
        response = requests.post(PUBLIC_CONCIERGE + '/ask',
                                 json={'prompt': prompt.strip()}, timeout=(5, 55))
        data = response.json()
        if response.status_code != 200:
            return jsonify(error='Recommendations are temporarily unavailable. Please try again.'), 503
        if not isinstance(data, dict) or not isinstance(data.get('response'), str) or not isinstance(data.get('wines'), list):
            raise ValueError('Unexpected recommendation response')
        return jsonify(response=data['response'], wines=data['wines'])
    except (requests.RequestException, ValueError):
        return jsonify(error='We could not connect to recommendations. Please try again.'), 503


@app.get('/wines')
def wines():
    try:
        response = requests.get(PUBLIC_CONCIERGE + '/wines', timeout=(5, 15))
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get('wines'), list):
            raise ValueError('Unexpected catalog response')
        return jsonify(wines=data['wines'])
    except (requests.RequestException, ValueError):
        return jsonify(error='Wine catalog is temporarily unavailable'), 503
