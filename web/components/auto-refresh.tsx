"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// IST = UTC+5:30. NSE market hours: 09:15–15:30 IST = 03:45–10:00 UTC
function isMarketHours(): boolean {
  const now = new Date();
  const totalUTCMin = now.getUTCHours() * 60 + now.getUTCMinutes();
  return totalUTCMin >= 225 && totalUTCMin <= 600;
}

export function AutoRefresh() {
  const router = useRouter();

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;

    function scheduleNext() {
      const interval = isMarketHours() ? 20_000 : 90_000;
      timer = setTimeout(() => {
        router.refresh();
        scheduleNext();
      }, interval);
    }

    scheduleNext();
    return () => clearTimeout(timer);
  }, [router]);

  return null;
}

export function RefreshButton() {
  const router = useRouter();
  return (
    <button
      className="refreshBtn"
      onClick={() => router.refresh()}
      title="Refresh now"
      type="button"
    >
      ↻ Refresh
    </button>
  );
}
