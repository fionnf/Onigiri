import type { ReactNode } from "react";
import { IconAlert, IconStar } from "./Icons";

export function Spinner({ label }: { label?: string }) {
  return (
    <output className="flex items-center gap-2 text-sm text-muted">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-ink" />
      {label}
    </output>
  );
}

export function Empty({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="card flex flex-col items-center gap-2 px-6 py-12 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {hint && <p className="max-w-md text-sm text-muted">{hint}</p>}
      {action}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="card flex items-start gap-2 border-danger/40 px-3 py-2 text-sm">
      <IconAlert className="mt-0.5 h-4 w-4 text-danger" />
      <div className="flex-1">
        <p className="text-ink">{message}</p>
        {onRetry && (
          <button type="button" className="btn btn-sm mt-2" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function Stars({
  value,
  onChange,
  size = "h-4 w-4",
}: {
  value: number | null;
  onChange?: (next: number) => void;
  size?: string;
}) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => {
        const filled = (value ?? 0) >= n;
        if (!onChange) {
          return <IconStar key={n} filled={filled} className={`${size} text-muted`} />;
        }
        return (
          <button
            key={n}
            type="button"
            aria-label={`${n} star${n > 1 ? "s" : ""}`}
            onClick={() => onChange(n)}
            className="text-muted transition hover:text-ink"
          >
            <IconStar filled={filled} className={size} />
          </button>
        );
      })}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  if (status === "needs_review") {
    return (
      <span className="chip border-warn/40 text-warn">
        <IconAlert className="h-3 w-3" />
        Needs review
      </span>
    );
  }
  if (status === "draft") return <span className="chip">Draft</span>;
  return null;
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    // The control arrives as children, so the association cannot be checked statically.
    // biome-ignore lint/a11y/noLabelWithoutControl: wrapping label, control passed in
    <label className="block space-y-1">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="block text-xs text-faint">{hint}</span>}
    </label>
  );
}

export function Confirm({
  message,
  onConfirm,
  children,
}: {
  message: string;
  onConfirm: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className="btn btn-sm text-danger"
      onClick={() => {
        if (window.confirm(message)) onConfirm();
      }}
    >
      {children}
    </button>
  );
}
