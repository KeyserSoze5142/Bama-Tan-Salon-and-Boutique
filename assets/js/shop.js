// ============================================================
// BAMA TAN — SHOP, CART & SQUARE CHECKOUT
// 1) WORKER_URL: paste your Cloudflare Worker URL after deploying
//    cloudflare/worker.js (see DEPLOYMENT-GUIDE.md), e.g.
//    "https://bamatan-checkout.YOURNAME.workers.dev"
// 2) PAYMENT_LINKS: monthly Club memberships bill monthly, so they
//    use Square *subscription* links created once in the Dashboard.
// 3) SERVICE_ITEMS is filled automatically by scripts/sync_square.py.
// All prices shown include sales tax & card processing (13.4%).
// ============================================================
const WORKER_URL = "https://bamatan-checkout.cmwebber51492.workers.dev";
const SHIPPING_CENTS = 1200; // flat shipping; keep in sync with the Worker
const PAYMENT_LINKS = {
  "l2-club":   "",  // Level 2 Club Tan $55/mo — subscription link
  "l3-club":   "",  // Level 3 Club Tan $65/mo — subscription link
  "spray-club":""   // Club Spray $65/mo — subscription link
};
const SERVICE_ITEMS = { "l2-single": { "vid": "CATOU5EMZG4HMS3GI4GKFZV3", "cents": 1361, "name": "Level 2 - 1 Visit" }, "l2-five": { "vid": "BPMFYM4HAMBCUKAULYBJOUT7", "cents": 5670, "name": "Level 2 - 5 Visits" }, "l2-ten": { "vid": "FBQT2Y5WA7LST2SBEDLR2XAT", "cents": 9072, "name": "Level 2 - 10 Visits" }, "l2-150": { "vid": "NOS2BW4TGJI6LZEQRNECB7PH", "cents": 11340, "name": "Level 2 - 150 Minutes" }, "l2-300": { "vid": "DGDOTQYNWSGONAQXZ3XPG5WR", "cents": 13608, "name": "Level 2 - 300 Minutes" }, "l2-month": { "vid": "USF7UOXBPXL6G2BOEE5HREXM", "cents": 7371, "name": "Level 2 Month Unlimited" }, "l3-single": { "vid": "XYRLIW2IZOEXICFUYLEVQLTS", "cents": 1701, "name": "Level 3 - 1 Visit" }, "l3-five": { "vid": "GO4ZVMYYIN7SIVKT7EN2M3MO", "cents": 6804, "name": "Level 3 - 5 Visits" }, "l3-ten": { "vid": "H54ZJR33SQXKXRZWGQ3OREYA", "cents": 11340, "name": "Level 3 - 10 Visits" }, "l3-150": { "vid": "HAX7UFV42WGILX6AHWEUX5H2", "cents": 12474, "name": "Level 3 - 150 Minutes" }, "l3-300": { "vid": "7MBR54WQEL6XAFOHH377KTRK", "cents": 17010, "name": "Level 3 - 300 Minutes" }, "l3-month": { "vid": "6HOS5GO4P4XS2P7RAXCQXZAP", "cents": 8505, "name": "Level 3 Month Unlimited" }, "rl-single": { "vid": "CGYRHH27G6C6LO4CPLA4DA2I", "cents": 1361, "name": "1 Visit" }, "rl-five": { "vid": "PK33FGZVLE7SNUBFGR5Z6QTB", "cents": 5670, "name": "5 Visits" }, "rl-ten": { "vid": "G3YLGU4NA2YYLCS25H26UWLU", "cents": 9072, "name": "10 Visits" }, "rl-month": { "vid": "XHFKU7H2XF3M7OFVVTPLH7ZY", "cents": 8505, "name": "Red light one month unlimited" }, "spray-single": { "vid": "RL7ZPR4QDW754H3S6MXXXXEF", "cents": 3402, "name": "Hand spray tan single visit" }, "week-any": { "vid": "73VX7I2KDAXOWSPYLT75M2BU", "cents": 3969, "name": "Weekly Unlimited" }, "family-add": { "vid": "7NYLV6QD6R7C6P7CHT6HDZG3", "cents": 3402, "name": "Add family member to any package" } }; /*SYNC:SERVICE_ITEMS*/
const NOLINK_MSG='Online checkout for this item is coming soon!\n\nCall (205) 462-2115 or visit us at 2337 University Blvd E to purchase today.';
const fmt=c=>'$'+(c/100).toFixed(2);

