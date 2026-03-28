/**
 * Sports Data — client-side analysis engines for Tennis & Baseball.
 * Fetches live data from MLB Stats API (free, no key) and performs all
 * analysis in the browser.
 */

// ══════════════════════════════════════════════════════════════════
//  MLB STATS API
// ══════════════════════════════════════════════════════════════════

const MLB_API = 'https://statsapi.mlb.com/api/v1';

const PARK_FACTORS = {
  'Coors Field': 1.35, 'Great American Ball Park': 1.12,
  'Fenway Park': 1.08, 'Globe Life Field': 1.05,
  'Citizens Bank Park': 1.04, 'Wrigley Field': 1.03,
  'Yankee Stadium': 1.02, 'Guaranteed Rate Field': 1.01,
  'Target Field': 0.99, 'Dodger Stadium': 0.98,
  'Truist Park': 0.97, 'T-Mobile Park': 0.95,
  'Oracle Park': 0.93, 'Petco Park': 0.92,
  'Tropicana Field': 0.91, 'Oakland Coliseum': 0.90,
  'Busch Stadium': 1.00, 'Camden Yards': 1.01,
  'Kauffman Stadium': 0.97, 'Chase Field': 1.06,
  'Rogers Centre': 1.00, 'Angel Stadium': 0.97,
  'Minute Maid Park': 1.03, 'PNC Park': 0.94,
  'American Family Field': 1.02, 'Nationals Park': 1.00,
  'Comerica Park': 0.96, 'loanDepot park': 0.95,
  'Oriole Park at Camden Yards': 1.01,
};

const _cache = new Map();
const CACHE_TTL = 30 * 60 * 1000; // 30 min

async function cachedFetch(url) {
  const now = Date.now();
  if (_cache.has(url)) {
    const { ts, data } = _cache.get(url);
    if (now - ts < CACHE_TTL) return data;
  }
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const data = await res.json();
    _cache.set(url, { ts: now, data });
    return data;
  } catch {
    return null;
  }
}

// ── MLB Schedule ─────────────────────────────────────────────────

export async function getMLBSchedule(date) {
  if (!date) date = new Date().toISOString().split('T')[0];
  const data = await cachedFetch(
    `${MLB_API}/schedule?sportId=1&date=${date}&hydrate=team,probablePitcher,linescore`
  );
  if (!data) return [];
  const games = [];
  for (const d of (data.dates || [])) {
    for (const g of (d.games || [])) {
      games.push(parseGame(g));
    }
  }
  return games;
}

function parseGame(g) {
  const away = g.teams?.away || {};
  const home = g.teams?.home || {};
  const venue = g.venue?.name || '';
  return {
    game_id: g.gamePk,
    status: g.status?.detailedState || '',
    venue,
    game_date: g.gameDate || '',
    away_team: {
      id: away.team?.id, name: away.team?.name || '',
      abbreviation: away.team?.abbreviation || '',
      record: `${away.leagueRecord?.wins || 0}-${away.leagueRecord?.losses || 0}`,
    },
    home_team: {
      id: home.team?.id, name: home.team?.name || '',
      abbreviation: home.team?.abbreviation || '',
      record: `${home.leagueRecord?.wins || 0}-${home.leagueRecord?.losses || 0}`,
    },
    away_pitcher: {
      id: away.probablePitcher?.id, name: away.probablePitcher?.fullName || 'TBD',
    },
    home_pitcher: {
      id: home.probablePitcher?.id, name: home.probablePitcher?.fullName || 'TBD',
    },
    park_factor: PARK_FACTORS[venue] || 1.0,
  };
}

// ── Pitcher Stats ────────────────────────────────────────────────

const EMPTY_PITCHER = {
  era: 4.50, whip: 1.30, k_per_9: 8.0, bb_per_9: 3.0,
  innings_pitched: 0, wins: 0, losses: 0, hr_per_9: 1.0,
  batting_avg_against: 0.250,
};

export async function getPitcherStats(pitcherId, season) {
  if (!pitcherId) return { ...EMPTY_PITCHER };
  season = season || new Date().getFullYear();
  const data = await cachedFetch(
    `${MLB_API}/people/${pitcherId}/stats?stats=season&season=${season}&group=pitching`
  );
  if (!data) return { ...EMPTY_PITCHER };
  try {
    const s = data.stats[0].splits[0].stat;
    return {
      era: parseFloat(s.era) || 4.50,
      whip: parseFloat(s.whip) || 1.30,
      k_per_9: parseFloat(s.strikeoutsPer9Inn) || 8.0,
      bb_per_9: parseFloat(s.walksPer9Inn) || 3.0,
      innings_pitched: parseFloat(s.inningsPitched) || 0,
      wins: parseInt(s.wins) || 0,
      losses: parseInt(s.losses) || 0,
      hr_per_9: parseFloat(s.homeRunsPer9) || 1.0,
      batting_avg_against: parseFloat(s.avg) || 0.250,
    };
  } catch {
    return { ...EMPTY_PITCHER };
  }
}

