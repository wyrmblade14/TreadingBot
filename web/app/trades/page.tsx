import { getDashboardData } from "@/lib/api";
import { PageHeader, TradesSection } from "@/components/dashboard";

export const dynamic = "force-dynamic";

export default async function TradesPage() {
  const data = await getDashboardData();

  return (
    <>
      <PageHeader
        description="Open and closed trades for today, plus the latest journal entries."
        status={data.bot.status}
        title="Trades"
      />
      <TradesSection recentTrades={data.recentTrades} todayTrades={data.todayTrades} />
    </>
  );
}
