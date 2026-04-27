import { SkeletonBlock, SkeletonPanel } from "@/components/Skeleton";

export default function Loading() {
  return (
    <div className="singlePanel">
      <SkeletonPanel>
        <div className="monitorGrid" aria-hidden="true">
          <SkeletonBlock height="72px" />
          <SkeletonBlock height="72px" />
          <SkeletonBlock height="72px" />
          <SkeletonBlock height="72px" />
        </div>
      </SkeletonPanel>
    </div>
  );
}
