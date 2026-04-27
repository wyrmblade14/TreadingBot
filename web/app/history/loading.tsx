import { SkeletonPanel, SkeletonTable } from "@/components/Skeleton";

export default function Loading() {
  return (
    <div className="singlePanel" style={{ maxWidth: "none" }}>
      <SkeletonPanel>
        <SkeletonTable rows={8} />
      </SkeletonPanel>
    </div>
  );
}