// ---------------- cart state ----------------
let CART=[];
try{CART=JSON.parse(localStorage.getItem('bt_cart')||'[]')}catch(e){}
const save=()=>{localStorage.setItem('bt_cart',JSON.stringify(CART));render()};
function addToCart(it){
  const ex=CART.find(x=>x.vid===it.vid);
  if(ex)ex.qty=Math.min(ex.qty+1,20); else CART.push({...it,qty:1});
  save(); openCart();
}

// ---------------- cart UI ----------------
const hasShop=!!document.getElementById('pGrid')||!!document.querySelector('[data-sku]');
if(hasShop){
  document.body.insertAdjacentHTML('beforeend',`
<button id="cartFab" aria-label="Shopping cart"><svg viewBox="0 0 24 24"><path d="M6 7h12l-1.2 12.2a1.8 1.8 0 0 1-1.8 1.8H9a1.8 1.8 0 0 1-1.8-1.8L6 7z"/><path d="M9 9V6a3 3 0 0 1 6 0v3"/></svg><span id="cartCount">0</span></button>
<div id="cartOverlay"></div>
<aside id="cartPanel" aria-label="Shopping cart panel">
  <div class="cart-head"><h3>Your Cart</h3><button id="cartClose" aria-label="Close cart">&times;</button></div>
  <div id="cartItems"></div>
  <div class="cart-foot">
    <div class="ful-opts">
      <label><input type="radio" name="ful" value="pickup" checked> Free store pickup <span class="ful-price">$0.00</span></label>
      <label><input type="radio" name="ful" value="shipping"> Ship to me <span class="ful-price">${fmt(SHIPPING_CENTS)}</span></label>
    </div>
    <div class="cart-total"><span>Total</span><b id="cartTotal">$0.00</b></div>
    <p class="cart-tax-note">All prices include sales tax &amp; card processing fees. Secure checkout by Square.</p>
    <button id="cartCheckout">Checkout with Square</button>
  </div>
</aside>`);
}
const openCart=()=>document.body.classList.add('cart-open');
const closeCart=()=>document.body.classList.remove('cart-open');
function fulfillment(){const r=document.querySelector('input[name=ful]:checked');return r?r.value:'pickup'}
function render(){
  if(!hasShop)return;
  const box=document.getElementById('cartItems');
  const n=CART.reduce((s,x)=>s+x.qty,0);
  document.getElementById('cartCount').textContent=n;
  if(!CART.length){box.innerHTML='<p class="cart-empty">Your cart is empty — add something you love!</p>';}
  else box.innerHTML=CART.map((x,i)=>`
<div class="cart-row">
  <div class="ci-info"><h4>${x.name}</h4>${x.vname?`<div class="ci-var">${x.vname}</div>`:''}</div>
  <div class="qty"><button data-q="${i},-1">−</button><span>${x.qty}</span><button data-q="${i},1">+</button></div>
  <span class="ci-price">${fmt(x.cents*x.qty)}</span>
  <button class="ci-remove" data-rm="${i}" aria-label="Remove">&times;</button>
</div>`).join('');
  const ship=fulfillment()==='shipping'?SHIPPING_CENTS:0;
  const tot=CART.reduce((s,x)=>s+x.cents*x.qty,0)+(CART.length?ship:0);
  document.getElementById('cartTotal').textContent=fmt(tot);
}
if(hasShop){
  document.getElementById('cartFab').addEventListener('click',openCart);
  document.getElementById('cartClose').addEventListener('click',closeCart);
  document.getElementById('cartOverlay').addEventListener('click',closeCart);
  document.querySelectorAll('input[name=ful]').forEach(r=>r.addEventListener('change',render));
  document.getElementById('cartItems').addEventListener('click',e=>{
    const q=e.target.closest('[data-q]'), rm=e.target.closest('[data-rm]');
    if(q){const[i,d]=q.dataset.q.split(',').map(Number);CART[i].qty+=d;if(CART[i].qty<1)CART.splice(i,1);save();}
    if(rm){CART.splice(+rm.dataset.rm,1);save();}
  });
  document.getElementById('cartCheckout').addEventListener('click',async()=>{
    if(!CART.length){alert('Your cart is empty.');return;}
    if(!WORKER_URL){alert(NOLINK_MSG);return;}
    const btn=document.getElementById('cartCheckout');
    btn.disabled=true;btn.textContent='Preparing checkout\u2026';
    try{
      const r=await fetch(WORKER_URL.replace(/\/$/,'')+'/checkout',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({items:CART.map(x=>({vid:x.vid,qty:x.qty})),fulfillment:fulfillment()})});
      const d=await r.json();
      if(d&&d.url){location.href=d.url;return;}
      throw new Error(d&&d.error||'checkout failed');
    }catch(err){alert('Sorry, checkout hit a snag. Please try again or call (205) 462-2115.');}
    btn.disabled=false;btn.textContent='Checkout with Square';
  });
  if(new URLSearchParams(location.search).get('paid')==='1'){
    CART=[];localStorage.removeItem('bt_cart');
    document.querySelector('main').insertAdjacentHTML('afterbegin',
      '<div class="paid-banner">Thank you for your order! A Square receipt is on its way to your email.</div>');
  }
  render();
}

