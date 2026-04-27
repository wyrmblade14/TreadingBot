import { SkeletonBlock, SkeletonPanel } from "@/components/Skeleton";

export default function Loading() {
  return (
    <div className="singlePanel">
      <SkeletonPanel>
        <SkeletonBlock height="200px" />
      </SkeletonPanel>
    </div>
  );
}
