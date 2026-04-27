export function SkeletonBlock({
  height,
  width = "100%",
  borderRadius = "6px"
}: {
  height: string;
  width?: string;
  borderRadius?: string;
}) {
  return (
    <div
      className="skeletonBlock"
      style={{ height, width, borderRadius }}
      aria-hidden="true"
    />
  );
}

export function SkeletonKpiGrid() {
  return (
    <section className="kpiGrid" aria-hidden="true">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="metricCard" style={{ gap: 10 }}>
          <SkeletonBlock height="13px" width="60%" />
          <SkeletonBlock height="30px" width="80%" />
        </div>
      ))}
    </section>
  );
}

export function SkeletonChartGrid() {
  return (
    <section className="chartGrid" aria-hidden="true">
      <SkeletonPanel>
        <SkeletonBlock height="260px" />
      </SkeletonPanel>
      <SkeletonPanel>
        <SkeletonBlock height="260px" />
      </SkeletonPanel>
    </section>
  );
}

export function SkeletonTable({ rows = 6 }: { rows?: number }) {
  return (
    <div aria-hidden="true" style={{ display: "grid", gap: 8 }}>
      <SkeletonBlock height="16px" width="40%" />
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonBlock key={i} height="44px" />
      ))}
    </div>
  );
}

export function SkeletonPanel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="panel"
      aria-hidden="true"
      style={{ display: "grid", gap: 14 }}
    >
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <SkeletonBlock height="38px" width="38px" borderRadius="8px" />
        <div style={{ display: "grid", gap: 6, flex: 1 }}>
          <SkeletonBlock height="14px" width="35%" />
          <SkeletonBlock height="12px" width="55%" />
        </div>
      </div>
      {children}
    </div>
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div aria-hidden="true" style={{ display: "grid", gap: 10 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            border: "1px solid var(--line)",
            borderRadius: 8,
            padding: 13,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 14
          }}
        >
          <div style={{ display: "grid", gap: 6, flex: 1 }}>
            <SkeletonBlock height="14px" width="40%" />
            <SkeletonBlock height="12px" width="60%" />
          </div>
          <div style={{ display: "grid", gap: 6, textAlign: "right" }}>
            <SkeletonBlock height="14px" width="80px" />
            <SkeletonBlock height="12px" width="60px" />
          </div>
        </div>
      ))}
    </div>
  );
}
