import { getDashboardData } from "@/lib/api";
import { ClipboardIcon } from "@/components/icons";
import { PageHeader, Panel, TradeTable } from "@/components/dashboard";

export const dynamic = "force-dynamic";

export default async function HistoryPage() {
  const data = await getDashboardData();

  return (
    <>
      <PageHeader
        description="Complete paper trade history — every entry and exit recorded to date."
        title="Trade History"
      />
      <Panel
        description={`${data.recentTrades.length} trades on record.`}
        icon={<ClipboardIcon />}
        title="All Trades"
      >
        <TradeTable
          emptyLabel="No trades recorded yet."
          showExitPrice
          trades={data.recentTrades}
        />
      </Panel>
    </>
  );
}
