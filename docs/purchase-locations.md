# Public buying directory

Customers can ask a buying-location question in `/ask`, choose the Where to buy
suggestion, or enter a city, ZIP code or store name in the optional location field.
Buying answers are built from reviewed records, without sending the query to the
recommendation model. The existing response/wines contract remains; location
answers add a locations array and use the existing signed speech playback.

`data/purchase_locations.json` is a public directory, not live inventory. Initial
entries are the winery and its online shop, checked against the winery's public
homepage and Visit Us page on October 22, 2026. The October 22 extension adds 37 individual retailers with reviewed public
addresses, plus owner-confirmed coverage at all North Carolina Food Lion stores.
All 509 individual North Carolina Food Lion stores are also included, bringing
the directory to 549 entries including the winery, online shop and statewide
Food Lion overview. Retailer candidates
were identified from the owner-authorized customer review; address facts come
from public merchant pages. No accounting data or customer identifiers are bundled.
Unresolved accounts and distributor warehouses are excluded; this is not an
exhaustive list of all retailers. Food Lion coverage includes a statewide overview plus each street-address
record from the official directory. This never claims that a particular bottle
is in stock at every store. No market
schedules have been asserted.

To add a retailer or market, include a stable id, name, kind (retailer/market),
street address, city, state, postal_code when publicly confirmed, public phone if known, HTTPS public
location url, public source_url, checked_on (ISO date), and active boolean. Extend
the explicit URL host allowlists in the server and customer renderer only for
reviewed public retailer domains. Never include invoices, customer account IDs,
wholesale terms, private contact details, sales amounts, or delivery records.
Owner-reviewed delivery evidence may establish a candidate listing but never
proves current bottle stock. Publish only the approved public location details.

Physical search matches the entered text against the listed name/address/city/
state/ZIP. North Carolina Food Lion coverage and the online shop remain
available as explicitly labeled regional/online alternatives even when a specific
physical address does not match. Street-address matches only include that query. It does not geocode, calculate distance, request device location or
claim a nearest store. Online remains an alternative regardless of the search;
shipping eligibility is checked in the shop. Nonmatching areas receive an explicit
no-confirmed-listing message, not a claim that there are no retailers there.
Generic spoken buying answers include physical addresses and the winery's public
phone. Cards include reviewed links and generated Google Maps address searches.
Inactive, future-dated or older-than-180-day listings are omitted until reconfirmed.

Validation: 42 relevant Python tests and five Node playback/location tests pass,
including all 509 store ZIP lookups, city filtering, public link safety, primary
address parsing and signed voice playback.

Public address sources: Walmart store finder (ZIP 28384); Lowes Foods individual
store pages 157, 160 and 261; Carlie C’s individual store pages; Fresh Foods
https://freshfoods.us/locations/; Piggly Wiggly’s North Carolina location directory;
and Well Travelled Beer’s main page. Food Lion’s official North Carolina directory
is the customer-facing chain finder.

## Official Food Lion collection

Run `python scripts/refresh_food_lion_locations.py --cache /tmp/food-lion-cache
--output /tmp/food-lion-nc.json` as one command. The script follows only official
North Carolina city/store links, uses a dated local cache and at most eight
concurrent requests, checks every city count against the index, and verifies
each primary store address, NC state, ZIP and phone. Missing, duplicate or
invalid records abort before an output file is written. Nearby-store teasers
are never mistaken for the primary store address. No live scraping occurs in
the customer request path.

The October 22 snapshot reconciles 243 city entries and 526 official detail pages to 509 grocery
store records. Seventeen pharmacy pages are excluded based on their official
page titles; grocery-store phone numbers and URLs are retained. All 509 records carry their own official store
URL, public telephone, ZIP and check date. The owner's all-NC wine coverage
confirmation is independent of the public directory's address evidence.

Responses show at most 24 cards and report the full matching count. Every
record remains searchable by city, ZIP, address or name. The interface does
not infer a nearest store or invent live wine inventory.
