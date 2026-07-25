#!/usr/bin/env python3
"""
Square -> website catalog sync for Bama Tan Salon & Boutique.

Runs in GitHub Actions (see .github/workflows/square-sync.yml).
- Pulls every item, variation, price, category, stock level and product
  photo from the Square Catalog / Inventory APIs.
- Rewrites the product grid in shop/index.html (between the
  CATALOG:START / CATALOG:END markers) with cart-ready cards:
  size dropdowns for multi-size items, the size shown inline for
  single-size items, and Add to Cart buttons carrying the Square
  variation IDs the checkout Worker needs.
- Fills the SERVICE_ITEMS map in assets/js/shop.js so tanning-package
  buttons are cart-enabled too.

All displayed prices are the Square catalog price multiplied by
PRICE_ADJ (sales tax + card processing). The Cloudflare Worker applies
the same percentage as an order service charge, so what customers see
is what Square charges.

Requires env var SQUARE_ACCESS_TOKEN. Never commit the token.
Optional: SQUARE_ENV=sandbox. Optional: --mock <fixtures.json>.
"""
import os, sys, json, re, time, html

try:
    import requests
except ImportError:
    requests = None

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOP_HTML = os.path.join(REPO, 'shop', 'index.html')
SHOP_JS = os.path.join(REPO, 'assets', 'js', 'shop.js')
CATALOG_FILE = os.path.join(REPO, 'data', 'catalog.json')

PRICE_ADJ = 1.134  # sales tax + card processing — keep in sync with the Worker's TAX_PERCENT

BASE = 'https://connect.squareupsandbox.com' if os.environ.get('SQUARE_ENV') == 'sandbox' \
       else 'https://connect.squareup.com'
TOKEN = os.environ.get('SQUARE_ACCESS_TOKEN', '')
HEADERS = {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json',
           'Square-Version': '2025-05-21'}

SERVICE_CATS = {'Tanning Packages', 'Red Light Therapy', 'Spray Tans'}
CAT_MAP = {'Clothes': 'clothes', 'Accessories': 'accessories', 'Jewelry': 'accessories',
           'Tanning Lotion': 'lotions'}
CAT_LABEL = {'clothes': 'Clothes', 'accessories': 'Accessories', 'lotions': 'Lotions', 'boutique': 'More'}

# shop-page Buy buttons (data-sku) -> Square item names.
# Club memberships are intentionally absent: recurring billing uses
# subscription links pasted into PAYMENT_LINKS in shop.js.
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

def cents_adj(cents):
    return int(round(cents * PRICE_ADJ))

def money(cents):
    return '$%.2f' % (cents_adj(cents) / 100.0)

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
def render_cards(products):
    out = []
    for p in products:
        vs = p['variations']
        adj = sorted({cents_adj(v['price']) for v in vs})
        price_label = ('$%.2f' % (adj[0]/100)) if len(adj) == 1 else ('$%.2f–$%.2f' % (adj[0]/100, adj[-1]/100))
        if p['img']:
            img = '<img src="%s" alt="%s — Bama Tan boutique, Tuscaloosa AL" loading="lazy" decoding="async">' % (esc(p['img']), esc(p['name']))
        else:
            img = '<div class="ph"><span class="mono">%s</span><small>%s</small></div>' % (esc(p['name'][:1].upper()), CAT_LABEL[p['cat']])
        meta, sel = '', ''
        if len(vs) > 1:
            opts = ''.join('<option value="%s" data-cents="%d" data-price="%s" data-vname="%s">%s — %s</option>' %
                           (esc(v['id']), cents_adj(v['price']), money(v['price']), esc(v['name']),
                            esc(v['name'] or 'Option'), money(v['price'])) for v in vs)
            sel = '<select class="p-var" aria-label="Choose size or option">%s</select>' % opts
            buy = '<button type="button" class="buy add-cart" data-name="%s">Add to Cart</button>' % esc(p['name'])
        else:
            v = vs[0]
            if v['name'] and v['name'].lower() not in ('regular', 'one size'):
                meta = '<p class="p-meta">Size: %s</p>' % esc(v['name'])
            buy = ('<button type="button" class="buy add-cart" data-vid="%s" data-cents="%d" data-name="%s" data-vname="%s">Add to Cart</button>'
                   % (esc(v['id']), cents_adj(v['price']), esc(p['name']), esc(v['name'] if v['name'].lower() not in ('regular','one size') else '')))
        out.append('''<div class="p-card" data-cat="%s" data-name="%s">
  <div class="p-img">%s</div>
  <div class="p-body"><h3>%s</h3>%s%s
    <div class="p-row"><span class="p-price">%s</span>%s</div>
  </div>
</div>''' % (p['cat'], esc(p['name'].lower()), img, esc(p['name']), meta, sel, price_label, buy))
    return '\n'.join(out)

def splice_shop(cards_html):
    src = open(SHOP_HTML).read()
    new = re.sub(r'(<!-- CATALOG:START -->).*?(<!-- CATALOG:END -->)',
                 lambda m: m.group(1) + '\n' + cards_html + '\n' + m.group(2),
                 src, flags=re.S)
    if new == src and cards_html not in src:
        raise SystemExit('CATALOG markers not found in shop/index.html')
    open(SHOP_HTML, 'w').write(new)

def wire_service_items(services):
    entries = {}
    for sku, (cat, item_name) in SERVICE_SKU_TO_ITEM.items():
        vs = services.get((cat, item_name)) or []
        if not vs:
            print('  ~ service item not found in Square:', item_name)
            continue
        v = vs[0]
        entries[sku] = {'vid': v['id'], 'cents': cents_adj(v['price']), 'name': item_name}
    js = open(SHOP_JS).read()
    blob = json.dumps(entries, indent=0).replace('\n', ' ')
    new = re.sub(r'const SERVICE_ITEMS = \{.*?\}; /\*SYNC:SERVICE_ITEMS\*/',
                 'const SERVICE_ITEMS = %s; /*SYNC:SERVICE_ITEMS*/' % blob, js, flags=re.S)
    if new == js and 'SYNC:SERVICE_ITEMS' not in js:
        print('  ~ SERVICE_ITEMS marker not found in shop.js', file=sys.stderr)
    open(SHOP_JS, 'w').write(new)
    return entries

# ---------------------------------------------------------------- main
def main():
    mock = None
    if '--mock' in sys.argv:
        mock = json.load(open(sys.argv[sys.argv.index('--mock') + 1]))
    if not mock and not TOKEN:
        raise SystemExit('SQUARE_ACCESS_TOKEN is not set')
    if not mock and requests is None:
        raise SystemExit('pip install requests')

    if mock:
        objects, counts = mock['objects'], mock.get('counts', {})
    else:
        print('Fetching catalog…'); objects = fetch_catalog()
        var_ids = [v['id'] for o in objects if o['type'] == 'ITEM'
                   for v in o.get('item_data', {}).get('variations', [])]
        print('Fetching inventory for %d variations…' % len(var_ids))
        counts = fetch_inventory(var_ids)

    products, services = build_products(objects, counts)
    print('Sellable products:', len(products))

    splice_shop(render_cards(products))
    entries = wire_service_items(services)
    os.makedirs(os.path.dirname(CATALOG_FILE), exist_ok=True)
    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()),
               'products': len(products), 'service_items': len(entries),
               'price_adjustment': PRICE_ADJ},
              open(CATALOG_FILE, 'w'), indent=1)
    print('Done. Shop page updated (prices include the %.1f%% adjustment).' % ((PRICE_ADJ-1)*100))

if __name__ == '__main__':
    main()
