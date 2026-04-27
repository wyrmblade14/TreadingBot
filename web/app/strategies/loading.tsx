import { SkeletonPanel, SkeletonRows } from "@/components/Skeleton";

export default function Loading() {
  return (
    <div className="singlePanel">
      <SkeletonPanel>
        <SkeletonRows rows={4} />
      </SkeletonPanel>
    </div>
  );
}
