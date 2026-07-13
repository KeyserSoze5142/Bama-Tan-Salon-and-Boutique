// Bama Tan Salon & Boutique — site JS
const nav=document.getElementById('nav');
addEventListener('scroll',()=>nav.classList.toggle('scrolled',scrollY>60),{passive:true});
document.getElementById('burger').addEventListener('click',()=>document.body.classList.toggle('menu-open'));
const io=('IntersectionObserver' in window)?new IntersectionObserver(es=>es.forEach(el=>{if(el.isIntersecting){el.target.classList.add('in');io.unobserve(el.target);}}),{threshold:.12}):null;
document.querySelectorAll('.reveal').forEach(el=>io?io.observe(el):el.classList.add('in'));
// contact form
const form=document.getElementById('contactForm');
if(form){
  const params=new URLSearchParams(location.search);
  const presets={'career':'Career — Hairdresser','tan-career':'Career — Tanning Consultant','private':'Private room pricing & availability'};
  const p=params.get('i');
  if(p&&presets[p]){const s=document.getElementById('f-interest');[...s.options].forEach(o=>{if(o.text===presets[p])s.value=o.text;});}
  if(params.get('sent')==='1'){
    const ok=document.createElement('div');
    ok.className='member-note';
    ok.style.marginBottom='26px';
    ok.innerHTML='<b>Thank you — your message is on its way!</b> We\'ll get back to you as soon as we can.';
    form.prepend(ok);
    if(form.scrollIntoView) form.scrollIntoView({behavior:'smooth',block:'center'});
  }
}
