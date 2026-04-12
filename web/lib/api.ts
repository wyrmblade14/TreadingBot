export type BotStatus = {
  status: "running" | "stopped" | "unknown";
  mode: string;
  since: string | null;
  pid: number | null;
  message: string;
};

export type Kpi = {
  label: string;
  value: number;
  display?: string;
  delta?: number;
  tone?: "positive" | "negative" | "neutral";
};

export type DailyPnlPoint = {
  date: string;
  pnl: number;
  trades: number;
};

export type EquityPoint = {
  date: string;
  value: number;
};

export type Trade = {
  id: string;
  symbol: string;
  side: "BUY" | "SELL";
  strategy: string;
  entryTime: string;
  exitTime: string | null;
  entryPrice: number;
  exitPrice: number | null;
  quantity: number;
  pnl: number | null;
  status: "open" | "closed";
};

export type StrategySummary = {
  strategy: string;
  trades: number;
  winRate: number;
  netPnl: number;
  avgPnl: number;
};

export type DashboardData = {
  generatedAt: string;
  source: "api" | "empty";
  bot: BotStatus;
  kpis: Kpi[];
  equity: EquityPoint[];
  dailyPnl: DailyPnlPoint[];
  todayTrades: Trade[];
  recentTrades: Trade[];
  strategies: StrategySummary[];
};

const API_INTERNAL_BASE =
  process.env.DASHBOARD_API_INTERNAL_URL?.replace(/\/$/, "") ||
  process.env.NEXT_PUBLIC_DASHBOARD_API_URL?.replace(/\/$/, "") ||
  "http://localhost:8765";

const API_EXTERNAL_BASE =
  process.env.NEXT_PUBLIC_DASHBOARD_API_URL?.replace(/\/$/, "") ||
  "http://localhost:8765";

const emptyBot: BotStatus = {
  status: "unknown",
  mode: "paper",
  since: null,
  pid: null,
  message: "Dashboard API is not connected"
};

export async function getDashboardData(): Promise<DashboardData> {
  const payload = await fetchFirstJson([
    `${API_INTERNAL_BASE}/dashboard`,
    `${API_INTERNAL_BASE}/api/dashboard`,
    `${API_INTERNAL_BASE}/api/summary`,
    `${API_EXTERNAL_BASE}/dashboard`,
    `${API_EXTERNAL_BASE}/api/dashboard`,
    `${API_EXTERNAL_BASE}/api/summary`
  ]);

  if (!payload) {
    return emptyDashboard();
  }

  return normalizeDashboard(payload);
}

async function fetchFirstJson(urls: string[]): Promise<unknown | null> {
  for (const url of urls) {
    try {
      const response = await fetch(url, {
        cache: "no-store",
        headers: { accept: "application/json" },
        next: { revalidate: 0 }
      });

      if (response.ok) {
        return await response.json();
      }
    } catch {
      continue;
    }
  }

  return null;
}

function emptyDashboard(): DashboardData {
  return {
    generatedAt: new Date().toISOString(),
    source: "empty",
    bot: emptyBot,
    kpis: [
      { label: "Virtual Capital", value: 100000, display: "INR 1,00,000" },
      { label: "Total P&L", value: 0, display: "INR 0", tone: "neutral" },
      { label: "Today P&L", value: 0, display: "INR 0", tone: "neutral" },
      { label: "Trades Today", value: 0, display: "0" }
    ],
    equity: [],
    dailyPnl: [],
    todayTrades: [],
    recentTrades: [],
    strategies: []
  };
}

