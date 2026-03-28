/**
 * Kalshi API Client — runs entirely in the browser.
 * Public endpoints need no auth. Authenticated endpoints use Web Crypto API
 * to sign requests with RSA-PSS (same algorithm as the Python backend).
 */

const KALSHI_BASE = 'https://api.elections.kalshi.com/trade-api/v2';
const KALSHI_DEMO = 'https://demo-api.kalshi.co/trade-api/v2';

export class KalshiClient {
  constructor() {
    this.apiKeyId = '';
    this._privateKey = null;   // CryptoKey object
    this._privateKeyPem = '';
    this.useDemo = true;
    this.authenticated = false;
  }

  get baseUrl() {
    return this.useDemo ? KALSHI_DEMO : KALSHI_BASE;
  }

  // ── Auth Setup ──────────────────────────────────────────────────

  async setCredentials(apiKeyId, privateKeyPem, useDemo = true) {
    this.apiKeyId = apiKeyId;
    this._privateKeyPem = privateKeyPem;
    this.useDemo = useDemo;
    this._privateKey = await this._importKey(privateKeyPem);
    this.authenticated = true;
  }

  async _importKey(pem) {
    const pemBody = pem
      .replace(/-----BEGIN (RSA )?PRIVATE KEY-----/, '')
      .replace(/-----END (RSA )?PRIVATE KEY-----/, '')
      .replace(/\s/g, '');
    const binaryDer = Uint8Array.from(atob(pemBody), c => c.charCodeAt(0));
    return crypto.subtle.importKey(
      'pkcs8',
      binaryDer.buffer,
      { name: 'RSA-PSS', hash: 'SHA-256' },
      false,
      ['sign']
    );
  }

  async _sign(message) {
    const enc = new TextEncoder().encode(message);
    const sig = await crypto.subtle.sign(
      { name: 'RSA-PSS', saltLength: 32 },
      this._privateKey,
      enc
    );
    return btoa(String.fromCharCode(...new Uint8Array(sig)));
  }

  _authHeaders(method, path) {
    // Returns a promise because signing is async
    const ts = Date.now().toString();
    const pathNoQuery = path.split('?')[0];
    return this._sign(ts + method.toUpperCase() + pathNoQuery).then(sig => ({
      'KALSHI-ACCESS-KEY': this.apiKeyId,
      'KALSHI-ACCESS-SIGNATURE': sig,
      'KALSHI-ACCESS-TIMESTAMP': ts,
    }));
  }

  async _get(path, params = {}, auth = false) {
    const qs = new URLSearchParams(params).toString();
    const fullPath = qs ? `${path}?${qs}` : path;
    const url = this.baseUrl + fullPath;
    const headers = auth && this.authenticated ? await this._authHeaders('GET', path) : {};
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(`Kalshi API ${res.status}: ${await res.text()}`);
    return res.json();
  }

  async _post(path, data) {
    const url = this.baseUrl + path;
    const headers = {
      'Content-Type': 'application/json',
      ...(this.authenticated ? await this._authHeaders('POST', path) : {}),
    };
    const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(data) });
    if (!res.ok) throw new Error(`Kalshi API ${res.status}: ${await res.text()}`);
    return res.json();
  }

  async _delete(path) {
    const url = this.baseUrl + path;
    const headers = this.authenticated ? await this._authHeaders('DELETE', path) : {};
    const res = await fetch(url, { method: 'DELETE', headers });
    if (!res.ok) throw new Error(`Kalshi API ${res.status}: ${await res.text()}`);
    return res.json();
  }

  // ── Public Market Data (no auth) ───────────────────────────────

  async getEvents(params = {}) {
    const defaults = { status: 'open', limit: 200, with_nested_markets: 'true' };
    return this._get('/events', { ...defaults, ...params });
  }

  async getEvent(ticker) {
    return this._get(`/events/${ticker}`, { with_nested_markets: 'true' });
  }

  async getMarkets(params = {}) {
    const defaults = { status: 'open', limit: 200 };
    return this._get('/markets', { ...defaults, ...params });
  }

  async getMarket(ticker) {
    return this._get(`/markets/${ticker}`);
  }

  async getOrderbook(ticker) {
    return this._get(`/markets/${ticker}/orderbook`);
  }

  // ── Sports Market Discovery ────────────────────────────────────

  async findSportsMarkets(keywords) {
    const allMarkets = [];
    let cursor = null;
    let pages = 0;
    do {
      const params = { status: 'open', limit: 200, with_nested_markets: 'true' };
      if (cursor) params.cursor = cursor;
      const data = await this._get('/events', params);
      const events = data.events || [];
      for (const event of events) {
        const combined = `${event.title || ''} ${event.sub_title || ''} ${event.category || ''}`.toLowerCase();
        if (keywords.some(kw => combined.includes(kw.toLowerCase()))) {
          for (const m of (event.markets || [])) {
            m._event_title = event.title || '';
            m._event_category = event.category || '';
            allMarkets.push(m);
          }
        }
      }
      cursor = data.cursor;
      pages++;
    } while (cursor && pages < 5);
    return allMarkets;
  }

  async findTennisMarkets() {
    return this.findSportsMarkets([
      'tennis', 'ATP', 'WTA', 'Grand Slam', 'Roland Garros',
      'Wimbledon', 'US Open Tennis', 'Australian Open Tennis',
      'French Open',
    ]);
  }

  async findBaseballMarkets() {
    return this.findSportsMarkets([
      'baseball', 'MLB', 'World Series', 'American League',
      'National League', 'Yankees', 'Dodgers', 'Mets', 'Red Sox',
      'Cubs', 'Astros', 'Braves', 'Phillies', 'Padres',
    ]);
  }

  // ── Portfolio (auth required) ──────────────────────────────────

  async getBalance() {
    return this._get('/portfolio/balance', {}, true);
  }

  async getPositions() {
    return this._get('/portfolio/positions', { settlement_status: 'unsettled' }, true);
  }

  async getFills(limit = 100) {
    return this._get('/portfolio/fills', { limit }, true);
  }

  // ── Orders (auth required) ─────────────────────────────────────

  async createOrder(ticker, side, action, count, priceCents, timeInForce = 'gtc') {
    const data = {
      ticker,
      side,
      action,
      count,
      type: 'limit',
      client_order_id: crypto.randomUUID(),
      time_in_force: timeInForce,
    };
    if (side === 'yes') data.yes_price = priceCents;
    else data.no_price = priceCents;
    return this._post('/portfolio/orders', data);
  }

  async cancelOrder(orderId) {
    return this._delete(`/portfolio/orders/${orderId}`);
  }

  async getOrders(status = 'resting') {
    return this._get('/portfolio/orders', { status }, true);
  }
}
