import { getDashboardData } from "@/lib/api";
import { ChartGrid, KpiGrid, PageHeader } from "@/components/dashboard";

export const dynamic = "force-dynamic";

export default async function Page() {
  const data = await getDashboardData();

  return (
    <>
      <PageHeader
        description="Live KPIs, equity curve, and daily P&L for your paper trading portfolio."
        status={data.bot.status}
        title="Overview"
      />
      <KpiGrid kpis={data.kpis} />
      <ChartGrid dailyPnl={data.dailyPnl} equity={data.equity} />
    </>
  );
}
