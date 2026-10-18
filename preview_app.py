"""Guest-only review server; never loads owner assistant modules or credentials."""
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
PUBLIC_CONCIERGE = 'https://wine-concierge.onrender.com'


@app.after_request
def preview_headers(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
@app.get('/embed')
def home():
    return render_template('concierge.html', embedded=request.path == '/embed', preview=True)


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
