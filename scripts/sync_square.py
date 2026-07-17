#!/usr/bin/env python3
"""
Square -> website catalog sync for Bama Tan Salon & Boutique.

Runs in GitHub Actions (see .github/workflows/square-sync.yml).
- Pulls every item, variation, price, category, stock level and product
  photo from the Square Catalog / Inventory APIs.
- Auto-creates a Square-hosted payment link for any sellable variation
  that doesn't have one yet (stored in data/payment_links.json so each
  link is only created once).
- Rewrites the product grid in shop/index.html (between the
  CATALOG:START / CATALOG:END markers) and wires the tanning-package
  Buy buttons in assets/js/shop.js.

Requires env var SQUARE_ACCESS_TOKEN. Never commit the token.
Optional: SQUARE_ENV=sandbox to run against a Square sandbox account.
Optional: --mock <fixtures.json> to test generation without the API.
"""
import os, sys, json, re, time, html, hashlib

try:
    import requests
except ImportError:
    requests = None

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/ -> repo root
SHOP_HTML = os.path.join(REPO, 'shop', 'index.html')
SHOP_JS = os.path.join(REPO, 'assets', 'js', 'shop.js')
LINKS_FILE = os.path.join(REPO, 'data', 'payment_links.json')
CATALOG_FILE = os.path.join(REPO, 'data', 'catalog.json')

BASE = 'https://connect.squareupsandbox.com' if os.environ.get('SQUARE_ENV') == 'sandbox' \
       else 'https://connect.squareup.com'
TOKEN = os.environ.get('SQUARE_ACCESS_TOKEN', '')
HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json',
           'Square-Version': '2025-05-21'}

SERVICE_CATS = {'Tanning Packages', 'Red Light Therapy', 'Spray Tans'}
CAT_MAP = {'Clothes': 'clothes', 'Accessories': 'accessories', 'Jewelry': 'accessories',
           'Tanning Lotion': 'lotions'}
CAT_LABEL = {'clothes': 'Clothes', 'accessories': 'Accessories', 'lotions': 'Lotions', 'boutique': 'More'}

# Tanning-package Buy buttons on the shop page -> Square item names.
# (Club memberships are excluded on purpose: recurring billing should be
# a Square *subscription* link the owner creates once in the dashboard.)
SERVICE_SKU_TO_ITEM = {
    'l2-single': ('Tanning Packages', 'Level 2 - 1 Visit'),
    'l2-five':   ('Tanning Packages', 'Level 2 - 5 Visits'),
    'l2-ten':    ('Tanning Packages', 'Level 2 - 10 Visits'),
    'l2-150':    ('Tanning Packages', 'Level 2 - 150 Minutes'),
    'l2-300':    ('Tanning Packages', 'Level 2 - 300 Minutes'),
    'l2-month':  ('Tanning Packages', 'Level 2 Month Unlimited'),
    'l3-single': ('Tanning Packages', 'Level 3 - 1 Visit'),
    'l3-five':   ('Tanning Packages', 'Level 3 - 5 Visits'),
    'l3-ten':    ('Tanning Packages', 'Level 3 - 10 Visits'),
    'l3-150':    ('Tanning Packages', 'Level 3 - 150 Minutes'),
    'l3-300':    ('Tanning Packages', 'Level 3 - 300 Minutes'),
    'l3-month':  ('Tanning Packages', 'Level 3 Month Unlimited'),
    'rl-single': ('Red Light Therapy', '1 Visit'),
    'rl-five':   ('Red Light Therapy', '5 Visits'),
    'rl-ten':    ('Red Light Therapy', '10 Visits'),
    'rl-month':  ('Red Light Therapy', 'Red light one month unlimited'),
    'spray-single': ('Spray Tans', 'Hand spray tan single visit'),
    'week-any':  ('Tanning Packages', 'Weekly Unlimited'),
    'family-add': ('Tanning Packages', 'Add family member to any package'),
}

def esc(s):
    return html.escape(str(s), quote=True)

def money(cents):
    d = cents / 100.0
    return ('$%g' % d) if d != int(d) or True else ('$%d' % int(d))

