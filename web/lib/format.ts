const numberFormatter = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 0
});

const decimalFormatter = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2
});

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "INR 0";
  }

  const sign = value < 0 ? "-" : "";
  return `${sign}INR ${numberFormatter.format(Math.abs(value))}`;
}

export function formatSignedMoney(value: number | null | undefined): string {
  const safeValue = value ?? 0;
  const prefix = safeValue > 0 ? "+" : safeValue < 0 ? "-" : "";
  return `${prefix}INR ${numberFormatter.format(Math.abs(safeValue))}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "0%";
  }

  return `${decimalFormatter.format(value)}%`;
}

export function formatNumber(value: number | null | undefined): string {
  return numberFormatter.format(value ?? 0);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "Not available";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "No date";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short"
  });
}
