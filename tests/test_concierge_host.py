import hashlib

import app


def test_original_portrait_is_served_without_modification():
    response = app.app.test_client().get('/static/images/dad-original.jpeg')
    assert response.status_code == 200
    assert response.mimetype == 'image/jpeg'
    # Check the original uploaded bytes, not a regenerated or recompressed image.
    assert hashlib.sha256(response.data).hexdigest() == (
        '977be9e3b0d53b8a42d46f149ecff7e24e5808948a4fe1f1dd7c2e012d7c5fb0'
    )


def test_both_customer_pages_identify_the_virtual_host():
    client = app.app.test_client()
    for route in ('/', '/embed'):
        response = client.get(route)
        assert response.status_code == 200
        assert b'/static/images/dad-original.jpeg' in response.data
        assert b'alt="Portrait of Dad, our virtual wine host"' in response.data
        assert b'Dad, our AI wine concierge' in response.data
        assert b'Chat by text below.' in response.data
        assert b'id="ask-form"' in response.data
