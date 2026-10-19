/* Stock Ledger front-end (Alpine.js, no build step). */

const BURN_WARN_PCT = 5;        // warn when a closed challan loses more than this %
const AGING_WARN_DAYS = 180;    // amber after this many days with vendor
const AGING_DANGER_DAYS = 300;  // red: close to the 1-year GST deemed-supply limit

const TYPES = {
  PURCHASE:   { label: 'Purchase In',   route: 'purchase',   badge: 'bg-emerald-100 text-emerald-800', btn: 'bg-emerald-600', tile: 'bg-emerald-600' },
  LABOUR_OUT: { label: 'Labour Out',    route: 'labour-out', badge: 'bg-amber-100 text-amber-800',     btn: 'bg-amber-600',   tile: 'bg-amber-600' },
  LABOUR_IN:  { label: 'Labour In',     route: 'labour-in',  badge: 'bg-sky-100 text-sky-800',         btn: 'bg-sky-600',     tile: 'bg-sky-600' },
  SALE:       { label: 'Sale Out',      route: 'sale',       badge: 'bg-rose-100 text-rose-800',       btn: 'bg-rose-600',    tile: 'bg-rose-600' },
  OPENING:    { label: 'Opening Stock', route: 'opening',    badge: 'bg-slate-200 text-slate-800',     btn: 'bg-slate-800',   tile: 'bg-slate-700' },
};
const ROUTE_TYPE = Object.fromEntries(Object.entries(TYPES).map(([k, v]) => [v.route, k]));
const NAV = [
  ['home', '#/', 'Home', 'M3 11l9-8 9 8v9a1 1 0 01-1 1h-5v-6h-6v6H4a1 1 0 01-1-1z'],
  ['stock', '#/stock', 'Stock', 'M3 7l9-4 9 4-9 4-9-4zm0 5l9 4 9-4M3 17l9 4 9-4'],
  ['ledger', '#/ledger', 'Ledger', 'M4 6h16M4 12h16M4 18h10'],
  ['reports', '#/reports', 'Reports', 'M5 20V11M12 20V4M19 20v-6M3 20h18'],
  ['masters', '#/masters', 'Masters', 'M12 15a3 3 0 100-6 3 3 0 000 6zm7.4-3a7.4 7.4 0 00-.1-1.3l2-1.6-2-3.4-2.4 1a7.6 7.6 0 00-2.2-1.3L14.3 3h-4.6l-.4 2.4a7.6 7.6 0 00-2.2 1.3l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 000 2.6l-2 1.6 2 3.4 2.4-1c.7.6 1.4 1 2.2 1.3l.4 2.4h4.6l.4-2.4c.8-.3 1.5-.7 2.2-1.3l2.4 1 2-3.4-2-1.6c.1-.4.1-.9.1-1.3z'],
];
const REPORTS = [
  { key: 'reconciliation', title: 'Item reconciliation', period: true, desc: 'Opening, in, out and closing stock of every item for a period.' },
  { key: 'vendor-pending', title: 'Vendor pending & aging', period: false, desc: 'Material with each vendor right now, grouped by how long it has been out.' },
  { key: 'burn', title: 'Burn %', period: true, desc: 'Loss on challans closed in a period, by vendor and by material.' },
];
const ITEM_TYPES = { RAW: 'Raw material', FG: 'Finished', SCRAP: 'Scrap' };
const ENDPOINT = { purchase: 'purchase', sale: 'sale', opening: 'opening', 'labour-out': 'labour-out', 'labour-in': 'labour-in' };
const FIELD_NAMES = { qty: 'Quantity', item_id: 'Material', party_id: 'Party', vendor_id: 'Vendor', date: 'Date',
  lot_id: 'Challan', fg_qty: 'Finished qty', scrap_qty: 'Scrap qty', name: 'Name', ref_no: 'Bill / invoice / challan no.',
  challan_no: 'Challan no.', remarks: 'Remarks', password: 'Password', hsn: 'HSN', phone: 'Phone', gstin: 'GSTIN', unit: 'Unit' };