// ── Team Batting ─────────────────────────────────────────────────

const EMPTY_BATTING = {
  avg: 0.250, obp: 0.320, slg: 0.400, ops: 0.720, runs_per_game: 4.5,
};

export async function getTeamBatting(teamId, season) {
  if (!teamId) return { ...EMPTY_BATTING };
  season = season || new Date().getFullYear();
  const data = await cachedFetch(
    `${MLB_API}/teams/${teamId}/stats?stats=season&season=${season}&group=hitting`
  );
  if (!data) return { ...EMPTY_BATTING };
  try {
    const s = data.stats[0].splits[0].stat;
    const gp = parseInt(s.gamesPlayed) || 1;
    return {
      avg: parseFloat(s.avg) || 0.250,
      obp: parseFloat(s.obp) || 0.320,
      slg: parseFloat(s.slg) || 0.400,
      ops: parseFloat(s.ops) || 0.720,
      runs_per_game: (parseInt(s.runs) || 0) / gp,
    };
  } catch {
    return { ...EMPTY_BATTING };
  }
}

// ── Team Bullpen ─────────────────────────────────────────────────

export async function getTeamBullpen(teamId, season) {
  if (!teamId) return { era: 4.00, whip: 1.30 };
  season = season || new Date().getFullYear();
  const data = await cachedFetch(
    `${MLB_API}/teams/${teamId}/stats?stats=season&season=${season}&group=pitching`
  );
  if (!data) return { era: 4.00, whip: 1.30 };
  try {
    const s = data.stats[0].splits[0].stat;
    return {
      era: parseFloat(s.era) || 4.00,
      whip: parseFloat(s.whip) || 1.30,
      saves: parseInt(s.saves) || 0,
      blown_saves: parseInt(s.blownSaves) || 0,
      k_per_9: parseFloat(s.strikeoutsPer9Inn) || 8.0,
    };
  } catch {
    return { era: 4.00, whip: 1.30 };
  }
}

// ── Team Recent Form ─────────────────────────────────────────────

export async function getTeamRecentForm(teamId, lastN = 10) {
  if (!teamId) return { wins: 0, losses: 0, win_pct: 0.5, run_diff: 0 };
  const today = new Date();
  const start = new Date(today - 30 * 86400000).toISOString().split('T')[0];
  const end = today.toISOString().split('T')[0];
  const data = await cachedFetch(
    `${MLB_API}/schedule?sportId=1&teamId=${teamId}&startDate=${start}&endDate=${end}&gameType=R`
  );
  if (!data) return { wins: 0, losses: 0, win_pct: 0.5, run_diff: 0 };

  const finished = [];
  for (const d of (data.dates || [])) {
    for (const g of (d.games || [])) {
      if (g.status?.detailedState === 'Final') finished.push(g);
    }
  }
  const recent = finished.slice(-lastN);
  let wins = 0, losses = 0, runDiff = 0;
  for (const g of recent) {
    const away = g.teams?.away || {};
    const home = g.teams?.home || {};
    if (away.team?.id === teamId) {
      if (away.isWinner) wins++; else losses++;
      runDiff += (away.score || 0) - (home.score || 0);
    } else {
      if (home.isWinner) wins++; else losses++;
      runDiff += (home.score || 0) - (away.score || 0);
    }
  }
  return {
    wins, losses,
    win_pct: wins / Math.max(wins + losses, 1),
    run_diff: runDiff,
    games_played: recent.length,
  };
}

// ══════════════════════════════════════════════════════════════════
//  BASEBALL GAME ANALYSIS
// ══════════════════════════════════════════════════════════════════

const BASEBALL_WEIGHTS = {
  pitching: 0.25, batting: 0.20, bullpen: 0.15,
  park_factor: 0.10, weather: 0.05, recent_form: 0.15, injuries: 0.10,
};

