/**
 * Trading Strategy — edge detection, Kelly criterion sizing, risk management.
 * Runs entirely client-side. State persisted to localStorage.
 */

const STORAGE_KEY = 'kalshi_bot_state';

export class StrategyEngine {
  constructor(config) {
    this.config = config;
    this.signals = [];
    this.stats = {
      signals_generated: 0, signals_traded: 0,
      wins: 0, losses: 0,
      daily_pnl_cents: 0, balance_cents: 0,
    };
    this._dailyLosses = 0;
    this._lastResetDate = new Date().toDateString();
    this._load();
  }

  // ── Persistence ────────────────────────────────────────────────

  _save() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        signals: this.signals.slice(-200),
        stats: this.stats,
        dailyLosses: this._dailyLosses,
        lastResetDate: this._lastResetDate,
        config: this.config,
      }));
    } catch { /* quota exceeded — silently degrade */ }
  }

  _load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const s = JSON.parse(raw);
      this.signals = s.signals || [];
      this.stats = { ...this.stats, ...s.stats };
      this._dailyLosses = s.dailyLosses || 0;
      this._lastResetDate = s.lastResetDate || new Date().toDateString();
      if (s.config) Object.assign(this.config, s.config);
    } catch { /* corrupt storage */ }
  }

  _resetDailyIfNeeded() {
    const today = new Date().toDateString();
    if (today !== this._lastResetDate) {
      this._dailyLosses = 0;
      this.stats.daily_pnl_cents = 0;
      this._lastResetDate = today;
    }
  }

  // ── Edge Detection ─────────────────────────────────────────────

  calculateEdge(modelProb, marketPriceCents) {
    const marketProb = marketPriceCents / 100;
    const yesEdge = modelProb - marketProb;
    const noEdge = (1 - modelProb) - (1 - marketProb);
    if (yesEdge > noEdge && yesEdge > 0) return { edge: yesEdge, side: 'yes' };
    if (noEdge > 0) return { edge: noEdge, side: 'no' };
    return { edge: yesEdge, side: 'yes' };
  }

  // ── Kelly Criterion ────────────────────────────────────────────

  kellyCriterion(probability, oddsDecimal, fraction = 0.25) {
    if (probability <= 0 || probability >= 1) return 0;
    const q = 1 - probability;
    const b = oddsDecimal - 1;
    if (b <= 0) return 0;
    const kelly = (probability * b - q) / b;
    return Math.min(Math.max(0, kelly) * fraction, this.config.max_kelly_bet || 0.10);
  }

  sizePosition(modelProb, marketPriceCents, side, bankrollCents) {
    const price = side === 'yes' ? marketPriceCents : (100 - marketPriceCents);
    if (price <= 0) return { contracts: 0, cost: 0 };
    const oddsDecimal = 100 / price;
    const winProb = side === 'yes' ? modelProb : (1 - modelProb);
    const kellyFrac = this.kellyCriterion(winProb, oddsDecimal, this.config.kelly_fraction);
    if (kellyFrac <= 0) return { contracts: 0, cost: 0 };

    const bankroll = bankrollCents / 100;
    let betDollars = bankroll * kellyFrac;
    betDollars = Math.min(betDollars, this.config.max_position);

    const priceDollars = price / 100;
    let contracts = Math.floor(betDollars / priceDollars);
    contracts = Math.max(1, Math.min(contracts, 100));
    return { contracts, cost: +(contracts * priceDollars).toFixed(2) };
  }

  // ── Risk Filters ───────────────────────────────────────────────

  passesRiskChecks(signal) {
    this._resetDailyIfNeeded();
    const c = this.config;
    if (Math.abs(signal.edge) < c.min_edge) return { pass: false, reason: `Edge ${(signal.edge*100).toFixed(1)}% < ${(c.min_edge*100).toFixed(1)}%` };
    if (signal.confidence < c.min_confidence) return { pass: false, reason: `Confidence too low` };
    if (this._dailyLosses >= c.max_daily_loss) return { pass: false, reason: 'Daily loss limit reached' };
    if (signal.market_probability < 0.05 || signal.market_probability > 0.95) return { pass: false, reason: 'Market too extreme' };
    return { pass: true, reason: 'OK' };
  }

  // ── Signal Generation ──────────────────────────────────────────

  generateSignal(market, analysis, sport) {
    const title = market._event_title || market.title || '';
    const yesBid = market.yes_bid_dollars;
    const yesAsk = market.yes_ask_dollars;
    const lastPrice = market.last_price_dollars;

    let marketPriceCents = 50;
    if (yesBid && yesAsk) {
      marketPriceCents = Math.round(((parseFloat(yesBid) + parseFloat(yesAsk)) / 2) * 100);
    } else if (lastPrice) {
      marketPriceCents = Math.round(parseFloat(lastPrice) * 100);
    }

    const modelProb = sport === 'baseball'
      ? analysis.home_win_probability
      : analysis.p1_win_probability;

    const { edge, side } = this.calculateEdge(modelProb, marketPriceCents);
    if (Math.abs(edge) < this.config.min_edge) return null;

    const bankroll = this.stats.balance_cents || 10000; // default $100
    const { contracts, cost } = this.sizePosition(modelProb, marketPriceCents, side, bankroll);
    if (contracts === 0) return null;

    const price = side === 'yes' ? marketPriceCents : (100 - marketPriceCents);

    const signal = {
      market_ticker: market.ticker || '',
      event_title: title,
      sport,
      side,
      model_probability: modelProb,
      market_probability: marketPriceCents / 100,
      edge: +edge.toFixed(4),
      confidence: analysis.confidence,
      kelly_fraction: this.kellyCriterion(
        side === 'yes' ? modelProb : (1 - modelProb),
        price > 0 ? 100 / price : 0,
        this.config.kelly_fraction
      ),
      suggested_size_dollars: cost,
      suggested_contracts: contracts,
      price_cents: price,
      analysis,
      timestamp: new Date().toISOString(),
      status: 'pending',
    };

    const { pass, reason } = this.passesRiskChecks(signal);
    if (!pass) {
      signal.status = `rejected: ${reason}`;
    }

    this.stats.signals_generated++;
    this.signals.push(signal);
    this._save();
    return signal;
  }

  updateConfig(updates) {
    Object.assign(this.config, updates);
    this._save();
  }

  getStats() { return { ...this.stats }; }
  getSignals(limit = 50) { return this.signals.slice(-limit); }

  clearHistory() {
    this.signals = [];
    this.stats = {
      signals_generated: 0, signals_traded: 0,
      wins: 0, losses: 0, daily_pnl_cents: 0,
      balance_cents: this.stats.balance_cents,
    };
    this._save();
  }
}
