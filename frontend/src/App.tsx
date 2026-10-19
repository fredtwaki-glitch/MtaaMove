import { useEffect, useState } from 'react';
import { ArrowRight, CheckCircle2, Clock3, MapPin, Menu, ShieldCheck, Truck, WalletCards } from 'lucide-react';

const API = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

type CurrentUser = { id: number; full_name: string; email: string; phone: string; role: string };
type Booking = { id: number; pickup: string; dropoff: string; move_date: string; status: string; estimated_price_kes: number };

function csrfToken() {
  const entry = document.cookie.split('; ').find(item => item.startsWith('mtaamove_csrf='));
  return entry ? decodeURIComponent(entry.split('=').slice(1).join('=')) : '';
}

export default function App() {
  const [form, setForm] = useState({ customer_name: '', customer_phone: '', pickup: '', dropoff: '', move_date: '', property_type: 'one-bedroom', vehicle_type: 'pickup', service_mode: 'automatic', inventory_notes: '' });
  const [quote, setQuote] = useState<number | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authForm, setAuthForm] = useState({ full_name: '', email: '', phone: '', password: '', password_confirmation: '' });
  const [authMessage, setAuthMessage] = useState('');
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [authBusy, setAuthBusy] = useState(false);
  const update = (key: string, value: string) => setForm(prev => ({ ...prev, [key]: value }));
  const updateAuth = (key: string, value: string) => setAuthForm(prev => ({ ...prev, [key]: value }));

  async function loadBookings() {
    const response = await fetch(`${API}/api/v1/bookings`, { credentials: 'include' });
    if (response.status === 401) {
      setUser(null); setBookings([]);
      throw new Error('Your session has expired. Please sign in again.');
    }
    if (response.ok) setBookings(await response.json());
  }

  useEffect(() => {
    fetch(`${API}/api/v1/auth/me`, { credentials: 'include' }).then(async response => {
      if (response.ok) {
        const current = await response.json();
        setUser(current);
        setForm(prev => ({ ...prev, customer_name: current.full_name, customer_phone: current.phone }));
        await loadBookings();
      }
    }).catch(() => {});
  }, []);

  async function submitAuth(e: React.FormEvent) {
    e.preventDefault(); setAuthBusy(true); setAuthMessage('');
    try {
      const endpoint = authMode === 'register' ? 'register' : 'login';
      const payload = authMode === 'register' ? authForm : { email: authForm.email, password: authForm.password };
      const response = await fetch(`${API}/api/v1/auth/${endpoint}`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check the details and try again.');
      setUser(data);
      setForm(prev => ({ ...prev, customer_name: data.full_name, customer_phone: data.phone }));
      setAuthMessage(`Signed in as ${data.full_name}.`);
      setAuthForm(prev => ({ ...prev, password: '', password_confirmation: '' }));
      await loadBookings();
    } catch (e) { setAuthMessage(e instanceof Error ? e.message : 'Could not authenticate.'); }
    finally { setAuthBusy(false); }
  }

  async function signOut() {
    setAuthMessage('');
    try {
      const response = await fetch(`${API}/api/v1/auth/logout`, {
        method: 'POST', credentials: 'include', headers: { 'X-CSRF-Token': csrfToken() }
      });
      if (!response.ok) throw new Error('Could not sign out. Refresh and try again.');
      setUser(null); setBookings([]);
      setForm(prev => ({ ...prev, customer_name: '', customer_phone: '' }));
      setAuthMessage('You have signed out.');
    } catch (e) { setAuthMessage(e instanceof Error ? e.message : 'Could not sign out.'); }
  }

  async function cancelBooking(id: number) {
    try {
      const response = await fetch(`${API}/api/v1/bookings/${id}/cancel`, {
        method: 'POST', credentials: 'include', headers: { 'X-CSRF-Token': csrfToken() }
      });
      const data = response.status === 204 ? null : await response.json();
      if (!response.ok) { if (response.status === 401) { setUser(null); setBookings([]); } throw new Error(data?.detail || 'Cancellation failed.'); }
      await loadBookings();
      setAuthMessage(`Booking #${id} cancelled.`);
    } catch (e) { setAuthMessage(e instanceof Error ? e.message : 'Cancellation failed.'); }
  }

  async function getQuote() {
    setMessage(''); setBusy(true);
    try {
      const response = await fetch(`${API}/api/v1/quotes`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
      if (!response.ok) throw new Error('Could not calculate an estimate. Check that the API is running.');
      const data = await response.json(); setQuote(data.estimated_price);
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Something went wrong.'); }
    finally { setBusy(false); }
  }

  async function bookMove(e: React.FormEvent) {
    e.preventDefault(); setMessage('');
    if (!user) { setMessage('Please create an account or sign in before submitting a booking. You can still calculate an estimate.'); return; }
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/v1/bookings`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() }, body: JSON.stringify(form) });
      const data = await response.json();
      if (!response.ok) { if (response.status === 401) { setUser(null); setBookings([]); } throw new Error(data.detail || 'Booking could not be created.'); }
      setMessage(`Request #${data.id} received. This is a demo booking; a real dispatch team must confirm availability.`);
      setQuote(data.estimated_price_kes);
      await loadBookings();
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Something went wrong.'); }
    finally { setBusy(false); }
  }

  return <div className="site-shell">
    <header className="nav"><a className="brand" href="#top"><span className="brand-mark"><Truck size={22}/></span><span>Mtaa<span className="brand-light">Move</span></span></a><nav><a href="#how">How it works</a><a href="#services">Services</a><a href="#book">Get a quote</a><a href="#account">My account</a></nav><a className="nav-cta" href="#book">Plan your move <ArrowRight size={16}/></a><button className="mobile-menu" aria-label="Menu"><Menu/></button></header>
    <main id="top">
      <section className="hero"><div className="hero-copy"><div className="eyebrow"><span className="eyebrow-dot"/> YOUR NEIGHBOURHOOD, MOVING FORWARD</div><h1>Moving day.<br/><em>Made lighter.</em></h1><p className="hero-text">From a single sofa to your whole home, find the right local moving help without the usual stress.</p><div className="hero-actions"><a className="button button-primary" href="#book">Get your estimate <ArrowRight size={18}/></a><a className="text-link" href="#how">See how it works</a></div><div className="trust-row"><div className="trust-avatars"><span>JM</span><span>AK</span><span>BK</span></div><div><strong>Local help, made simple</strong><small>Clear estimates · Cash on completion</small></div></div></div>
      <div className="hero-visual"><div className="photo-placeholder"><div className="sun"/><div className="building b1"/><div className="building b2"/><div className="road"/><div className="van"><div className="van-window"/><div className="van-logo">Mtaa<br/>Move</div><i/><i/></div><div className="floating-card"><span className="floating-icon"><MapPin size={17}/></span><div><strong>Your move, your way</strong><small>Choose a provider or let us match you</small></div></div><div className="photo-caption">LOCAL MOVERS. EVERYDAY JOURNEYS.</div></div></div>
      <div className="hero-stamp"><span>MOVE</span><span>WITH</span><strong>EASE</strong><ArrowRight size={21}/></div></section>
      <section className="benefits"><div><ShieldCheck/><span><strong>Provider-first trust</strong><small>Verification planned for launch</small></span></div><div><WalletCards/><span><strong>Pay on completion</strong><small>Cash-first booking flow</small></span></div><div><Clock3/><span><strong>Built around your time</strong><small>Choose a date that works</small></span></div></section>
      <section className="services-section" id="services"><div className="section-heading"><div><div className="eyebrow">ONE PLATFORM, MANY MOVES</div><h2>Big move or small.<br/><em>We make room for it.</em></h2></div><p>Choose a vehicle that fits your load, then tell us where you're headed. We’ll help you take the next step.</p></div><div className="service-grid"><article className="service-card"><div className="service-number">01 / HOME</div><div className="service-illustration home-art"><span className="roof"/><span className="house"/><span className="door"/></div><h3>Home moves</h3><p>Move between bedsitters, apartments and family homes.</p></article><article className="service-card"><div className="service-number">02 / ITEMS</div><div className="service-illustration box-art"><span/><span/><span/></div><h3>Furniture & bulky items</h3><p>Get help with that sofa, fridge, desk or marketplace find.</p></article><article className="service-card"><div className="service-number">03 / BUSINESS</div><div className="service-illustration shop-art"><span/><span/><span/></div><h3>Small business moves</h3><p>Move stock, equipment and office essentials with a plan.</p></article></div></section>
      <section className="auth-section" id="account">
        <div className="auth-copy"><div className="eyebrow">YOUR MOVE, YOUR ACCOUNT</div><h2>Bookings that are <em>yours.</em></h2><p>Create an account to submit moving requests and see your private booking history. Your account details are used for your booking contact information.</p></div>
        <div className="auth-card">
          {user ? <>
            <div className="auth-card-head"><div><span className="form-step">SIGNED IN</span><h3>Welcome, {user.full_name}</h3><p>{user.email} · {user.phone}</p></div><button type="button" className="button button-outline" onClick={signOut}>Sign out</button></div>
            <h4>Your bookings</h4>
            {bookings.length === 0 ? <p className="auth-empty">No bookings yet. Your submitted move requests will appear here.</p> : <div className="booking-history">{bookings.map(item => <article className="history-item" key={item.id}><div><strong>Request #{item.id}</strong><small>{item.pickup} → {item.dropoff}</small><small>{item.move_date} · KES {item.estimated_price_kes.toLocaleString('en-KE')}</small></div><div className="history-actions"><span className="history-status">{item.status}</span>{!['cancelled', 'completed'].includes(item.status) && <button type="button" className="history-cancel" onClick={() => cancelBooking(item.id)}>Cancel</button>}</div></article>)}</div>}
          </> : <>
            <div className="auth-tabs"><button type="button" className={authMode === 'login' ? 'active' : ''} onClick={() => { setAuthMode('login'); setAuthMessage(''); }}>Sign in</button><button type="button" className={authMode === 'register' ? 'active' : ''} onClick={() => { setAuthMode('register'); setAuthMessage(''); }}>Create account</button></div>
            <form className="auth-form" onSubmit={submitAuth}>
              {authMode === 'register' && <><label>Full name<input required minLength={2} maxLength={120} value={authForm.full_name} onChange={e => updateAuth('full_name', e.target.value)} autoComplete="name" placeholder="Your full name"/></label><label>Phone number<input required minLength={7} maxLength={30} value={authForm.phone} onChange={e => updateAuth('phone', e.target.value)} autoComplete="tel" placeholder="07XX XXX XXX"/></label></>}
              <label>Email address<input required type="email" value={authForm.email} onChange={e => updateAuth('email', e.target.value)} autoComplete="email" placeholder="you@example.com"/></label>
              <label>Password<input required minLength={authMode === 'register' ? 12 : 1} maxLength={128} type="password" value={authForm.password} onChange={e => updateAuth('password', e.target.value)} autoComplete={authMode === 'register' ? 'new-password' : 'current-password'} placeholder={authMode === 'register' ? 'At least 12 characters' : 'Your password'}/></label>
              {authMode === 'register' && <label>Confirm password<input required minLength={12} maxLength={128} type="password" value={authForm.password_confirmation} onChange={e => updateAuth('password_confirmation', e.target.value)} autoComplete="new-password" placeholder="Enter password again"/></label>}
              <button type="submit" className="button button-primary auth-submit" disabled={authBusy}>{authBusy ? 'Please wait…' : authMode === 'register' ? 'Create secure account' : 'Sign in'} <ArrowRight size={17}/></button>
            </form>
          </>}
          {authMessage && <p className="form-message" role="status">{authMessage}</p>}
        </div>
      </section>
      <section className="booking-section" id="book"><div className="booking-intro"><div className="eyebrow">LET'S GET YOU THERE</div><h2>Your next chapter<br/>starts <em>here.</em></h2><p>Share a few details to get an indicative estimate or submit a demo booking request.</p><div className="note"><CheckCircle2 size={20}/><span><strong>No online payment required</strong><small>This MVP is configured for cash on completion. Confirm the final price and provider before the move.</small></span></div><div className="booking-scribble">A smoother move<br/>starts with a plan ↗</div></div>
      <form className="booking-form" onSubmit={bookMove}><div className="form-top"><div><span className="form-step">YOUR MOVE / 01</span><h3>Tell us about it</h3></div><span className="required-note">* Required</span></div><div className="field-grid"><label>Your name<input readOnly value={user?.full_name || ''} placeholder="Sign in to load your account"/></label><label>Phone number<input readOnly value={user?.phone || ''} placeholder="Sign in to load your account"/></label><label className="full">Pickup location *<input required minLength={3} value={form.pickup} onChange={e=>update('pickup',e.target.value)} placeholder="Estate, street or landmark"/></label><label className="full">Drop-off location *<input required minLength={3} value={form.dropoff} onChange={e=>update('dropoff',e.target.value)} placeholder="Where are you moving to?"/></label><label>Moving date *<input required type="date" min={new Date().toISOString().slice(0,10)} value={form.move_date} onChange={e=>update('move_date',e.target.value)}/></label><label>What are you moving? <select value={form.property_type} onChange={e=>update('property_type',e.target.value)}><option value="studio">Bedsitter / studio</option><option value="one-bedroom">One-bedroom home</option><option value="two-bedroom">Two-bedroom home</option><option value="three-bedroom">Three-bedroom home</option><option value="office">Office / business</option></select></label><label>Vehicle preference<select value={form.vehicle_type} onChange={e=>update('vehicle_type',e.target.value)}><option value="motorbike">Motorbike / small items</option><option value="pickup">Pickup</option><option value="canter">Canter</option><option value="truck">Large truck</option></select></label><label>How should we find a mover?<select value={form.service_mode} onChange={e=>update('service_mode',e.target.value)}><option value="automatic">Match me automatically</option><option value="choose_provider">I want to choose a provider</option></select></label><label className="full">Extra details<textarea rows={3} value={form.inventory_notes} onChange={e=>update('inventory_notes',e.target.value)} placeholder="Furniture, number of boxes, stairs, special handling…"/></label></div><div className="estimate-row"><div><span>INDICATIVE ESTIMATE</span><strong>{quote === null ? '—' : `KES ${quote.toLocaleString('en-KE')}`}</strong></div><button type="button" className="button button-outline" onClick={getQuote} disabled={busy}>{busy?'Working…':'Calculate estimate'}</button></div><button type="submit" className="button button-primary submit-button" disabled={busy || !user}>{busy?'Please wait…':'Submit move request'} <ArrowRight size={18}/></button>{message && <p className="form-message" role="status">{message}</p>}<p className="fine-print">Estimates are illustrative and not distance-based yet. Submitting does not guarantee a mover or confirm a booking.</p></form></section>
      <section className="how-section" id="how"><div className="eyebrow">SIMPLE BY DESIGN</div><h2>Three steps. <em>Less stress.</em></h2><div className="steps"><div><span>01</span><h3>Tell us what’s moving</h3><p>Add your locations, date and the size of your move.</p></div><div><span>02</span><h3>Find your fit</h3><p>Choose a provider or request automatic matching.</p></div><div><span>03</span><h3>Move with confidence</h3><p>Confirm the final quote, complete your move and pay as agreed.</p></div></div></section>
    </main><footer><a className="brand footer-brand" href="#top"><span className="brand-mark"><Truck size={20}/></span><span>Mtaa<span className="brand-light">Move</span></span></a><p>Moving forward, together.</p><span className="footer-tag">BUILT FOR LOCAL MOVES · KENYA</span><small>Prototype interface — provider verification, live dispatch and Google Maps routing are not yet enabled.</small></footer>
  </div>;
}
