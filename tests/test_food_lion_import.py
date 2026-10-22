import pytest
from scripts.refresh_food_lion_locations import extract_store


def fixture(state='NC', postal='27513'):
    return f'''<h1>Food Lion Grocery Store of Cary</h1>
    <address itemprop="address"><span class="Address-field Address-line1">900 NE Maynard Rd</span>
    <span class="Address-field Address-city">Cary</span>
    <abbr class="Address-field Address-region">{state}</abbr>
    <span class="Address-field Address-postalCode">{postal}</span></address>
    <span itemprop="telephone">(919) 460-6274</span>
    <address><span class="Address-city">Other city</span></address>'''


def test_official_primary_address_excludes_nearby_teasers():
    row = extract_store(fixture(), 'https://stores.foodlion.com/nc/cary/900-ne-maynard-rd', '2026-10-22')
    assert row['city'] == 'Cary'
    assert row['address'] == '900 NE Maynard Rd'
    assert row['postal_code'] == '27513'
    assert row['phone'] == '(919) 460-6274'
    assert row['source_url'] == row['url']
    assert row['active'] is True


@pytest.mark.parametrize('html', [fixture('SC'), fixture(postal='bad'), '<h1>Unavailable</h1>'])
def test_invalid_primary_store_aborts_refresh(html):
    with pytest.raises(ValueError):
        extract_store(html, 'https://stores.foodlion.com/nc/cary/example', '2026-10-22')
