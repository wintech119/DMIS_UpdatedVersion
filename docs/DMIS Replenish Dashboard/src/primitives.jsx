// Small reusable bits — chips, metric strip, icons.
const { useState, useEffect, useMemo, useRef, useCallback } = React;

// Material icon ligature helper
function MI({ name, style }) {
  return <span className="material-icons-outlined" aria-hidden="true" style={style}>{name}</span>;
}

function Chip({ tone = 'neutral', icon, children }) {
  return (
    <span className={`ops-chip ops-chip--${tone}`}>
      {icon && <MI name={icon} />}
      {children}
    </span>
  );
}

function Metric({ label, value, hint, tone = 'default' }) {
  const cls = tone === 'default' ? '' : `ops-metric--${tone}`;
  return (
    <div className={`ops-metric ${cls}`}>
      <div className="ops-metric__label">{label}</div>
      <div className="ops-metric__value">{value}</div>
      {hint && <div className="ops-metric__hint">{hint}</div>}
    </div>
  );
}

function Button({ variant = 'primary', size, icon, iconRight, children, onClick, disabled, title, ariaLabel }) {
  const cls = `btn btn--${variant}${size === 'small' ? ' btn--small' : ''}`;
  return (
    <button className={cls} onClick={onClick} disabled={disabled} title={title} aria-label={ariaLabel}>
      {icon && <MI name={icon} />}
      {children}
      {iconRight && <MI name={iconRight} />}
    </button>
  );
}

function Toast({ toasts }) {
  return (
    <div className="ops-toast-layer" role="status" aria-live="polite">
      {toasts.map(t => (
        <div key={t.id} className={`ops-toast ops-toast--${t.tone || 'default'}`}>
          {t.icon && <MI name={t.icon} />}
          {t.text}
        </div>
      ))}
    </div>
  );
}

function Dialog({ title, children, actions, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="ops-dialog-backdrop" onClick={onClose}>
      <div className="ops-dialog" role="dialog" aria-modal="true" aria-label={title} onClick={e => e.stopPropagation()}>
        <h3 className="ops-dialog__title">{title}</h3>
        <div className="ops-dialog__body">{children}</div>
        <div className="ops-dialog__actions">{actions}</div>
      </div>
    </div>
  );
}

// Rank badge copy helper
function rankLabel(card) {
  const rule = card.rankingPolicy || card._rankingPolicy || 'FEFO';
  if (card.issuanceOrder === 1) return `Primary · ${rule}`;
  return `+${card.issuanceOrder - 1} · ${rule}`;
}

// Rank reason copy mapper
function rankReasonCopy(card, requestedQty, remainingBeforeThisCard) {
  if (!card.rankReason) return null;
  const pct = card.rankReasonPct ?? Math.min(100, Math.round((card.totalAvailable / Math.max(requestedQty, 1)) * 100));
  switch (card.rankReason) {
    case 'EARLIEST_EXPIRY':
      return `Ranked first — earliest-expiring batch (${card.rankReasonDate}), covers ${pct}% of need.`;
    case 'EARLIEST_RECEIPT':
      return `Ranked first — oldest receipt (${card.rankReasonDate}), FIFO priority.`;
    case 'COVERS_REMAINDER':
      return `Ranks next — holds ${card.totalAvailable} which covers the remaining shortfall.`;
    case 'PROXIMITY':
      return `Ranked ${card.issuanceOrder} — nearest warehouse with matching stock.`;
    case 'LAST_RESORT':
      return `Remaining available stock for this item.`;
    default:
      return null;
  }
}

Object.assign(window, { MI, Chip, Metric, Button, Toast, Dialog, rankLabel, rankReasonCopy });
