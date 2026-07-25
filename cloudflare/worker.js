/**
 * Bama Tan — cart checkout Worker (Cloudflare Workers, free tier).
 *
 * Receives the shopping cart from the website, creates ONE Square order
 * containing every item plus a 13.4% "sales tax & card processing"
 * service charge (so the charged total matches the tax-included prices
 * shown on the site) and, for shipping orders, a flat shipping charge.
 * Returns the Square-hosted checkout URL.
 *
 * Setup (one time):
 *   1. Cloudflare dashboard -> Workers & Pages -> Create -> Worker.
 *      Name it e.g. "bamatan-checkout", deploy the hello-world, then
 *      "Edit code", replace everything with this file, Deploy.
 *   2. Worker -> Settings -> Variables and Secrets:
 *        - Add SECRET named SQUARE_ACCESS_TOKEN (the same token used
 *          for the GitHub sync).
 *        - Optional plain variables: SHIPPING_CENTS (default "1200"),
 *          TAX_PERCENT (default "13.4"), LOCATION_ID (auto-detected
 *          if omitted).
 *   3. Copy the worker URL (https://bamatan-checkout.XXXX.workers.dev)
 *      into WORKER_URL at the top of assets/js/shop.js and commit.
 */

const SQUARE_BASE = 'https://connect.squareup.com';
const ALLOWED_ORIGINS = [
  'https://www.bamatansalonandboutique.com',
  'https://bamatansalonandboutique.com',
  'http://localhost:8000', 'http://127.0.0.1:8000', // local testing
];

let cachedLocation = null;

function cors(origin) {
  const ok = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    'Access-Control-Allow-Origin': ok,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json',
  };
}

async function sq(env, method, path, body) {
  const r = await fetch(SQUARE_BASE + path, {
    method,
    headers: {
      'Authorization': `Bearer ${env.SQUARE_ACCESS_TOKEN}`,
      'Content-Type': 'application/json',
      'Square-Version': '2025-05-21',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`Square ${r.status}: ${JSON.stringify(data.errors || data).slice(0, 300)}`);
  return data;
}

async function locationId(env) {
  if (env.LOCATION_ID) return env.LOCATION_ID;
  if (cachedLocation) return cachedLocation;
  const data = await sq(env, 'GET', '/v2/locations');
  const loc = (data.locations || []).find(l => l.status === 'ACTIVE');
  if (!loc) throw new Error('No active Square location');
  cachedLocation = loc.id;
  return cachedLocation;
}

export default {
  async fetch(req, env) {
    const origin = req.headers.get('Origin') || '';
    const headers = cors(origin);

    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers });
    const url = new URL(req.url);
    if (url.pathname === '/health') {
      return new Response(JSON.stringify({ ok: true }), { headers });
    }
    if (req.method !== 'POST' || url.pathname !== '/checkout') {
      return new Response(JSON.stringify({ error: 'not found' }), { status: 404, headers });
    }

    try {
      const { items, fulfillment } = await req.json();
      if (!Array.isArray(items) || items.length === 0 || items.length > 50) {
        throw new Error('invalid cart');
      }
      const lineItems = items.map(it => {
        const qty = Math.max(1, Math.min(20, parseInt(it.qty, 10) || 1));
        if (typeof it.vid !== 'string' || !/^[A-Z0-9]{10,40}$/i.test(it.vid)) throw new Error('invalid item');
        return { quantity: String(qty), catalog_object_id: it.vid };
      });

      const taxPercent = env.TAX_PERCENT || '13.4';
      const shippingCents = parseInt(env.SHIPPING_CENTS || '1200', 10);
      const shipping = fulfillment === 'shipping';

      const serviceCharges = [{
        name: `Sales tax & card processing (${taxPercent}%)`,
        percentage: String(taxPercent),
        calculation_phase: 'SUBTOTAL_PHASE',
      }];
      if (shipping && shippingCents > 0) {
        serviceCharges.push({
          name: 'Shipping (flat rate)',
          amount_money: { amount: shippingCents, currency: 'USD' },
          calculation_phase: 'TOTAL_PHASE',
        });
      }

      const body = {
        idempotency_key: crypto.randomUUID(),
        order: {
          location_id: await locationId(env),
          line_items: lineItems,
          service_charges: serviceCharges,
        },
        checkout_options: {
          allow_tipping: false,
          ask_for_shipping_address: shipping,
          redirect_url: 'https://www.bamatansalonandboutique.com/shop/?paid=1',
          merchant_support_email: 'bethprice@bamatansalonandboutique.com',
        },
        payment_note: shipping ? 'SHIP TO CUSTOMER' : 'STORE PICKUP',
      };

      const data = await sq(env, 'POST', '/v2/online-checkout/payment-links', body);
      const link = data.payment_link && data.payment_link.url;
      if (!link) throw new Error('no checkout url returned');
      return new Response(JSON.stringify({ url: link }), { headers });
    } catch (err) {
      return new Response(JSON.stringify({ error: String(err.message || err).slice(0, 200) }),
                          { status: 400, headers });
    }
  },
};
