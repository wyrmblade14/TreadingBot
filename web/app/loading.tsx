import { SkeletonChartGrid, SkeletonKpiGrid } from "@/components/Skeleton";

export default function Loading() {
  return (
    <>
      <div className="pageHeader" aria-hidden="true">
        <div style={{ display: "grid", gap: 8 }}>
          <div className="skeletonBlock" style={{ height: 32, width: 140, borderRadius: 6 }} />
          <div className="skeletonBlock" style={{ height: 14, width: 320, borderRadius: 6 }} />
        </div>
      </div>
      <SkeletonKpiGrid />
      <SkeletonChartGrid />
    </>
  );
}