export async function analyzeBaseballGame(game) {
  const [awayP, homeP, awayBat, homeBat, awayBP, homeBP, awayForm, homeForm] =
    await Promise.all([
      getPitcherStats(game.away_pitcher?.id),
      getPitcherStats(game.home_pitcher?.id),
      getTeamBatting(game.away_team?.id),
      getTeamBatting(game.home_team?.id),
      getTeamBullpen(game.away_team?.id),
      getTeamBullpen(game.home_team?.id),
      getTeamRecentForm(game.away_team?.id),
      getTeamRecentForm(game.home_team?.id),
    ]);

  const pitchingFactor = ((4.50 - homeP.era) / 4.50) - ((4.50 - awayP.era) / 4.50);
  const battingFactor = (homeBat.ops - awayBat.ops) * 2.0;
  const bpFactor = (awayBP.era - homeBP.era) / 4.50;
  const pf = game.park_factor || 1.0;
  const parkFactor = (pf - 1.0) * 0.5;
  const formFactor = homeForm.win_pct - awayForm.win_pct;
  const homeBase = 0.04;

  const rawEdge = homeBase
    + BASEBALL_WEIGHTS.pitching * pitchingFactor
    + BASEBALL_WEIGHTS.batting * battingFactor
    + BASEBALL_WEIGHTS.bullpen * bpFactor
    + BASEBALL_WEIGHTS.park_factor * parkFactor
    + BASEBALL_WEIGHTS.recent_form * formFactor;

  const homeProb = Math.min(0.95, Math.max(0.05, 1 / (1 + Math.exp(-3 * rawEdge))));

  return {
    game_id: game.game_id,
    away_team: game.away_team?.name,
    home_team: game.home_team?.name,
    venue: game.venue,
    home_win_probability: +homeProb.toFixed(4),
    away_win_probability: +(1 - homeProb).toFixed(4),
    confidence: +(Math.abs(homeProb - 0.5) * 2).toFixed(4),
    factors: {
      pitching: {
        away_pitcher: game.away_pitcher?.name, home_pitcher: game.home_pitcher?.name,
        away_era: awayP.era, home_era: homeP.era, factor: +pitchingFactor.toFixed(3),
      },
      batting: {
        away_ops: awayBat.ops, home_ops: homeBat.ops, factor: +battingFactor.toFixed(3),
      },
      bullpen: {
        away_era: awayBP.era, home_era: homeBP.era, factor: +bpFactor.toFixed(3),
      },
      park: { venue: game.venue, factor: +pf.toFixed(3) },
      recent_form: { away: awayForm, home: homeForm, factor: +formFactor.toFixed(3) },
    },
    raw_edge: +rawEdge.toFixed(4),
  };
}

// ══════════════════════════════════════════════════════════════════
//  TENNIS MATCH ANALYSIS
// ══════════════════════════════════════════════════════════════════

const TENNIS_WEIGHTS = {
  surface: 0.20, form: 0.25, h2h: 0.15,
  fatigue: 0.15, ranking: 0.10, serve: 0.10, mental: 0.05,
};

const SURFACE_KEYWORDS = {
  clay: ['roland garros', 'french open', 'clay', 'rome', 'madrid', 'monte carlo', 'barcelona'],
  grass: ['wimbledon', 'grass', 'queen', 'halle', 'stuttgart', 'eastbourne'],
};

export function detectSurface(title) {
  const t = title.toLowerCase();
  for (const [surface, kws] of Object.entries(SURFACE_KEYWORDS)) {
    if (kws.some(kw => t.includes(kw))) return surface;
  }
  return 'hard';
}

export function parseTennisMatch(title) {
  const vsMatch = title.match(/(.+?)\s+(?:vs\.?|v\.?)\s+(.+?)(?:\s*[-–—]|\s*\?|$)/i);
  const beatMatch = title.match(/Will\s+(.+?)\s+beat\s+(.+?)\?/i);
  const m = vsMatch || beatMatch;
  if (!m) return null;
  return {
    player1: m[1].trim(),
    player2: m[2].trim(),
    surface: detectSurface(title),
  };
}

export function analyzeTennisMatch(player1, player2, surface) {
  // Client-side analysis uses ranking heuristics and surface factors.
  // Without a live tennis stats API, we use a baseline model.
  // In production, plug in a tennis data provider here.

  const surfaceFactors = { hard: 0.0, clay: 0.0, grass: 0.0 };
  const rawEdge = 0.0; // Neutral without live data
  const p1Prob = Math.min(0.95, Math.max(0.05, 1 / (1 + Math.exp(-3 * rawEdge))));

  return {
    player1, player2, surface,
    p1_win_probability: +p1Prob.toFixed(4),
    p2_win_probability: +(1 - p1Prob).toFixed(4),
    confidence: +(Math.abs(p1Prob - 0.5) * 2).toFixed(4),
    factors: {
      surface_advantage: { p1: 0, p2: 0 },
      fatigue: { p1: 0, p2: 0 },
      ranking: { p1: 100, p2: 100, factor: 0 },
      recent_form: { p1: 0.5, p2: 0.5 },
      h2h: { p1_wins: 0, p2_wins: 0 },
      serve_dominance: 0,
      mental_strength: 0,
    },
    raw_edge: +rawEdge.toFixed(4),
    note: 'Tennis analysis uses baseline model. Connect a tennis stats API for deeper analysis.',
  };
}