// ---------------- buy buttons ----------------
document.addEventListener('click',e=>{
  const b=e.target.closest('.add-cart');
  if(!b)return;
  e.preventDefault();
  const card=b.closest('.p-card');
  const sel=card?card.querySelector('.p-var'):null;
  if(sel){
    const o=sel.selectedOptions[0];
    if(!o.value){alert(NOLINK_MSG);return;}
    addToCart({vid:o.value,cents:+o.dataset.cents,name:b.dataset.name||card.querySelector('h3').textContent,vname:o.dataset.vname||''});
  }else if(b.dataset.vid){
    addToCart({vid:b.dataset.vid,cents:+b.dataset.cents,name:b.dataset.name,vname:b.dataset.vname||''});
  }else alert(NOLINK_MSG);
});
// tanning package / service buttons (data-sku)
document.querySelectorAll('[data-sku]').forEach(btn=>{
  const sku=btn.dataset.sku, si=SERVICE_ITEMS[sku], url=PAYMENT_LINKS[sku];
  if(si&&si.vid){
    btn.addEventListener('click',e=>{e.preventDefault();addToCart({vid:si.vid,cents:si.cents,name:si.name,vname:''});});
    if(btn.textContent.trim()==='Buy')btn.textContent='Add to Cart';
  }
  else if(url){btn.href=url;btn.target='_blank';btn.rel='noopener';}
  else btn.addEventListener('click',e=>{e.preventDefault();alert(NOLINK_MSG);});
});
// variation selects: update displayed price
document.querySelectorAll('.p-var').forEach(sel=>{
  const price=sel.closest('.p-card').querySelector('.p-price');
  const upd=()=>{const o=sel.selectedOptions[0];if(o&&o.dataset.price)price.textContent=o.dataset.price;};
  sel.addEventListener('change',upd);upd();
});
// ---------- catalog filter + search ----------
const grid=document.getElementById('pGrid');
if(grid){
  const cards=[...grid.querySelectorAll('.p-card')];
  const btns=[...document.querySelectorAll('.filter-btn')];
  const search=document.getElementById('pSearch');
  const count=document.getElementById('pCount');
  let cat='all';
  function apply(){
    const q=(search.value||'').toLowerCase().trim();
    let n=0;
    cards.forEach(c=>{
      const ok=(cat==='all'||c.dataset.cat===cat)&&(!q||c.dataset.name.includes(q));
      c.style.display=ok?'':'none';
      if(ok)n++;
    });
    count.textContent=n+' item'+(n===1?'':'s');
  }
  btns.forEach(b=>b.addEventListener('click',()=>{btns.forEach(x=>x.classList.remove('on'));b.classList.add('on');cat=b.dataset.filter;apply();}));
  search.addEventListener('input',apply);
  apply();
}
