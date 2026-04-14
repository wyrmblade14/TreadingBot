import { getLogsData } from "@/lib/api";
import { ActivityIcon } from "@/components/icons";
import { LogViewer, PageHeader, Panel } from "@/components/dashboard";

export const dynamic = "force-dynamic";

export default async function LogsPage() {
  const lines = await getLogsData(200);

  return (
    <>
      <PageHeader
        description="Live output from the bot process — last 200 lines of the current session log."
        title="Bot Logs"
      />
      <Panel
        description="Refreshes every 60 seconds. ERROR lines are red, WARNING lines are yellow."
        icon={<ActivityIcon />}
        title="Session Log"
      >
        <LogViewer lines={lines} />
      </Panel>
    </>
  );
}