# ---------------------------------------------------------------- API helpers
def api_get(path, params=None):
    r = requests.get(BASE + path, headers=HEADERS, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()

def api_post(path, body):
    r = requests.post(BASE + path, headers=HEADERS, json=body, timeout=30)
    if r.status_code >= 400:
        print('  ! API error', r.status_code, r.text[:300], file=sys.stderr)
        return None
    return r.json()

def fetch_catalog():
    objs, cursor = [], None
    while True:
        params = {'types': 'ITEM,IMAGE,CATEGORY'}
        if cursor: params['cursor'] = cursor
        data = api_get('/v2/catalog/list', params)
        objs += data.get('objects', [])
        cursor = data.get('cursor')
        if not cursor: break
    return objs

def fetch_inventory(variation_ids):
    counts = {}
    for i in range(0, len(variation_ids), 100):
        chunk = variation_ids[i:i+100]
        data = api_post('/v2/inventory/counts/batch-retrieve',
                        {'catalog_object_ids': chunk}) or {}
        cursor = True
        while cursor:
            for c in data.get('counts', []):
                if c.get('state') == 'IN_STOCK':
                    counts[c['catalog_object_id']] = counts.get(c['catalog_object_id'], 0) + float(c.get('quantity', 0))
            cursor = data.get('cursor')
            if cursor:
                data = api_post('/v2/inventory/counts/batch-retrieve',
                                {'catalog_object_ids': chunk, 'cursor': cursor}) or {}
    return counts

def get_location_id():
    data = api_get('/v2/locations')
    for loc in data.get('locations', []):
        if loc.get('status') == 'ACTIVE':
            return loc['id']
    raise SystemExit('No active Square location found')

def ensure_payment_link(links, variation_id, location_id):
    if links.get(variation_id):
        return links[variation_id]
    body = {
        'idempotency_key': hashlib.sha256(('bamatan-' + variation_id).encode()).hexdigest()[:45],
        'order': {'location_id': location_id,
                  'line_items': [{'quantity': '1', 'catalog_object_id': variation_id}]},
    }
    data = api_post('/v2/online-checkout/payment-links', body)
    time.sleep(0.35)  # stay well under rate limits
    if data and data.get('payment_link', {}).get('url'):
        links[variation_id] = data['payment_link']['url']
        return links[variation_id]
    return ''

# ---------------------------------------------------------------- model
def build_products(objects, counts):
    images = {o['id']: o['image_data'].get('url', '') for o in objects if o['type'] == 'IMAGE'}
    cats = {o['id']: o['category_data'].get('name', '') for o in objects if o['type'] == 'CATEGORY'}
    products, services = [], {}
    for o in objects:
        if o['type'] != 'ITEM' or o.get('is_deleted'):
            continue
        d = o.get('item_data', {})
        if d.get('is_archived'):
            continue
        name = (d.get('name') or '').strip()
        cat_ids = [c.get('id') for c in d.get('categories', [])] or ([d.get('category_id')] if d.get('category_id') else [])
        cat_name = cats.get(cat_ids[0], '') if cat_ids else ''
        variations = []
        for v in d.get('variations', []):
            vd = v.get('item_variation_data', {})
            price = vd.get('price_money', {}).get('amount')
            if price is None:
                continue
            vid = v['id']
            tracked = vd.get('track_inventory', False)
            in_stock = (not tracked) or counts.get(vid, 0) > 0
            variations.append({'id': vid, 'name': (vd.get('name') or '').strip(),
                               'price': price, 'in_stock': in_stock})
        if cat_name in SERVICE_CATS:
            services[(cat_name, name)] = variations
            continue
        avail = [v for v in variations if v['in_stock']]
        if not avail:
            continue
        img = ''
        for iid in d.get('image_ids', []) or []:
            if images.get(iid):
                img = images[iid]; break
        products.append({'name': name, 'cat': CAT_MAP.get(cat_name, 'boutique'),
                         'img': img, 'variations': avail})
    products.sort(key=lambda p: (p['cat'], p['name'].lower()))
    return products, services

# ---------------------------------------------------------------- HTML
def render_cards(products, links):
    out = []
    for p in products:
        vs = p['variations']
        prices = sorted({v['price'] for v in vs})
        price_label = money(prices[0]) if len(prices) == 1 else '%s–%s' % (money(prices[0]), money(prices[-1]))
        first_link = links.get(vs[0]['id'], '')
        if p['img']:
            img = '<img src="%s" alt="%s — Bama Tan boutique, Tuscaloosa AL" loading="lazy" decoding="async">' % (esc(p['img']), esc(p['name']))
        else:
            img = '<div class="ph"><span class="mono">%s</span><small>%s</small></div>' % (esc(p['name'][:1].upper()), CAT_LABEL[p['cat']])
        sel = ''
        if len(vs) > 1:
            opts = ''.join('<option value="%s" data-price="%s">%s — %s</option>' %
                           (esc(links.get(v['id'], '')), money(v['price']), esc(v['name'] or 'Option'), money(v['price']))
                           for v in vs)
            sel = '<select class="p-var" aria-label="Choose option">%s</select>' % opts
        buy = ('<a class="buy" href="%s" target="_blank" rel="noopener">Buy</a>' % esc(first_link)) if first_link \
              else '<a class="buy" data-nolink href="#" role="button">Buy</a>'
        out.append('''<div class="p-card" data-cat="%s" data-name="%s">
  <div class="p-img">%s</div>
  <div class="p-body"><h3>%s</h3>%s
    <div class="p-row"><span class="p-price">%s</span>%s</div>
  </div>
</div>''' % (p['cat'], esc(p['name'].lower()), img, esc(p['name']), sel, price_label, buy))
    return '\n'.join(out)

def splice_shop(cards_html):
    src = open(SHOP_HTML).read()
    new = re.sub(r'(<!-- CATALOG:START -->).*?(<!-- CATALOG:END -->)',
                 lambda m: m.group(1) + '\n' + cards_html + '\n' + m.group(2),
                 src, flags=re.S)
    if new == src and cards_html not in src:
        raise SystemExit('CATALOG markers not found in shop/index.html')
    open(SHOP_HTML, 'w').write(new)

def wire_service_links(services, links, location_id, live=True):
    js = open(SHOP_JS).read()
    for sku, (cat, item_name) in SERVICE_SKU_TO_ITEM.items():
        vs = services.get((cat, item_name)) or []
        if not vs:
            print('  ~ service item not found in Square:', item_name)
            continue
        url = ensure_payment_link(links, vs[0]['id'], location_id) if live else links.get(vs[0]['id'], '')
        if url:
            js = re.sub(r'("%s":\s*)"[^"]*"' % re.escape(sku), r'\1"%s"' % url, js)
    open(SHOP_JS, 'w').write(js)

# ---------------------------------------------------------------- main
def main():
    mock = None
    if '--mock' in sys.argv:
        mock = json.load(open(sys.argv[sys.argv.index('--mock') + 1]))
    if not mock and not TOKEN:
        raise SystemExit('SQUARE_ACCESS_TOKEN is not set')
    if not mock and requests is None:
        raise SystemExit('pip install requests')

    os.makedirs(os.path.dirname(LINKS_FILE), exist_ok=True)
    links = json.load(open(LINKS_FILE)) if os.path.exists(LINKS_FILE) else {}

    if mock:
        objects, counts, location_id = mock['objects'], mock.get('counts', {}), 'MOCK'
    else:
        print('Fetching catalog…'); objects = fetch_catalog()
        var_ids = [v['id'] for o in objects if o['type'] == 'ITEM'
                   for v in o.get('item_data', {}).get('variations', [])]
        print('Fetching inventory for %d variations…' % len(var_ids))
        counts = fetch_inventory(var_ids)
        location_id = get_location_id()

    products, services = build_products(objects, counts)
    print('Sellable products:', len(products))

    if not mock:
        need = [v for p in products for v in p['variations'] if not links.get(v['id'])]
        print('Creating %d missing payment links…' % len(need))
        for v in need:
            ensure_payment_link(links, v['id'], location_id)

    splice_shop(render_cards(products, links))
    wire_service_links(services, links, None if mock else location_id, live=not mock)
    json.dump(links, open(LINKS_FILE, 'w'), indent=1)
    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()),
               'products': len(products)}, open(CATALOG_FILE, 'w'), indent=1)
    print('Done. Shop page updated.')

if __name__ == '__main__':
    main()
