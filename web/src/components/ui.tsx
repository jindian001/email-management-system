import { useEffect, type ReactNode } from "react";

export function Tag({ tone = "", children }: { tone?: string; children: ReactNode }) {
  return <span className={`tag ${tone}`.trim()}>{children}</span>;
}

export function Badge({ tone = "", children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge ${tone}`.trim()}>{children}</span>;
}

export interface Column<T> {
  key: string;
  title: string;
  render: (row: T) => ReactNode;
  width?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  empty?: ReactNode;
  loading?: boolean;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty = "暂无数据",
  loading = false,
}: DataTableProps<T>) {
  if (loading) return <div className="card empty">加载中…</div>;
  return (
    <table>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column.key} style={column.width ? { width: column.width } : undefined}>
              {column.title}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={columns.length} className="empty">
              {empty}
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr
              key={rowKey(row)}
              className={onRowClick ? "clickable" : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((column) => (
                <td key={column.key}>{column.render(row)}</td>
              ))}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

interface ModalProps {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}

export function Modal({ title, onClose, children, footer }: ModalProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="overlay"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="modal-close" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {children}
          {footer ? <div className="row" style={{ marginTop: 16 }}>{footer}</div> : null}
        </div>
      </div>
    </div>
  );
}

export function Bars({
  data,
  total,
  empty = "暂无数据",
}: {
  data: Record<string, number>;
  total?: number;
  empty?: string;
}) {
  const entries = Object.entries(data || {}).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return <div className="muted">{empty}</div>;
  const max = Math.max(total ?? 0, ...entries.map(([, value]) => value), 1);
  return (
    <div className="barlist">
      {entries.map(([key, value]) => (
        <div className="item" key={key}>
          <span>{key}</span>
          <div className="bar">
            <span style={{ width: `${Math.round((value / max) * 100)}%` }} />
          </div>
          <span className="muted">{value}</span>
        </div>
      ))}
    </div>
  );
}

export function ScoreBar({ value }: { value: number }) {
  const width = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className="bar" style={{ margin: "10px 0" }}>
      <span style={{ width: `${width}%` }} />
    </div>
  );
}

export function Pagination({
  page,
  total,
  hasPrev,
  hasNext,
  onPrev,
  onNext,
}: {
  page: number;
  total: number;
  hasPrev: boolean;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="row" style={{ marginTop: 12 }}>
      <button className="act fixed" onClick={onPrev} disabled={!hasPrev}>
        ← 上一页
      </button>
      <button className="act fixed" onClick={onNext} disabled={!hasNext}>
        下一页 →
      </button>
      <span className="muted">
        第 {page} 页 · 共 {total} 封
      </span>
    </div>
  );
}

export function Field({
  label,
  children,
  width,
}: {
  label: string;
  children: ReactNode;
  width?: number | string;
}) {
  return (
    <label className="field" style={{ width, flex: width ? "0 0 auto" : 1, minWidth: 140 }}>
      <span>{label}</span>
      {children}
    </label>
  );
}

export function ErrorCard({ message }: { message: string }) {
  return (
    <div className="card">
      <div className="err">
        加载失败：{message}
        {message.startsWith("401") ? "（请在右上角填入 X-API-Key）" : ""}
      </div>
    </div>
  );
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

export function pct(value: number): string {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

export function reasonText(reason: Record<string, unknown>): string {
  return String(reason.desc || reason.kind || reason.type || "命中");
}
