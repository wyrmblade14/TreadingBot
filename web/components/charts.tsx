import type { DailyPnlPoint, EquityPoint } from "@/lib/api";
import { formatDate, formatMoney, formatSignedMoney } from "@/lib/format";

type LineChartProps = {
  data: EquityPoint[];
};

type BarChartProps = {
  data: DailyPnlPoint[];
};

export function EquityChart({ data }: LineChartProps) {
  if (data.length < 2) {
    return <ChartEmptyState label="Equity curve appears after two trading days." />;
  }

  const points = toLinePoints(data.map((point) => point.value), 680, 220);
  const path = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
  const area = `${path} L 680 220 L 0 220 Z`;
  const first = data[0];
  const last = data[data.length - 1];

  return (
    <div className="chartBlock">
      <svg className="chartSvg" role="img" viewBox="0 0 680 240">
        <title>Equity curve</title>
        <path className="chartGridLine" d="M0 55H680 M0 110H680 M0 165H680 M0 220H680" />
        <path className="chartArea" d={area} />
        <path className="chartLine" d={path} />
      </svg>
      <div className="chartMeta">
        <span>{formatDate(first.date)}: {formatMoney(first.value)}</span>
        <span>{formatDate(last.date)}: {formatMoney(last.value)}</span>
      </div>
    </div>
  );
}

export function DailyPnlChart({ data }: BarChartProps) {
  if (data.length === 0) {
    return <ChartEmptyState label="Daily P&L appears after the first closed trade." />;
  }

  const width = 680;
  const height = 220;
  const maxAbs = Math.max(...data.map((point) => Math.abs(point.pnl)), 1);
  const barWidth = width / data.length;
  const zeroY = height / 2;

  return (
    <div className="chartBlock">
      <svg className="chartSvg" role="img" viewBox={`0 0 ${width} 240`}>
        <title>Daily profit and loss</title>
        <path className="chartGridLine" d={`M0 ${zeroY}H${width} M0 55H${width} M0 165H${width}`} />
        {data.map((point, index) => {
          const normalized = Math.abs(point.pnl) / maxAbs;
          const barHeight = Math.max(normalized * (height / 2 - 12), 2);
          const x = index * barWidth + 3;
          const y = point.pnl >= 0 ? zeroY - barHeight : zeroY;

          return (
            <rect
              className={point.pnl >= 0 ? "barPositive" : "barNegative"}
              height={barHeight}
              key={point.date}
              rx="3"
              width={Math.max(barWidth - 6, 3)}
              x={x}
              y={y}
            >
              <title>{formatDate(point.date)}: {formatSignedMoney(point.pnl)}</title>
            </rect>
          );
        })}
      </svg>
      <div className="chartMeta">
        <span>{data.length} trading days</span>
        <span>{formatSignedMoney(data.reduce((sum, point) => sum + point.pnl, 0))}</span>
      </div>
    </div>
  );
}

function ChartEmptyState({ label }: { label: string }) {
  return (
    <div className="chartEmpty">
      <span>{label}</span>
    </div>
  );
}

function toLinePoints(values: number[], width: number, height: number) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  return values.map((value, index) => ({
    x: values.length === 1 ? 0 : (index / (values.length - 1)) * width,
    y: height - ((value - min) / span) * (height - 24) - 12
  }));
}
