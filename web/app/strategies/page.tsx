import { getDashboardData } from "@/lib/api";
import { LayersIcon } from "@/components/icons";
import { PageHeader, Panel, StrategyTable } from "@/components/dashboard";

export const dynamic = "force-dynamic";

export default async function StrategiesPage() {
  const data = await getDashboardData();

  return (
    <>
      <PageHeader
        description="Closed-trade performance grouped by strategy — win rate, net P&L, and average trade."
        title="Strategies"
      />
      <Panel
        description="Stats are computed from all closed trades."
        icon={<LayersIcon />}
        title="Strategy Summary"
      >
        <StrategyTable strategies={data.strategies} />
      </Panel>
    </>
  );
}
