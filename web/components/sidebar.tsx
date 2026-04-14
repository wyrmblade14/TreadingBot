"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ActivityIcon,
  BotIcon,
  ChartIcon,
  ClipboardIcon,
  GaugeIcon,
  LayersIcon,
  TableIcon,
  WalletIcon
} from "@/components/icons";

const NAV = [
  { href: "/",            label: "Overview",    icon: <GaugeIcon /> },
  { href: "/trades",      label: "Trades",      icon: <TableIcon /> },
  { href: "/history",     label: "History",     icon: <ClipboardIcon /> },
  { href: "/strategies",  label: "Strategies",  icon: <LayersIcon /> },
  { href: "/market",      label: "Market",      icon: <WalletIcon /> },
  { href: "/monitor",     label: "Bot Monitor", icon: <BotIcon /> },
  { href: "/logs",        label: "Logs",        icon: <ActivityIcon /> },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sidebar" aria-label="Navigation">
      <div className="brand">
        <div className="brandMark"><ActivityIcon /></div>
        <div>
          <span className="eyebrow">Paper Trading</span>
          <strong>TreadingBot</strong>
        </div>
      </div>

      <nav className="navList">
        {NAV.map(({ href, label, icon }) => (
          <Link
            key={href}
            href={href}
            className={pathname === href ? "navActive" : undefined}
          >
            {icon}
            {label}
          </Link>
        ))}
      </nav>

      <div className="sideNote">
        <span>Mode</span>
        <strong>PAPER</strong>
        <p>No live capital. Review paper results before switching to a live broker.</p>
      </div>
    </aside>
  );
}
