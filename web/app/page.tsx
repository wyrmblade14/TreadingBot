import { getDashboardData } from "@/lib/api";
import { ChartGrid, KpiGrid, OpenPositionsPanel, PageHeader } from "@/components/dashboard";

export const dynamic = "force-dynamic";

export default async function Page() {
  const data = await getDashboardData();

  return (
    <>
      <PageHeader
        apiSource={data.source}
        description="Live KPIs, equity curve, and daily P&L for your paper trading portfolio."
        generatedAt={data.generatedAt}
        status={data.bot.status}
        title="Overview"
      />
      <KpiGrid kpis={data.kpis} />
      <OpenPositionsPanel trades={data.todayTrades} />
      <ChartGrid dailyPnl={data.dailyPnl} equity={data.equity} />
    </>
  );
}
