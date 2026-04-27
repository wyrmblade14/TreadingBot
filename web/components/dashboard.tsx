import type { DashboardData, MarketOverview, StrategySummary, Trade } from "@/lib/api";
import type { ReactNode } from "react";
import { FreshnessTag } from "@/components/FreshnessTag";
import { RefreshButton } from "@/components/auto-refresh";
import {
  BotIcon,
  ChartIcon,
  ClipboardIcon,
  LayersIcon,
  TableIcon,
  WalletIcon,
  ActivityIcon
} from "@/components/icons";
import { DailyPnlChart, EquityChart } from "@/components/charts";
import {
  formatDateTime,
  formatMoney,
  formatNumber,
  formatPercent,
  formatSignedMoney
} from "@/lib/format";

// ── Page header ────────────────────────────────────────────────────

export function PageHeader({
  apiSource,
  description,
  generatedAt,
  status,
  title
}: {
  apiSource?: DashboardData["source"];
  description: string;
  generatedAt?: string;
  status?: DashboardData["bot"]["status"];
  title: string;
}) {
  return (
    <>
      <header className="pageHeader">
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        <div className="pageHeaderActions">
          {status && <StatusPill status={status} />}
          {generatedAt && <FreshnessTag generatedAt={generatedAt} />}
          <RefreshButton />
        </div>
      </header>
      {apiSource === "empty" && (
        <div className="offlineBanner" role="alert">
          Dashboard API is not responding — showing defaults. Start the bot server to restore live data.
        </div>
      )}
    </>
  );
}

// ── KPI grid ───────────────────────────────────────────────────────

export function KpiGrid({ kpis }: { kpis: DashboardData["kpis"] }) {
  return (
    <section className="kpiGrid" aria-label="Portfolio KPIs">
      {kpis.map((kpi) => (
        <article className="metricCard" data-tone={kpi.tone ?? "neutral"} key={kpi.label}>
          <span>{kpi.label}</span>
          <strong>{kpi.display ?? formatKpiValue(kpi.label, kpi.value)}</strong>
          {typeof kpi.delta === "number" && <small>{formatSignedMoney(kpi.delta)}</small>}
        </article>
      ))}
    </section>
  );
}

// ── Charts ─────────────────────────────────────────────────────────

export function ChartGrid({
  dailyPnl,
  equity
}: {
  dailyPnl: DashboardData["dailyPnl"];
  equity: DashboardData["equity"];
}) {
  return (
    <section className="chartGrid">
      <Panel description="Portfolio value after realised paper P&L." icon={<ChartIcon />} title="Equity Curve">
        <EquityChart data={equity} />
      </Panel>
      <Panel description="Realised day-by-day net P&L from completed trades." icon={<WalletIcon />} title="Daily P&L">
        <DailyPnlChart data={dailyPnl} />
      </Panel>
    </section>
  );
}

// ── Open positions panel ───────────────────────────────────────────