const nf = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 3 });
const r3 = (x) => Math.round((+x || 0) * 1000) / 1000;
const num = (x) => nf.format(r3(x));
const dmy = (iso) => { if (!iso) return ''; const [y, m, d] = iso.slice(0, 10).split('-'); return `${d}-${m}-${y}`; };
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked: fine */ } },
};

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (res.status === 401 && !url.startsWith('/api/auth/')) window.dispatchEvent(new Event('auth-lost'));
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) {
      msg = msg.map((d) => {
        const f = FIELD_NAMES[(d.loc || []).slice(-1)[0]] || (d.loc || []).slice(-1)[0];
        if ((d.type || '').startsWith('greater_than')) return `${f} must be more than 0.`;
        if (d.type === 'string_too_long') return `${f} is too long.`;
        if (d.type === 'missing') return `${f} is required.`;
        return `${f}: ${d.msg}`;
      }).join(' ');
    }
    throw new Error(msg || `Something went wrong (${res.status}).`);
  }
  return data;
}

document.addEventListener('alpine:init', () => {
  Alpine.data('app', () => ({
    TYPES, ITEM_TYPES, NAV, REPORTS, BURN_WARN_PCT, num, dmy,
    ready: false,
    auth: { setup_needed: false, users: [], me: null }, login: { user_id: null, password: '', name: '', code: '' },
    meta: { items: [], parties: [], vendors: [], today: '' },
    route: 'home', param: null,
    form: {}, editId: null, saved: null, busy: false,
    toast: null, toastTimer: null,
    sheet: { open: false, title: '', q: '', options: [], groups: [], onPick: null, addParty: false, addItemType: null, adding: false, party: {}, newItem: {} },
    // labour in
    openLots: [], lotStep: 'vendor', lotVendor: null, lot: null,
    // stock
    stock: { items: [], with_vendors: [] }, stockTab: 'RAW', stockQ: '', hideZero: true,
    // ledger
    ledger: [], lf: { entry_type: '', date_from: '', date_to: '', q: '', item_id: null },
    entry: null,
    // masters
    mtab: 'items', mq: '', medit: null, users: [],
    // reports
    rep: { key: null, from: '', to: '', data: null },
    // home
    recent: [], homeLots: [],

    async init() {
      window.addEventListener('hashchange', () => this.auth.me && this.onRoute());
      window.addEventListener('auth-lost', () => { this.auth.me = null; this.loadAuth(); });
      try { await this.loadAuth(); } catch (e) { this.showError(e); }
      if (this.auth.me) await this.start();
      this.ready = true;
    },
    async start() {
      try { await this.loadMeta(); } catch (e) { this.showError(e); }
      await this.onRoute();
    },

    // ------------------------------------------------ login
    async loadAuth() {
      this.auth = await api('GET', '/api/auth/state');
      if (!this.auth.me && this.auth.users.length === 1) this.pickLogin(this.auth.users[0]);
    },
    get canEdit() { return !!this.auth.me && this.auth.me.role === 'EDITOR'; },
    pickLogin(u) { this.login = { user_id: u.id, name: u.name, password: '' }; this.$nextTick(() => { const el = document.getElementById('login-pw'); if (el) el.focus(); }); },
    async doLogin() {
      try {
        if (this.auth.setup_needed) {
          if (!this.login.name.trim()) throw new Error('Enter your name.');
          this.busy = true;
          this.auth.me = await api('POST', '/api/auth/setup', { name: this.login.name, password: this.login.password, code: this.login.code || '' });
        } else {
          if (!this.login.user_id) throw new Error('Tap your name.');
          this.busy = true;
          this.auth.me = await api('POST', '/api/auth/login', { user_id: this.login.user_id, password: this.login.password });
        }
        this.auth.setup_needed = false;
        this.login = { user_id: null, password: '', name: '', code: '' };
        this.toast = null;
        await this.start();
      } catch (e) { this.showError(e); } finally { this.busy = false; }
    },
    async logout() {
      if (!confirm('Log out?')) return;
      try { await api('POST', '/api/auth/logout'); } catch (e) { /* already logged out */ }
      this.auth.me = null;
      await this.loadAuth();
    },
    async loadMeta() { this.meta = await api('GET', '/api/meta'); },

    // ------------------------------------------------ navigation
    go(h) { if (location.hash === h) this.onRoute(); else location.hash = h; },
    back() { if (this.route === 'labour-in' && this.lotStep !== 'vendor' && !this.saved && !this.editId) { this.lotStep = this.lotStep === 'form' ? 'lots' : 'vendor'; return; } history.length > 1 ? history.back() : this.go('#/'); },
    async onRoute() {
      const parts = location.hash.replace(/^#\/?/, '').split('/');
      let r = parts[0] || 'home';
      this.param = parts[1] || null;
      if (!this.canEdit && (r === 'edit' || ROUTE_TYPE[r])) r = 'home';  // viewers can't open entry forms
      this.saved = null; this.sheet.open = false; this.editId = null; this.medit = null; this.toast = null;
      window.scrollTo(0, 0);
      try {
        if (r === 'edit') {
          const e = await api('GET', `/api/entries/${this.param}`);
          const rr = TYPES[e.entry_type].route;
          this.form = { ...this.blankForm(rr), ...e.form };
          const takes = e.entry_type === 'SALE' || (e.entry_type === 'LABOUR_OUT' && !e.form.is_opening);
          this._origFor = { id: e.id, item_id: e.form.item_id, qty: takes ? e.form.qty : 0 };
          this.editId = e.id;
          this.route = rr;
          return;
        }
        if (['purchase', 'sale', 'opening', 'labour-out'].includes(r)) {
          this.form = this.blankForm(r);
          if (r === 'labour-out') this.form.challan_no = (await api('GET', '/api/labour/next-challan')).challan_no;
        }
        if (r === 'labour-in') { this.form = this.blankForm(r); this.lotStep = 'vendor'; this.lot = null; this.lotVendor = null; await this.loadLots(); }
        if (r === 'stock') this.stock = await api('GET', '/api/stock');
        if (r === 'ledger') await this.loadLedger();
        if (r === 'entry') this.entry = await api('GET', `/api/entries/${this.param}`);
        if (r === 'home') await this.loadHome();
        if (r === 'report') { this.rep.key = this.param; this.rep.data = null; if (!this.rep.from) this.setPeriod(this.periods()[2], false); await this.loadReport(); }
        if (r === 'masters' && this.canEdit) await this.loadUsers();
        if (r === 'masters' && !this.canEdit && this.mtab === 'users') this.mtab = 'items';
      } catch (e) { this.showError(e); }
      this.route = r;
    },
    nav(n) { if (n[0] === 'ledger' && this.route !== 'ledger') this.lf = { entry_type: '', date_from: '', date_to: '', q: '', item_id: null }; this.go(n[1]); },
    navOn(n) { return this.route === n[0] || (n[0] === 'ledger' && this.route === 'entry') || (n[0] === 'reports' && this.route === 'report'); },
    get title() {
      const t = ROUTE_TYPE[this.route];
      if (t) return (this.editId ? 'Edit ' : '') + TYPES[t].label;
      if (this.route === 'report') return (this.report && this.report.title) || 'Report';
      return { home: 'Stock Ledger', stock: 'Stock', ledger: 'Ledger', entry: 'Entry', masters: 'Masters', reports: 'Reports' }[this.route] || '';
    },
    get isForm() { return !!ROUTE_TYPE[this.route]; },
    get saveBtn() { const t = ROUTE_TYPE[this.route]; return t ? TYPES[t].btn : 'bg-slate-900'; },

    // ------------------------------------------------ lookups
    item(id) { return this.meta.items.find((i) => i.id === id) || null; },
    itemName(id) { const i = this.item(id); return i ? i.name : ''; },
    party(id) { return this.meta.parties.find((p) => p.id === id) || null; },
    vendor(id) { return this.meta.vendors.find((v) => v.id === id) || null; },
    get activeVendors() { return this.meta.vendors.filter((v) => v.active); },

    blankForm(r) {
      const date = this.meta.today;
      return {
        purchase: { date, item_id: null, party_id: null, qty: '', ref_no: '', remarks: '' },
        sale: { date, item_id: null, party_id: null, qty: '', ref_no: '', remarks: '' },
        opening: { date, item_id: null, qty: '', remarks: '' },
        'labour-out': { date, vendor_id: null, item_id: null, qty: '', challan_no: '', remarks: '', is_opening: false },
        'labour-in': { date, lot_id: null, fg_item_id: null, fg_qty: '', scrap_item_id: null, scrap_qty: '', close: false, ref_no: '', remarks: '' },
      }[r] || {};
    },

    // available stock for the selected item; on edit, add back what this entry already took
    available(itemId) {
      const it = this.item(itemId);
      if (!it) return 0;
      let a = it.stock;
      if (this.editId && this.editOrig && this.editOrig.item_id === itemId) a += this.editOrig.qty || 0;
      return r3(a);
    },

    // ------------------------------------------------ picker sheet
    openSheet(cfg) {
      this.sheet = { open: true, q: '', groups: [], addParty: false, addItemType: null, adding: false, party: {}, newItem: {}, ...cfg };
      this.$nextTick(() => { const el = document.getElementById('sheet-q'); if (el && window.innerWidth > 640) el.focus(); });
    },
    closeSheet() { this.sheet.open = false; },
    get sheetOptions() {
      const q = this.sheet.q.trim().toLowerCase();
      return this.sheet.options.filter((o) => !q || (o.label + ' ' + (o.sub || '')).toLowerCase().includes(q));
    },
    sheetGroup(g) { return this.sheetOptions.filter((o) => o.group === g); },
    pickOption(o) { this.sheet.onPick(o.id); this.closeSheet(); },
    pickFirst() { const o = this.sheet.groups.flatMap((g) => this.sheetGroup(g))[0]; if (o) this.pickOption(o); },

    pickItem(field, { filter = 'all', prefer = null, title = 'Select material' } = {}) {
      let items = this.meta.items.filter((i) => i.active || i.id === this.form[field]);
      if (filter === 'instock') items = items.filter((i) => this.available(i.id) > 0.0005 || i.id === this.form[field]);
      const order = prefer ? [prefer, ...['RAW', 'FG', 'SCRAP'].filter((t) => t !== prefer)] : ['RAW', 'FG', 'SCRAP'];
      const options = items.map((i) => ({ id: i.id, label: i.name, sub: i.hsn ? `HSN ${i.hsn}` : 'No HSN', right: `${num(this.available(i.id))} ${i.unit}`, group: i.type }));
      this.openSheet({ title, options, groups: order, empty: filter === 'instock' ? 'Nothing in stock.' : 'No items found.',
        addItemType: filter === 'all' ? (prefer || 'RAW') : null, onPick: (id) => { this.form[field] = id; } });
    },
    pickParty(field) {
      const options = this.meta.parties.filter((p) => p.active).map((p) => ({ id: p.id, label: p.name, sub: p.gstin || p.phone || '', group: '' }));
      this.openSheet({ title: 'Select party', options, groups: [''], addParty: true, empty: 'No party found.', onPick: (id) => { this.form[field] = id; } });
    },
    startAddParty() { this.sheet.party = { name: this.sheet.q.trim(), gstin: '', phone: '' }; this.sheet.adding = true; },
    startAddItem() { this.sheet.newItem = { name: this.sheet.q.trim(), hsn: '', type: this.sheet.addItemType, unit: 'kg', active: true }; this.sheet.adding = true; },
    async saveNewItem() {
      try {
        if (!this.sheet.newItem.name.trim()) throw new Error('Enter item name.');
        this.busy = true;
        const it = await api('POST', '/api/items', this.sheet.newItem);
        await this.loadMeta();
        this.sheet.onPick(it.id);
        this.closeSheet();
        this.notify(`Added item ${it.name}`);
      } catch (e) { this.showError(e); } finally { this.busy = false; }
    },
    async saveNewParty() {
      try {
        if (!this.sheet.party.name.trim()) throw new Error('Enter party name.');
        this.busy = true;
        const p = await api('POST', '/api/parties', this.sheet.party);
        await this.loadMeta();
        this.sheet.onPick(p.id);
        this.closeSheet();
        this.notify(`Added party ${p.name}`);
      } catch (e) { this.showError(e); } finally { this.busy = false; }
    },

    // ------------------------------------------------ labour in
    async loadLots() { this.openLots = await api('GET', '/api/lots?status=OPEN'); },
    lotsFor(vid) { return this.openLots.filter((l) => l.vendor_id === vid); },
    pendingFor(vid) { return r3(this.lotsFor(vid).reduce((s, l) => s + l.pending, 0)); },
    chooseVendor(v) { this.lotVendor = v; this.lotStep = 'lots'; window.scrollTo(0, 0); },
    metalOf(name) {
      for (const m of ['Copper Nickel', 'Copper Alloys', 'Copper', 'Brass', 'Aluminium']) if (name.startsWith(m)) return m;
      return name.split(' ')[0];
    },
    suggest(rawId, type) {
      const raw = this.item(rawId);
      if (!raw) return null;
      const m = this.metalOf(raw.name);
      const c = this.meta.items.filter((i) => i.active && i.type === type && this.metalOf(i.name) === m);
      return c.length ? c[0].id : null;
    },
    chooseLot(l) {
      this.lot = l;
      const pref = (store.get('li-pref') || {})[l.item_id] || {};
      this.form = { ...this.blankForm('labour-in'), lot_id: l.id,
        fg_item_id: pref.fg || this.suggest(l.item_id, 'FG'),
        scrap_item_id: pref.scrap || this.suggest(l.item_id, 'SCRAP') };
      this.lotStep = 'form';
      window.scrollTo(0, 0);
    },
    get li() {
      const l = this.lot;
      if (!l) return null;
      const fg = +this.form.fg_qty || 0, sc = +this.form.scrap_qty || 0;
      const left = r3(l.pending - fg - sc);
      const closes = this.form.close || Math.abs(left) < 0.0005;
      const burn = this.form.close ? Math.max(left, 0) : 0;
      const burnPct = l.qty_out ? Math.round((burn / l.qty_out) * 10000) / 100 : 0;
      return { fg, sc, left, over: left < -0.0005, closes, burn, burnPct, warn: burnPct > BURN_WARN_PCT };
    },
    agingClass(days) {
      if (days >= AGING_DANGER_DAYS) return 'bg-red-100 text-red-800';
      if (days >= AGING_WARN_DAYS) return 'bg-amber-100 text-amber-800';
      return 'bg-slate-100 text-slate-700';
    },

    // ------------------------------------------------ save
    async save() {
      const r = this.route, f = { ...this.form };
      try {
        if (!f.date) throw new Error('Select date.');
        if (r === 'labour-in') {
          if (!f.lot_id) throw new Error('Select a challan.');
          f.fg_qty = +f.fg_qty || 0; f.scrap_qty = +f.scrap_qty || 0;
          if (f.fg_qty > 0 && !f.fg_item_id) throw new Error('Select finished item.');
          if (f.scrap_qty > 0 && !f.scrap_item_id) throw new Error('Select scrap item.');
          if (f.fg_qty <= 0 && f.scrap_qty <= 0 && !f.close) throw new Error('Enter finished or scrap quantity.');
          if (this.li.over) throw new Error(`Only ${num(this.lot.pending)} kg is pending on this challan.`);
          if (f.close && f.fg_qty <= 0 && f.scrap_qty <= 0 &&
              !confirm(`Close challan with nothing received? All ${num(this.lot.pending)} kg will be counted as burn.`)) return;
          if (f.close && this.li.warn &&
              !confirm(`Burn is ${this.li.burnPct}% (${num(this.li.burn)} kg). That's higher than usual. Save anyway?`)) return;
        } else {
          if (r === 'labour-out' && !f.vendor_id) throw new Error('Select vendor.');
          if (!f.item_id) throw new Error('Select material.');
          if ((r === 'purchase' || r === 'sale') && !f.party_id) throw new Error('Select party.');
          f.qty = +f.qty;
          if (!(f.qty > 0)) throw new Error('Enter quantity.');
          const outgoing = r === 'sale' || (r === 'labour-out' && !f.is_opening);
          if (outgoing && f.qty > this.available(f.item_id) + 0.0005)
            throw new Error(`Only ${num(this.available(f.item_id))} ${this.item(f.item_id).unit} of ${this.itemName(f.item_id)} in stock.`);
        }
        this.busy = true;
        const res = this.editId
          ? await api('PUT', `/api/entries/${this.editId}`, f)
          : await api('POST', `/api/entries/${ENDPOINT[r]}`, f);
        if (r === 'labour-in' && this.lot) {
          const pref = store.get('li-pref') || {};
          pref[this.lot.item_id] = { fg: f.fg_item_id, scrap: f.scrap_item_id };
          store.set('li-pref', pref);
        }
        await this.loadMeta();
        if (r === 'labour-in') await this.loadLots();
        this.saved = res;
        this.toast = null;
        window.scrollTo(0, 0);
      } catch (e) { this.showError(e); } finally { this.busy = false; }
    },
    async again() {
      const r = this.route, keepDate = this.form.date, keepVendor = this.lotVendor;
      this.saved = null; this.editId = null;
      if (r === 'labour-in') {
        this.form = { ...this.blankForm(r), date: keepDate };
        this.lot = null;
        this.lotStep = keepVendor && this.lotsFor(keepVendor.id).length ? 'lots' : 'vendor';
      } else {
        this.form = { ...this.blankForm(r), date: keepDate };
        if (r === 'labour-out') this.form.challan_no = (await api('GET', '/api/labour/next-challan')).challan_no;
      }
      if (location.hash.startsWith('#/edit')) location.hash = `#/${r}`;
      window.scrollTo(0, 0);
    },
    stockNow(itemId) { const i = this.item(itemId); return i ? `${num(i.stock)} ${i.unit}` : ''; },
    savedLot() { return this.saved && this.saved.lot_id ? this.openLots.find((l) => l.id === this.saved.lot_id) : null; },

    // edit support: remember what the entry originally took out, so "available" is right
    get editOrig() {
      if (!this.editId || !this._origFor || this._origFor.id !== this.editId) return null;
      return this._origFor;
    },
    _origFor: null,

    // ------------------------------------------------ stock
    get stockRows() {
      const q = this.stockQ.trim().toLowerCase();
      return this.stock.items.filter((i) => i.type === this.stockTab && (i.active || Math.abs(i.stock) > 0.0005)
        && (!this.hideZero || Math.abs(i.stock) > 0.0005)
        && (!q || (i.name + ' ' + i.hsn).toLowerCase().includes(q)));
    },
    stockTotal(type) { return r3(this.stock.items.filter((i) => i.type === type).reduce((s, i) => s + i.stock, 0)); },
    get vendorGroups() {
      const by = {};
      for (const l of this.stock.with_vendors) (by[l.vendor_name] = by[l.vendor_name] || []).push(l);
      return Object.entries(by).map(([name, lots]) => ({ name, lots, total: r3(lots.reduce((s, l) => s + l.pending, 0)) }));
    },
    get withVendorTotal() { return r3(this.stock.with_vendors.reduce((s, l) => s + l.pending, 0)); },
    openItemLedger(i) { this.lf = { entry_type: '', date_from: '', date_to: '', q: '', item_id: i.id }; this.go('#/ledger'); },

    // ------------------------------------------------ ledger
    async loadLedger() {
      const p = new URLSearchParams();
      for (const [k, v] of Object.entries(this.lf)) if (v) p.set(k, v);
      this.ledger = await api('GET', `/api/entries?${p}`);
    },
    setLf(k, v) { this.lf[k] = v; this.loadLedger().catch((e) => this.showError(e)); },
    get ledgerGroups() {
      const g = [];
      for (const e of this.ledger) {
        if (!g.length || g[g.length - 1].date !== e.date) g.push({ date: e.date, rows: [] });
        g[g.length - 1].rows.push(e);
      }
      return g;
    },
    who(e) { return e.party_name || e.vendor_name || ''; },
    lineText(l) { return `${l.qty > 0 ? '+' : '−'}${num(Math.abs(l.qty))} ${l.unit}`; },
    editEntry(e) { this.go(`#/edit/${e.id}`); },
    async deleteEntry(e) {
      if (!confirm(`Delete this ${TYPES[e.entry_type].label} entry? Stock will be recalculated.`)) return;
      try {
        await api('DELETE', `/api/entries/${e.id}`);
        await this.loadMeta();
        this.notify('Entry deleted');
        history.length > 1 ? history.back() : this.go('#/ledger');
      } catch (err) { this.showError(err); }
    },

    // ------------------------------------------------ home
    async loadHome() {
      const [recent, lots] = await Promise.all([api('GET', `/api/entries?limit=${window.innerWidth >= 1024 ? 12 : 6}`), api('GET', '/api/lots?status=OPEN')]);
      this.recent = recent; this.homeLots = lots;
    },
    get homePending() { return r3(this.homeLots.reduce((s, l) => s + l.pending, 0)); },
    get homeOld() { return this.homeLots.filter((l) => l.days_out >= AGING_WARN_DAYS).length; },

    // ------------------------------------------------ masters
    get masterRows() {
      const q = this.mq.trim().toLowerCase();
      const src = { items: this.meta.items, parties: this.meta.parties, vendors: this.meta.vendors, users: this.users }[this.mtab];
      return src.filter((r) => !q || (r.name + ' ' + (r.hsn || '') + ' ' + (r.gstin || '')).toLowerCase().includes(q));
    },
    editMaster(kind, row) {
      const blank = { items: { name: '', hsn: '', type: 'RAW', unit: 'kg', active: true },
        parties: { name: '', gstin: '', phone: '', active: true }, vendors: { name: '', gstin: '', active: true },
        users: { name: '', role: 'VIEWER', password: '', active: true } }[kind];
      if (!this.canEdit) return;
      this.medit = { kind, id: row ? row.id : null, data: { ...blank, ...(row || {}), ...(kind === 'users' ? { password: '' } : {}) } };
    },
    async loadUsers() { this.users = await api('GET', '/api/users'); },
    async saveMaster() {
      const m = this.medit;
      try {
        if (!m.data.name.trim()) throw new Error('Enter a name.');
        this.busy = true;
        if (m.kind === 'users' && !m.id && !m.data.password) throw new Error('Set a password for the new user.');
        await api(m.id ? 'PUT' : 'POST', `/api/${m.kind}${m.id ? '/' + m.id : ''}`, m.data);
        if (m.kind === 'users') { await this.loadUsers(); await this.loadAuth(); } else await this.loadMeta();
        this.medit = null;
        this.notify('Saved');
      } catch (e) { this.showError(e); } finally { this.busy = false; }
    },

    // ------------------------------------------------ reports
    get report() { return REPORTS.find((r) => r.key === this.rep.key) || null; },
    periods() {
      const t = this.meta.today || new Date().toISOString().slice(0, 10);
      const [y, m] = t.split('-').map(Number);
      const iso = (yy, mm, dd) => `${yy}-${String(mm).padStart(2, '0')}-${String(dd).padStart(2, '0')}`;
      const last = (yy, mm) => new Date(yy, mm, 0).getDate();  // days in month mm
      const fy = m >= 4 ? y : y - 1;
      const [ly, lm] = m === 1 ? [y - 1, 12] : [y, m - 1];
      return [
        ['This month', iso(y, m, 1), t],
        ['Last month', iso(ly, lm, 1), iso(ly, lm, last(ly, lm))],
        [`FY ${fy}-${String(fy + 1).slice(2)}`, iso(fy, 4, 1), t],
        ['Apr–Sep', iso(fy, 4, 1), iso(fy, 9, 30) < t ? iso(fy, 9, 30) : t],
        ['Oct–Mar', iso(fy, 10, 1), iso(fy + 1, 3, 31) < t ? iso(fy + 1, 3, 31) : t],
      ].filter((p) => p[1] <= t);
    },
    setPeriod(p, load = true) { this.rep.from = p[1]; this.rep.to = p[2]; if (load) this.loadReport(); },
    async loadReport() {
      if (!this.report) return;
      const q = this.report.period ? `?date_from=${this.rep.from}&date_to=${this.rep.to}` : '';
      try { this.rep.data = await api('GET', `/api/reports/${this.rep.key}${q}`); } catch (e) { this.showError(e); }
    },
    cell(row, col) {
      const v = row[col[0]];
      if (v === '' || v === null || v === undefined) return '';
      if (col[2] === 'num') return num(v);
      if (col[2] === 'pct') return `${v}%`;
      if (col[2] === 'date') return dmy(v);
      return v;
    },
    exportCSV(t) {
      const esc = (v) => { v = v === null || v === undefined ? '' : String(v); return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v; };
      // text starting with = + - @ would run as a formula in Excel, so make it plain text
      const val = (row, col) => {
        const v = col[2] === 'date' ? dmy(row[col[0]]) : row[col[0]];
        return typeof v === 'string' && /^[=+\-@\t\r]/.test(v) ? `'${v}` : v;
      };
      const lines = [t.cols.map((c) => esc(c[1])), ...t.rows.concat(t.total ? [t.total] : []).map((r) => t.cols.map((c) => esc(val(r, c))))];
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob(['\ufeff' + lines.map((l) => l.join(',')).join('\r\n')], { type: 'text/csv' }));  // BOM so Excel reads UTF-8
      a.download = `${t.key}${this.report.period ? `_${this.rep.from}_to_${this.rep.to}` : `_${this.meta.today}`}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    },

    // ------------------------------------------------ toast
    notify(msg, kind = 'ok') {
      this.toast = { msg, kind };
      clearTimeout(this.toastTimer);
      this.toastTimer = setTimeout(() => { this.toast = null; }, kind === 'err' ? 6000 : 2500);
    },
    showError(e) { this.notify(e.message || String(e), 'err'); },
  }));
});
