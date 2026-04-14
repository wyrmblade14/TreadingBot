import { getMarketData } from "@/lib/api";
import { WalletIcon } from "@/components/icons";
import { MarketOverviewPanel, PageHeader, Panel } from "@/components/dashboard";

export const dynamic = "force-dynamic";

export default async function MarketPage() {
  const market = await getMarketData();

  return (
    <>
      <PageHeader
        description="NIFTY 50 index snapshot — price, breadth, and today's top movers."
        title="Market Overview"
      />
      <div className="singlePanel">
        <Panel
          description="Data sourced from yfinance. Updates every 5 minutes during market hours."
          icon={<WalletIcon />}
          title="NIFTY 50"
        >
          <MarketOverviewPanel market={market} />
        </Panel>
      </div>
    </>
  );
}