function normalizeDashboard(input: unknown): DashboardData {
  const record = asRecord(input);
  const tradeRecord = asRecord(record.trades);
  const marketRecord = asRecord(record.market);
  const rootTradeRecord = Object.keys(tradeRecord).length > 0 ? tradeRecord : record;

  const trades = normalizeTrades(
    firstArray(rootTradeRecord, ["recentTrades", "recent_trades", "trades", "journal"])
  );
  const todayTrades = normalizeTrades(
    firstArray(rootTradeRecord, ["todayTrades", "today_trades"])
  );
  const dailyPnl = normalizeDailyPnl(
    firstArray(rootTradeRecord, ["dailyPnl", "daily_pnl", "daily"])
  );
  const equity = normalizeEquity(firstArray(rootTradeRecord, ["equity", "equityCurve"]));
  const strategies = normalizeStrategies(
    firstArray(rootTradeRecord, ["strategies", "strategySummary", "strategy_summary"])
  );
  const normalizedEquity = equity.length > 0 ? equity : equityFromDailyPnl(dailyPnl, rootTradeRecord);

  return {
    generatedAt: stringValue(record.generatedAt ?? record.generated_at) ?? new Date().toISOString(),
    source: "api",
    bot: normalizeBot(record.bot ?? record),
    kpis: normalizeKpis(firstArray(rootTradeRecord, ["kpis", "metrics"]), {
      dailyPnl,
      todayTrades,
      recentTrades: trades,
      equity: normalizedEquity
    }),
    equity: normalizedEquity,
    dailyPnl,
    todayTrades,
    recentTrades: trades,
    strategies: strategies.length > 0 ? strategies : normalizeStrategies(firstArray(marketRecord, ["strategies"]))
  };
}

function normalizeBot(input: unknown): BotStatus {
  if (typeof input === "string") {
    const status = input.toLowerCase();
    return {
      ...emptyBot,
      status: status === "running" || status === "stopped" ? status : "unknown"
    };
  }

  const record = asRecord(input);
  const status = stringValue(record.status)?.toLowerCase();

  return {
    status: status === "running" || status === "stopped" ? status : "unknown",
    mode: stringValue(record.mode ?? record.trading_mode) ?? "paper",
    since: stringValue(record.since ?? record.started_at ?? record.startedAt),
    pid: numberValue(record.pid),
    message: stringValue(record.message ?? record.reason) ?? "Status available"
  };
}

function normalizeKpis(
  input: unknown[],
  fallback: Pick<DashboardData, "dailyPnl" | "todayTrades" | "recentTrades" | "equity">
): Kpi[] {
  const fromApi = input
    .map((item): Kpi | null => {
      const record = asRecord(item);
      const label = stringValue(record.label ?? record.name);
      if (!label) {
        return null;
      }

      const value = numberValue(record.value) ?? 0;
      return {
        label,
        value,
        display: stringValue(record.display) ?? undefined,
        delta: numberValue(record.delta) ?? undefined,
        tone: toneValue(record.tone)
      };
    })
    .filter((item): item is Kpi => item !== null);

  if (fromApi.length > 0) {
    return fromApi;
  }

  const totalPnl = fallback.dailyPnl.reduce((sum, day) => sum + day.pnl, 0);
  const latestEquity = fallback.equity.at(-1)?.value ?? 100000 + totalPnl;
  const todayPnl = fallback.dailyPnl.at(-1)?.pnl ?? 0;

  return [
    { label: "Portfolio Value", value: latestEquity },
    { label: "Total P&L", value: totalPnl, tone: pnlTone(totalPnl) },
    { label: "Today P&L", value: todayPnl, tone: pnlTone(todayPnl) },
    { label: "Trades Today", value: fallback.todayTrades.length }
  ];
}

function normalizeDailyPnl(input: unknown[]): DailyPnlPoint[] {
  return input
    .map((item) => {
      const record = asRecord(item);
      const date = stringValue(record.date ?? record.day);
      if (!date) {
        return null;
      }

      return {
        date,
        pnl: numberValue(record.pnl ?? record.net_pnl ?? record.netPnl) ?? 0,
        trades: numberValue(record.trades ?? record.num_trades ?? record.numTrades) ?? 0
      };
    })
    .filter((item): item is DailyPnlPoint => item !== null);
}

