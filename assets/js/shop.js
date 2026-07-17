// ============================================================
// SQUARE CHECKOUT INTEGRATION
// For each item, create a Payment Link in the Square Dashboard
// (Payment Links > Create > Sell an item — pick the item from
// the library so sizes/variations carry over). Use a
// *subscription* link for monthly Club memberships.
// Paste each URL between the quotes — buttons go live instantly.
// Items with no link show a friendly "call or visit" message.
// ============================================================
const PAYMENT_LINKS = {
  // ----- Tanning packages & memberships -----
  "l2-single": "",     // Level 2 — single visit $12
  "l2-five": "",       // Level 2 — five visits $50
  "l2-ten": "",        // Level 2 — ten visits $80
  "l2-150": "",        // Level 2 — 150 minutes $100
  "l2-300": "",        // Level 2 — 300 minutes $120
  "l2-month": "",      // Level 2 — one-month unlimited $65
  "l2-club": "",       // Level 2 — Club Tan $55/mo (subscription)
  "l3-single": "",     // Level 3 — single visit $15
  "l3-five": "",       // Level 3 — five visits $60
  "l3-ten": "",        // Level 3 — ten visits $100
  "l3-150": "",        // Level 3 — 150 minutes $110
  "l3-300": "",        // Level 3 — 300 minutes $150
  "l3-month": "",      // Level 3 — one-month unlimited $75
  "l3-club": "",       // Level 3 — Club Tan $65/mo (subscription)
  "rl-single": "",     // Red light — single $12
  "rl-five": "",       // Red light — five visits $50
  "rl-ten": "",        // Red light — ten visits $80
  "rl-month": "",      // Red light — one-month unlimited $75
  "spray-single": "",  // Spray tan session $30
  "spray-club": "",    // Club Spray $65/mo (subscription)
  "week-any": "",      // Straight-week tanning $35
  "family-add": "",    // Add family member to any package $30
  // ----- Boutique & products (from Square item library) -----
};
const NOLINK_MSG='Online checkout for this item is coming soon!\n\nCall (205) 462-2115 or visit us at 2337 University Blvd E to purchase today.';
document.querySelectorAll('[data-sku]').forEach(btn=>{
  const url=PAYMENT_LINKS[btn.dataset.sku];
  if(url){btn.href=url;btn.target='_blank';btn.rel='noopener';}
  else{btn.addEventListener('click',e=>{e.preventDefault();alert(NOLINK_MSG);});}
});
// synced cards: no-link fallback (delegated so it follows variation changes) + variation selects
document.addEventListener('click',e=>{const b=e.target.closest('.buy[data-nolink]');if(b){e.preventDefault();alert(NOLINK_MSG);}});
document.querySelectorAll('.p-var').forEach(sel=>{
  const card=sel.closest('.p-card'), buy=card.querySelector('.buy'), price=card.querySelector('.p-price');
  function upd(){
    const o=sel.selectedOptions[0];
    if(o.dataset.price) price.textContent=o.dataset.price;
    if(o.value){buy.href=o.value;buy.target='_blank';buy.rel='noopener';buy.removeAttribute('data-nolink');}
    else{buy.href='#';buy.setAttribute('data-nolink','');}
  }
  sel.addEventListener('change',upd); upd();
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