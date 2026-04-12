import type { DashboardData, StrategySummary, Trade } from "@/lib/api";
import type { ReactNode } from "react";
import {
  ActivityIcon,
  BotIcon,
  ChartIcon,
  ClipboardIcon,
  GaugeIcon,
  LayersIcon,
  TableIcon,
  WalletIcon
} from "@/components/icons";
import { DailyPnlChart, EquityChart } from "@/components/charts";
import {
  formatDateTime,
  formatMoney,
  formatNumber,
  formatPercent,
  formatSignedMoney
} from "@/lib/format";

type DashboardProps = {
  data: DashboardData;
};

export function Dashboard({ data }: DashboardProps) {
  return (
    <main className="dashboard">
      <aside className="sidebar" aria-label="Dashboard navigation">
        <div className="brand">
          <div className="brandMark"><ActivityIcon /></div>
          <div>
            <span className="eyebrow">Paper Trading</span>
            <strong>TreadingBot</strong>
          </div>
        </div>

        <nav className="navList">
          <a href="#overview"><GaugeIcon /> Overview</a>
          <a href="#charts"><ChartIcon /> Performance</a>
          <a href="#trades"><TableIcon /> Trades</a>
          <a href="#strategies"><LayersIcon /> Strategies</a>
          <a href="#monitor"><BotIcon /> Bot Monitor</a>
        </nav>

        <div className="sideNote">
          <span>Mode</span>
          <strong>{data.bot.mode.toUpperCase()}</strong>
          <p>No live capital. Review paper results before any broker switch.</p>
        </div>
      </aside>

      <section className="content">
        <header className="topbar">
          <div>
            <span className="eyebrow">Operational Dashboard</span>
            <h1>NSE paper trading control room</h1>
            <p>Core bot health, trades, strategy performance, and P&L in one place.</p>
          </div>
          <StatusPill status={data.bot.status} />
        </header>

        <section className="kpiGrid" id="overview" aria-label="Portfolio KPIs">
          {data.kpis.map((kpi) => (
            <article className="metricCard" data-tone={kpi.tone ?? "neutral"} key={kpi.label}>
              <span>{kpi.label}</span>
              <strong>{kpi.display ?? formatKpiValue(kpi.label, kpi.value)}</strong>
              {typeof kpi.delta === "number" ? <small>{formatSignedMoney(kpi.delta)}</small> : null}
            </article>
          ))}
        </section>

        <section className="chartGrid" id="charts">
          <Panel
            description="Portfolio value after realised paper P&L."
            icon={<ChartIcon />}
            title="Equity Curve"
          >
            <EquityChart data={data.equity} />
          </Panel>

          <Panel
            description="Realised day-by-day net P&L from completed trades."
            icon={<WalletIcon />}
            title="Daily P&L"
          >
            <DailyPnlChart data={data.dailyPnl} />
          </Panel>
        </section>

        <section className="splitGrid">
          <Panel
            description="Open and closed trades recorded for the current trading day."
            icon={<TableIcon />}
            id="trades"
            title="Today Trades"
          >
            <TradeTable emptyLabel="No trades today." trades={data.todayTrades} />
          </Panel>

          <Panel
            description="Latest journal entries from the paper trade log."
            icon={<ClipboardIcon />}
            title="Recent Journal"
          >
            <TradeList trades={data.recentTrades} />
          </Panel>
        </section>

        <section className="splitGrid">
          <Panel
            description="Closed-trade performance grouped by strategy."
            icon={<LayersIcon />}
            id="strategies"
            title="Strategy Summary"
          >
            <StrategyTable strategies={data.strategies} />
          </Panel>

          <Panel
            description="Shared process status reported by the trading bot."
            icon={<BotIcon />}
            id="monitor"
            title="Bot Monitor"
          >
            <BotMonitor data={data} />
          </Panel>
        </section>

        <section className="placeholderGrid" aria-label="Workflow placeholders">
          <Placeholder title="Signals" text="Live signal scanning needs the deeper strategy API workflow." />
          <Placeholder title="Backtest" text="Backtest controls will connect after the run workflow is exposed over HTTP." />
          <Placeholder title="Fundamentals" text="Fundamental rankings need a dedicated selector endpoint before migration." />
        </section>
      </section>
    </main>
  );
}

function Panel({
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

function StatusPill({ status }: { status: DashboardData["bot"]["status"] }) {
  return (
    <div className="statusPill" data-status={status}>
      <span />
      {status.toUpperCase()}
    </div>
  );
}

function TradeTable({ emptyLabel, trades }: { emptyLabel: string; trades: Trade[] }) {
  if (trades.length === 0) {
    return <EmptyState label={emptyLabel} />;
  }

  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Side</th>
            <th>Strategy</th>
            <th>Entry</th>
            <th>Qty</th>
            <th>P&L</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.id}>
              <td><strong>{trade.symbol}</strong></td>
              <td><span className="tag">{trade.side}</span></td>
              <td>{humanStrategy(trade.strategy)}</td>
              <td>{formatDateTime(trade.entryTime)}</td>
              <td>{formatNumber(trade.quantity)}</td>
              <td className={toneClass(trade.pnl)}>{trade.pnl === null ? "Open" : formatSignedMoney(trade.pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradeList({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) {
    return <EmptyState label="No journal entries yet." />;
  }

  return (
    <div className="journalList">
      {trades.slice(0, 6).map((trade) => (
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

function StrategyTable({ strategies }: { strategies: StrategySummary[] }) {
  if (strategies.length === 0) {
    return <EmptyState label="No closed strategy trades yet." />;
  }

  return (
    <div className="strategyStack">
      {strategies.map((strategy) => (
        <article className="strategyRow" key={strategy.strategy}>
          <div>
            <strong>{humanStrategy(strategy.strategy)}</strong>
            <span>{formatNumber(strategy.trades)} trades / {formatPercent(strategy.winRate)} win rate</span>
          </div>
          <div>
            <strong className={toneClass(strategy.netPnl)}>{formatSignedMoney(strategy.netPnl)}</strong>
            <span>{formatSignedMoney(strategy.avgPnl)} avg</span>
          </div>
        </article>
      ))}
    </div>
  );
}

function BotMonitor({ data }: { data: DashboardData }) {
  return (
    <div className="monitorGrid">
      <div>
        <span>Status</span>
        <strong>{data.bot.status.toUpperCase()}</strong>
      </div>
      <div>
        <span>Process</span>
        <strong>{data.bot.pid ? `PID ${data.bot.pid}` : "Not attached"}</strong>
      </div>
      <div>
        <span>Started</span>
        <strong>{formatDateTime(data.bot.since)}</strong>
      </div>
      <div>
        <span>Data Source</span>
        <strong>{data.source === "api" ? "HTTP API" : "Empty State"}</strong>
      </div>
      <p>{data.bot.message}</p>
    </div>
  );
}

function Placeholder({ text, title }: { text: string; title: string }) {
  return (
    <article className="placeholder">
      <span>{title}</span>
      <p>{text}</p>
    </article>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="emptyState">
      <span>{label}</span>
    </div>
  );
}

function humanStrategy(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function toneClass(value: number | null): string {
  if (value === null || value === 0) {
    return "neutralText";
  }

  return value > 0 ? "positiveText" : "negativeText";
}

function formatKpiValue(label: string, value: number): string {
  if (label.toLowerCase().includes("p&l") || label.toLowerCase().includes("capital") || label.toLowerCase().includes("value")) {
    return formatMoney(value);
  }

  return formatNumber(value);
}
