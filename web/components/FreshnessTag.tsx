"use client";

import { useEffect, useState } from "react";

function getRelativeLabel(generatedAt: string): string {
  const diff = Math.floor((Date.now() - new Date(generatedAt).getTime()) / 1000);
  if (diff < 5) return "Just updated";
  if (diff < 60) return `Updated ${diff}s ago`;
  const m = Math.floor(diff / 60);
  if (m < 60) return `Updated ${m}m ago`;
  return `Updated ${Math.floor(m / 60)}h ago`;
}

function getTone(generatedAt: string): string {
  const diff = Math.floor((Date.now() - new Date(generatedAt).getTime()) / 1000);
  if (diff > 180) return "freshTag--stale";
  if (diff > 90) return "freshTag--warn";
  return "";
}

export function FreshnessTag({ generatedAt }: { generatedAt: string }) {
  const [label, setLabel] = useState(getRelativeLabel(generatedAt));
  const [tone, setTone] = useState(getTone(generatedAt));

  useEffect(() => {
    const timer = setInterval(() => {
      setLabel(getRelativeLabel(generatedAt));
      setTone(getTone(generatedAt));
    }, 5000);
    return () => clearInterval(timer);
  }, [generatedAt]);

  return (
    <span className={`freshTag ${tone}`} title={new Date(generatedAt).toLocaleTimeString("en-IN")}>
      {label}
    </span>
  );
}
