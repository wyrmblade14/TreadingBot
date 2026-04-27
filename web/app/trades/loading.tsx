import { SkeletonPanel, SkeletonTable } from "@/components/Skeleton";

export default function Loading() {
  return (
    <section className="splitGrid">
      <SkeletonPanel>
        <SkeletonTable rows={5} />
      </SkeletonPanel>
      <SkeletonPanel>
        <SkeletonTable rows={5} />
      </SkeletonPanel>
    </section>
  );
}
