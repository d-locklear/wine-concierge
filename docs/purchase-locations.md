# Public buying directory

Customers can ask a buying-location question in `/ask`, choose the Where to buy
suggestion, or enter a city, ZIP code or store name in the optional location field.
Buying answers are built from reviewed records, without sending the query to the
recommendation model. The existing response/wines contract remains; location
answers add a locations array and use the existing signed speech playback.

`data/purchase_locations.json` is a public directory, not live inventory. Initial
entries are the winery and its online shop, checked against the winery's public
homepage and Visit Us page on October 22, 2026. No third-party retailer or farmers
market is claimed yet. Those require reviewed individual locations before listing.

To add a retailer or market, include a stable id, name, kind (retailer/market),
full street address, city, state, postal_code, public phone if known, HTTPS public
location url, public source_url, checked_on (ISO date), and active boolean. Extend
the explicit URL host allowlists in the server and customer renderer only for
reviewed public retailer domains. Never include invoices, customer account IDs,
wholesale terms, private contact details, sales amounts, or delivery records.
Owner-reviewed delivery evidence may establish a candidate listing but never
proves current bottle stock. Publish only the approved public location details.

Physical search matches the entered text against the listed name/address/city/
state/ZIP. It does not geocode, calculate distance, request device location or
claim a nearest store. Online remains an alternative regardless of the search;
shipping eligibility is checked in the shop. Nonmatching areas receive an explicit
no-confirmed-listing message, not a claim that there are no retailers there.
Generic spoken buying answers include physical addresses and the winery's public
phone. Cards include reviewed links and generated Google Maps address searches.
Inactive, future-dated or older-than-180-day listings are omitted until reconfirmed.

Validation: 35 relevant Python tests and four existing Node playback tests pass.