function equityFromDailyPnl(input: DailyPnlPoint[], record: Record<string, unknown>): EquityPoint[] {
  const initialCapital =
    numberValue(record.initialCapital ?? record.initial_capital ?? record.capital) ?? 100000;
  let running = initialCapital;

  return input.map((point) => {
    running += point.pnl;
    return {
      date: point.date,
      value: running
    };
  });
}

function normalizeEquity(input: unknown[]): EquityPoint[] {
  return input
    .map((item) => {
      const record = asRecord(item);
      const date = stringValue(record.date ?? record.day ?? record.timestamp);
      const value = numberValue(record.value ?? record.equity ?? record.portfolio_value);
      if (!date || value === null) {
        return null;
      }

      return { date, value };
    })
    .filter((item): item is EquityPoint => item !== null);
}

function normalizeTrades(input: unknown[]): Trade[] {
  return input
    .map((item, index): Trade => {
      const record = asRecord(item);
      const symbol = stringValue(record.symbol) ?? "UNKNOWN";
      const side: Trade["side"] =
        stringValue(record.side ?? record.action)?.toUpperCase() === "SELL" ? "SELL" : "BUY";
      const exitPrice = numberValue(record.exitPrice ?? record.exit_price);
      const pnl = numberValue(record.pnl ?? record.net_pnl ?? record.netPnl);

      return {
        id: stringValue(record.id ?? record.trade_id) ?? `${symbol}-${index}`,
        symbol,
        side,
        strategy: stringValue(record.strategy) ?? "unknown",
        entryTime: stringValue(record.entryTime ?? record.entry_time ?? record.timestamp) ?? "",
        exitTime: stringValue(record.exitTime ?? record.exit_time ?? record.exit_timestamp),
        entryPrice: numberValue(record.entryPrice ?? record.entry_price) ?? 0,
        exitPrice,
        quantity: numberValue(record.quantity ?? record.qty) ?? 0,
        pnl,
        status: exitPrice === null ? "open" : "closed"
      };
    })
    .filter((trade) => trade.symbol !== "UNKNOWN" || trade.strategy !== "unknown");
}

function normalizeStrategies(input: unknown[]): StrategySummary[] {
  return input
    .map((item) => {
      const record = asRecord(item);
      const strategy = stringValue(record.strategy ?? record.name);
      if (!strategy) {
        return null;
      }

      return {
        strategy,
        trades: numberValue(record.trades ?? record.num_trades ?? record.numTrades) ?? 0,
        winRate: numberValue(record.winRate ?? record.win_rate ?? record.win_rate_pct) ?? 0,
        netPnl: numberValue(record.netPnl ?? record.net_pnl ?? record.total_net_pnl) ?? 0,
        avgPnl: numberValue(record.avgPnl ?? record.avg_pnl ?? record.avg_net_pnl) ?? 0
      };
    })
    .filter((item): item is StrategySummary => item !== null);
}

function firstArray(record: Record<string, unknown>, keys: string[]): unknown[] {
  for (const key of keys) {
    if (Array.isArray(record[key])) {
      return record[key];
    }
  }

  return [];
}

function asRecord(input: unknown): Record<string, unknown> {
  return input && typeof input === "object" && !Array.isArray(input)
    ? (input as Record<string, unknown>)
    : {};
}

function stringValue(input: unknown): string | null {
  return typeof input === "string" && input.trim() ? input : null;
}

function numberValue(input: unknown): number | null {
  if (typeof input === "number" && Number.isFinite(input)) {
    return input;
  }

  if (typeof input === "string" && input.trim()) {
    const parsed = Number(input.replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
}

function toneValue(input: unknown): Kpi["tone"] {
  return input === "positive" || input === "negative" || input === "neutral"
    ? input
    : undefined;
}

function pnlTone(value: number): Kpi["tone"] {
  if (value > 0) {
    return "positive";
  }

  if (value < 0) {
    return "negative";
  }

  return "neutral";
}