export function OpenPositionsPanel({ trades }: { trades: Trade[] }) {
  const open = trades.filter((t) => t.status === "open");
  const now = new Date();

  if (open.length === 0) {
    return (
      <div className="positionsSection">
        <div className="positionsFlat">
          <span className="flatDot" />
          Flat — no open positions
        </div>
      </div>
    );
  }

  return (
    <div className="positionsSection">
      <div className="positionsHeader">
        <h2 style={{ margin: 0, fontSize: 16 }}>Open Positions</h2>
        <span className="openBadge">{open.length} open</span>
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Strategy</th>
              <th>Entry Time</th>
              <th>Entry ₹</th>
              <th>Qty</th>
              <th>Hold</th>
              <th>P&L</th>
            </tr>
          </thead>
          <tbody>
            {open.map((trade) => (
              <tr key={trade.id}>
                <td><strong>{trade.symbol}</strong></td>
                <td><span className={`tag tag--${trade.side.toLowerCase()}`}>{trade.side}</span></td>
                <td>{humanStrategy(trade.strategy)}</td>
                <td>{formatDateTime(trade.entryTime)}</td>
                <td>{formatMoney(trade.entryPrice)}</td>
                <td>{formatNumber(trade.quantity)}</td>
                <td className="neutralText">{holdDuration(trade.entryTime, now)}</td>
                <td>
                  {trade.pnl === null
                    ? <span className="openBadge">Open</span>
                    : <span className={toneClass(trade.pnl)}>{formatSignedMoney(trade.pnl)}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function holdDuration(entryTime: string, now: Date): string {
  if (!entryTime) return "—";
  const entry = new Date(entryTime);
  if (Number.isNaN(entry.getTime())) return "—";
  const diffMs = now.getTime() - entry.getTime();
  if (diffMs < 0) return "—";
  const h = Math.floor(diffMs / 3600000);
  const m = Math.floor((diffMs % 3600000) / 60000);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

// ── Today trades + journal ─────────────────────────────────────────

export function TradesSection({
  recentTrades,
  todayTrades
}: {
  recentTrades: Trade[];
  todayTrades: Trade[];
}) {
  return (
    <section className="splitGrid">
      <Panel
        description="Open and closed trades for the current trading day."
        icon={<TableIcon />}
        title="Today Trades"
      >
        <TradeTable emptyLabel="No trades today." trades={todayTrades} />
      </Panel>
      <Panel
        description="Latest entries from the paper trade log."
        icon={<ClipboardIcon />}
        title="Recent Journal"
      >
        <TradeList trades={recentTrades} />
      </Panel>
    </section>
  );
}

// ── Trade table (reusable) ─────────────────────────────────────────

export function TradeTable({
  emptyLabel,
  showExitPrice = false,
  trades
}: {
  emptyLabel: string;
  showExitPrice?: boolean;
  trades: Trade[];
}) {
  if (trades.length === 0) return <EmptyState label={emptyLabel} />;

  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Side</th>
            <th>Strategy</th>
            <th>Entry Time</th>
            {showExitPrice && <th>Exit Time</th>}
            <th>Entry ₹</th>
            {showExitPrice && <th>Exit ₹</th>}
            <th>Qty</th>
            <th>P&L</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.id}>
              <td><strong>{trade.symbol}</strong></td>
              <td><span className={`tag tag--${trade.side.toLowerCase()}`}>{trade.side}</span></td>
              <td>{humanStrategy(trade.strategy)}</td>
              <td>{formatDateTime(trade.entryTime)}</td>
              {showExitPrice && <td className="neutralText">{trade.exitTime ? formatDateTime(trade.exitTime) : "—"}</td>}
              <td>{formatMoney(trade.entryPrice)}</td>
              {showExitPrice && <td>{trade.exitPrice ? formatMoney(trade.exitPrice) : "—"}</td>}
              <td>{formatNumber(trade.quantity)}</td>
              <td className={toneClass(trade.pnl)}>
                {trade.pnl === null ? <span className="openBadge">Open</span> : formatSignedMoney(trade.pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Recent journal list ────────────────────────────────────────────

export function TradeList({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) return <EmptyState label="No journal entries yet." />;

  return (
    <div className="journalList">
      {trades.slice(0, 8).map((trade) => (
        <article className="journalItem" key={trade.id}>
          <div>
            <strong>{trade.symbol}</strong>
            <span>{trade.side} / {humanStrategy(trade.strategy)}</span>
          </div>
          <div className="journalResult">
            <strong className={toneClass(trade.pnl)}>
              {trade.pnl === null ? "Open" : formatSignedMoney(trade.pnl)}
            </strong>
            <span>{formatDateTime(trade.entryTime)}</span>
          </div>
        </article>
      ))}
    </div>
  );
}

// ── Strategy table ─────────────────────────────────────────────────

export function StrategyTable({ strategies }: { strategies: StrategySummary[] }) {
  if (strategies.length === 0) return <EmptyState label="No closed strategy trades yet." />;

  return (
    <div className="strategyStack">
      {strategies.map((s) => (
        <article className="strategyRow" key={s.strategy}>
          <div>
            <strong>{humanStrategy(s.strategy)}</strong>
            <span>{formatNumber(s.trades)} trades · {formatPercent(s.winRate)} win rate</span>
          </div>
          <div>
            <strong className={toneClass(s.netPnl)}>{formatSignedMoney(s.netPnl)}</strong>
            <span>{formatSignedMoney(s.avgPnl)} avg</span>
          </div>
        </article>
      ))}
    </div>
  );
}

// ── Bot monitor ────────────────────────────────────────────────────

export function BotMonitor({ data }: { data: DashboardData }) {
  return (
    <div className="monitorGrid">
      <div>
        <span>Status</span>
        <strong className={`statusText statusText--${data.bot.status}`}>
          {data.bot.status.toUpperCase()}
        </strong>
      </div>
      <div>
        <span>Process</span>
        <strong>{data.bot.pid ? `PID ${data.bot.pid}` : "—"}</strong>
      </div>
      <div>
        <span>Mode</span>
        <strong>{data.bot.mode.toUpperCase()}</strong>
      </div>
      <div>
        <span>Started</span>
        <strong>{data.bot.since ? formatDateTime(data.bot.since) : "—"}</strong>
      </div>
      <p>{data.bot.message}</p>
    </div>
  );
}

// ── Market overview ────────────────────────────────────────────────

export function MarketOverviewPanel({ market }: { market: MarketOverview }) {
  const total = market.advances + market.declines + market.unchanged;
  const advancePct = total > 0 ? (market.advances / total) * 100 : 0;
  const declinePct = total > 0 ? (market.declines / total) * 100 : 0;

  if (market.niftyPrice === null) {
    return (
      <EmptyState
        label={market.error ?? "Market data not available outside trading hours."}
      />
    );
  }

  return (
    <div className="marketPanel">
      <div className="niftyRow">
        <div>
          <span className="eyebrow">NIFTY 50</span>
          <strong className="niftyPrice">{formatNumber(Math.round(market.niftyPrice))}</strong>
        </div>
        {market.niftyChange !== null && (
          <div className={`niftyChange ${market.niftyChange >= 0 ? "positiveText" : "negativeText"}`}>
            <strong>
              {market.niftyChange >= 0 ? "+" : ""}{market.niftyChange.toFixed(1)}
            </strong>
            {market.niftyChangePct !== null && (
              <span>
                ({market.niftyChangePct >= 0 ? "+" : ""}{market.niftyChangePct.toFixed(2)}%)
              </span>
            )}
          </div>
        )}
      </div>

      {total > 0 && (
        <div className="breadthSection">
          <div className="breadthBar">
            <div className="breadthAdvance" style={{ width: `${advancePct}%` }} />
            <div className="breadthDecline" style={{ width: `${declinePct}%` }} />
          </div>
          <div className="breadthLabels">
            <span className="positiveText">▲ {market.advances} up</span>
            <span className="neutralText">{market.unchanged} flat</span>
            <span className="negativeText">▼ {market.declines} down</span>
          </div>
        </div>
      )}

      {(market.topGainers.length > 0 || market.topLosers.length > 0) && (
        <div className="moversGrid">
          {market.topGainers.length > 0 && (
            <div>
              <span className="eyebrow">Top Gainers</span>
              {market.topGainers.slice(0, 5).map((m) => (
                <div className="moverRow" key={m.symbol}>
                  <strong>{m.symbol}</strong>
                  <span className="positiveText">+{m.changePct.toFixed(2)}%</span>
                </div>
              ))}
            </div>
          )}
          {market.topLosers.length > 0 && (
            <div>
              <span className="eyebrow">Top Losers</span>
              {market.topLosers.slice(0, 5).map((m) => (
                <div className="moverRow" key={m.symbol}>
                  <strong>{m.symbol}</strong>
                  <span className="negativeText">{m.changePct.toFixed(2)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Log viewer ─────────────────────────────────────────────────────

export function LogViewer({ lines }: { lines: string[] }) {
  if (lines.length === 0) {
    return <EmptyState label="No log output yet. Logs appear once the bot has started." />;
  }

  return (
    <div className="logViewer">
      {lines.map((line, i) => (
        <div className={`logLine logLine--${logLevel(line)}`} key={i}>
          {line}
        </div>
      ))}
    </div>
  );
}

// ── Generic panel wrapper ──────────────────────────────────────────

export function Panel({
  children,
  description,
  icon,
  id,
  title
}: {
  children: ReactNode;
  description: string;
  icon: ReactNode;
  id?: string;
  title: string;
}) {
  return (
    <section className="panel" id={id}>
      <div className="panelHeader">
        <div className="panelTitle">
          {icon}
          <div>
            <h2>{title}</h2>
            <p>{description}</p>
          </div>
        </div>
      </div>
      {children}
    </section>
  );
}

// ── Empty state ────────────────────────────────────────────────────

export function EmptyState({ label }: { label: string }) {
  return (
    <div className="emptyState">
      <span>{label}</span>
    </div>
  );
}

// ── Status pill ────────────────────────────────────────────────────

export function StatusPill({ status }: { status: DashboardData["bot"]["status"] }) {
  return (
    <div className="statusPill" data-status={status}>
      <span />
      {status.toUpperCase()}
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────

export function humanStrategy(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
}

function toneClass(value: number | null): string {
  if (value === null || value === 0) return "neutralText";
  return value > 0 ? "positiveText" : "negativeText";
}

function formatKpiValue(label: string, value: number): string {
  const l = label.toLowerCase();
  if (l.includes("p&l") || l.includes("capital") || l.includes("value")) {
    return formatMoney(value);
  }
  return formatNumber(value);
}

function logLevel(line: string): string {
  if (line.includes("| ERROR") || line.includes("| CRITICAL")) return "error";
  if (line.includes("| WARNING")) return "warning";
  if (line.includes("| DEBUG")) return "debug";
  return "info";
}
