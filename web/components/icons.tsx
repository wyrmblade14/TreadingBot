import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function IconBase({ children, ...props }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className="icon"
      fill="none"
      focusable="false"
      height="20"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      width="20"
      {...props}
    >
      {children}
    </svg>
  );
}

export function ActivityIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M3 12h4l2.5-7 5 14 2.5-7h4" />
    </IconBase>
  );
}

export function BotIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect height="12" rx="3" width="16" x="4" y="8" />
      <path d="M12 4v4" />
      <path d="M8.5 13h.01" />
      <path d="M15.5 13h.01" />
      <path d="M9 17h6" />
    </IconBase>
  );
}

export function ChartIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 19V5" />
      <path d="M4 19h16" />
      <path d="m7 15 3-4 3 2 4-7" />
    </IconBase>
  );
}

export function ClipboardIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M9 4h6" />
      <path d="M9 4a3 3 0 0 0 6 0" />
      <rect height="17" rx="3" width="14" x="5" y="4" />
      <path d="M8 11h8" />
      <path d="M8 15h5" />
    </IconBase>
  );
}

export function GaugeIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 14a8 8 0 0 1 16 0" />
      <path d="M12 14l4-4" />
      <path d="M8 18h8" />
    </IconBase>
  );
}

export function LayersIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m12 3 9 5-9 5-9-5 9-5Z" />
      <path d="m3 12 9 5 9-5" />
      <path d="m3 16 9 5 9-5" />
    </IconBase>
  );
}

export function TableIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect height="14" rx="2" width="18" x="3" y="5" />
      <path d="M3 10h18" />
      <path d="M9 5v14" />
    </IconBase>
  );
}

export function WalletIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 7h15a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7.8A2.8 2.8 0 0 1 5.8 5H18" />
      <path d="M16 13h.01" />
    </IconBase>
  );
}
