import { getDashboardData } from "@/lib/api";
import { BotIcon } from "@/components/icons";
import { BotMonitor, PageHeader, Panel } from "@/components/dashboard";

export const dynamic = "force-dynamic";

export default async function MonitorPage() {
  const data = await getDashboardData();

  return (
    <>
      <PageHeader
        description="Process health, scheduler state, and runtime status for the trading bot."
        status={data.bot.status}
        title="Bot Monitor"
      />
      <div className="singlePanel">
        <Panel
          description="Status reported from the shared bot_state.json file."
          icon={<BotIcon />}
          title="Runtime Status"
        >
          <BotMonitor data={data} />
        </Panel>
      </div>
    </>
  );
}
