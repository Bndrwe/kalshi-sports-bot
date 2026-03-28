/**
 * Bot Orchestrator — ties together Kalshi client, sports data, and strategy.
 * Runs entirely in-browser with setInterval for automated scanning.
 */

import { KalshiClient } from './kalshi-client.js';
import {
  getMLBSchedule, analyzeBaseballGame,
  parseTennisMatch, analyzeTennisMatch,
} from './sports-data.js';
import { StrategyEngine } from './strategy.js';

const DEFAULT_CONFIG = {
  min_edge: 0.08,
  min_confidence: 0.60,
  max_position: 50,
  max_daily_loss: 200,
  kelly_fraction: 0.25,
  max_kelly_bet: 0.10,
  scan_interval: 120,
};

export class TradingBot {
  constructor() {
    this.kalshi = new KalshiClient();
    this.strategy = new StrategyEngine({ ...DEFAULT_CONFIG });
    this.running = false;
    this.mode = 'paper';
    this.scanCount = 0;
    this.lastScanTime = null;
    this._intervalId = null;
    this.errors = [];
    this.logs = [];
    this._onUpdate = null; // callback for UI refresh
  }

  log(level, msg) {
    const entry = { time: new Date().toISOString(), level, msg };
    this.logs.push(entry);
    if (this.logs.length > 500) this.logs = this.logs.slice(-300);
    console.log(`[${level}] ${msg}`);
  }

  // ── Credentials ────────────────────────────────────────────────

  async connect(apiKeyId, privateKeyPem, useDemo = true) {
    await this.kalshi.setCredentials(apiKeyId, privateKeyPem, useDemo);
    const balance = await this.kalshi.getBalance();
    this.strategy.stats.balance_cents = balance.balance || 0;
    this.log('INFO', `Connected. Balance: $${(balance.balance / 100).toFixed(2)}`);
    return balance;
  }

  // ── Scanning ───────────────────────────────────────────────────

  async scan() {
    this.scanCount++;
    this.lastScanTime = new Date().toISOString();
    this.log('INFO', `=== Scan #${this.scanCount} ===`);

    const tennisSignals = await this._scanTennis();
    const baseballSignals = await this._scanBaseball();
    const all = [...tennisSignals, ...baseballSignals];

    let executed = 0;
    for (const sig of all) {
      if (sig.status === 'pending') {
        await this._execute(sig);
        executed++;
      }
    }

    this.log('INFO', `Scan complete: ${tennisSignals.length} tennis, ${baseballSignals.length} baseball, ${executed} executed`);
    if (this._onUpdate) this._onUpdate();
    return { tennis: tennisSignals.length, baseball: baseballSignals.length, executed };
  }

  async _scanTennis() {
    const signals = [];
    try {
      const markets = await this.kalshi.findTennisMarkets();
      this.log('INFO', `Found ${markets.length} tennis markets`);
      for (const market of markets) {
        if (market.status !== 'open') continue;
        const parsed = parseTennisMatch(market._event_title || market.title || '');
        if (!parsed) continue;
        const analysis = analyzeTennisMatch(parsed.player1, parsed.player2, parsed.surface);
        const signal = this.strategy.generateSignal(market, analysis, 'tennis');
        if (signal) signals.push(signal);
      }
    } catch (e) {
      this.log('ERROR', `Tennis scan: ${e.message}`);
      this.errors.push({ time: new Date().toISOString(), error: e.message, sport: 'tennis' });
    }
    return signals;
  }

  async _scanBaseball() {
    const signals = [];
    try {
      const markets = await this.kalshi.findBaseballMarkets();
      this.log('INFO', `Found ${markets.length} baseball markets`);
      const schedule = await getMLBSchedule();

      for (const market of markets) {
        if (market.status !== 'open') continue;
        // Try to match market to MLB game for enriched analysis
        const title = (market._event_title || market.title || '').toLowerCase();
        let matchedGame = null;
        for (const game of schedule) {
          const aN = (game.away_team?.name || '').toLowerCase();
          const hN = (game.home_team?.name || '').toLowerCase();
          if ((title.includes(aN) || aN.includes(title.split(' ')[0])) &&
              (title.includes(hN) || hN.includes(title.split(' ').pop()))) {
            matchedGame = game;
            break;
          }
        }
        let analysis;
        if (matchedGame) {
          analysis = await analyzeBaseballGame(matchedGame);
        } else {
          analysis = {
            home_win_probability: 0.54, away_win_probability: 0.46,
            confidence: 0.1, factors: {}, raw_edge: 0.04,
            away_team: '?', home_team: '?',
          };
        }
        const signal = this.strategy.generateSignal(market, analysis, 'baseball');
        if (signal) signals.push(signal);
      }
    } catch (e) {
      this.log('ERROR', `Baseball scan: ${e.message}`);
      this.errors.push({ time: new Date().toISOString(), error: e.message, sport: 'baseball' });
    }
    return signals;
  }

  async _execute(signal) {
    if (this.mode === 'paper') {
      signal.status = 'paper_filled';
      this.strategy.stats.signals_traded++;
      this.log('INFO', `[PAPER] ${signal.side.toUpperCase()} ${signal.suggested_contracts}x @ ${signal.price_cents}¢ on ${signal.market_ticker}`);
      return;
    }
    if (!this.kalshi.authenticated) {
      signal.status = 'rejected: no credentials';
      return;
    }
    try {
      const result = await this.kalshi.createOrder(
        signal.market_ticker, signal.side, 'buy',
        signal.suggested_contracts, signal.price_cents
      );
      signal.status = result.order?.status || 'placed';
      this.strategy.stats.signals_traded++;
      this.log('INFO', `Order placed: ${result.order?.order_id}`);
    } catch (e) {
      signal.status = `error: ${e.message}`;
      this.log('ERROR', `Order failed: ${e.message}`);
    }
  }

  // ── Bot Loop ───────────────────────────────────────────────────

  start() {
    if (this.running) return;
    this.running = true;
    this.log('INFO', `Bot started in ${this.mode} mode, interval: ${this.strategy.config.scan_interval}s`);
    this.scan(); // immediate first scan
    this._intervalId = setInterval(() => this.scan(), this.strategy.config.scan_interval * 1000);
    if (this._onUpdate) this._onUpdate();
  }

  stop() {
    this.running = false;
    if (this._intervalId) {
      clearInterval(this._intervalId);
      this._intervalId = null;
    }
    this.log('INFO', 'Bot stopped');
    if (this._onUpdate) this._onUpdate();
  }

  setMode(mode) {
    this.mode = mode;
    this.log('INFO', `Mode: ${mode}`);
  }

  // ── State for Dashboard ────────────────────────────────────────

  getState() {
    return {
      running: this.running,
      mode: this.mode,
      scan_count: this.scanCount,
      last_scan_time: this.lastScanTime,
      authenticated: this.kalshi.authenticated,
      config: { ...this.strategy.config },
      strategy_stats: this.strategy.getStats(),
      recent_signals: this.strategy.getSignals(20),
      errors: this.errors.slice(-10),
      logs: this.logs.slice(-200),
    };
  }
}
