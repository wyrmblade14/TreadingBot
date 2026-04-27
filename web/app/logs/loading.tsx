import { SkeletonBlock, SkeletonPanel } from "@/components/Skeleton";

export default function Loading() {
  return (
    <SkeletonPanel>
      <div
        style={{
          background: "#0d1117",
          borderRadius: 6,
          padding: 14,
          display: "grid",
          gap: 6
        }}
        aria-hidden="true"
      >
        {Array.from({ length: 12 }).map((_, i) => (
          <SkeletonBlock
            key={i}
            height="14px"
            width={`${60 + Math.round((i * 37) % 35)}%`}
            borderRadius="3px"
          />
        ))}
      </div>
    </SkeletonPanel>
  );
}
