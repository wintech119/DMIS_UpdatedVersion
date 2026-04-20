// Main App — orchestrates items rail, selection, partial/cancel dialogs, toasts.
const { useState, useEffect, useMemo } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "comfortable",
  "mobilePreview": false,
  "startingItem": 0
}/*EDITMODE-END*/;

function makeInitialState(raw) {
  // prefill qty = suggestedQty
  return raw.items.map(it => ({
    ...it,
    warehouseCards: (it.warehouseCards || []).map(c => ({ ...c, qty: c.suggestedQty, bypassReason: null })),
    _partialAccepted: false,
    _skipped: false,
  }));
}

function App() {
  const [items, setItems] = useState(() => makeInitialState(window.ALLOCATION_DATA));
  const [selectedIdx, setSelectedIdx] = useState(() => {
    const saved = parseInt(localStorage.getItem('dmis.alloc.idx') || '0', 10);
    return Number.isNaN(saved) ? 0 : Math.min(Math.max(saved, 0), window.ALLOCATION_DATA.items.length - 1);
  });
  const [dialog, setDialog] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [tweaks, setTweaks] = useState(TWEAK_DEFAULTS);
  const [density, setDensity] = useState('comfortable');

  useEffect(() => { localStorage.setItem('dmis.alloc.idx', String(selectedIdx)); }, [selectedIdx]);

  // Tweaks host protocol
  useEffect(() => {
    const onMsg = (e) => {
      if (e.data?.type === '__activate_edit_mode') setTweaksOpen(true);
      if (e.data?.type === '__deactivate_edit_mode') setTweaksOpen(false);
    };
    window.addEventListener('message', onMsg);
    try { window.parent.postMessage({ type: '__edit_mode_available' }, '*'); } catch {}
    return () => window.removeEventListener('message', onMsg);
  }, []);

  const pushToast = (t) => {
    const id = Math.random().toString(36).slice(2);
    setToasts(ts => [...ts, { ...t, id }]);
    setTimeout(() => setToasts(ts => ts.filter(x => x.id !== id)), 2800);
  };

  const item = items[selectedIdx];

  const updateItem = (next) => {
    setItems(its => its.map((x, i) => i === selectedIdx ? next : x));
  };

  // Per-item status for rail
  const itemStatus = (it) => {
    if (it.availabilityState && (it.warehouseCards?.length ?? 0) === 0) {
      return it._skipped ? 'partial' : 'blocked';
    }
    const total = (it.warehouseCards || []).reduce((s, c) => s + (c.qty ?? 0), 0);
    if (total === 0) return 'pending';
    if (total >= it.requestedQty) return 'done';
    if (it._partialAccepted) return 'partial';
    return 'pending';
  };

  // Aggregate progress
  const doneCount = items.filter(it => {
    const s = itemStatus(it);
    return s === 'done' || s === 'partial';
  }).length;

  const onAcceptPartial = ({ shortfall, alternatesAvailable }) => {
    if (alternatesAvailable) {
      setDialog({
        kind: 'partial-override',
        shortfall,
        reason: '',
      });
    } else {
      setDialog({
        kind: 'partial-compliant',
        shortfall,
      });
    }
  };

  const confirmCompliantPartial = () => {
    updateItem({ ...item, _partialAccepted: true });
    setDialog(null);
    pushToast({ text: 'Partial fulfillment accepted.', tone: 'success', icon: 'check_circle' });
  };
  const confirmOverridePartial = (reason) => {
    updateItem({ ...item, _partialAccepted: true, _overrideReason: reason });
    setDialog(null);
    pushToast({ text: 'Partial accepted — flagged for override review.', tone: 'warning', icon: 'flag' });
  };
  const reopenPartial = () => {
    updateItem({ ...item, _partialAccepted: false, _overrideReason: null });
  };

  const skipBlockedItem = () => {
    updateItem({ ...item, _skipped: true, _partialAccepted: true });
    pushToast({ text: `${item.itemName} skipped — marked partial at package level.`, tone: 'success', icon: 'skip_next' });
    // auto-advance
    const nextIdx = items.findIndex((x, i) => i > selectedIdx && itemStatus(x) === 'pending');
    if (nextIdx >= 0) setSelectedIdx(nextIdx);
  };

  const confirmCancel = () => {
    setDialog({ kind: 'cancel' });
  };
  const doCancel = () => {
    setDialog(null);
    pushToast({ text: 'Fulfillment cancelled. Stock released.', tone: 'warning', icon: 'restart_alt' });
  };

  const canContinue = items.every(it => {
    const s = itemStatus(it);
    if (s === 'done' || s === 'partial') return true;
    return false;
  }) && !items.some(it => (it.warehouseCards || []).some(c => (c.qty ?? 0) > c.totalAvailable));

  // Computed for main metric strip
  const totalReserving = (item.warehouseCards || []).reduce((s, c) => s + (c.qty ?? 0), 0);
  const shortfall = Math.max(0, item.requestedQty - totalReserving);
  const whsUsed = (item.warehouseCards || []).filter(c => (c.qty ?? 0) > 0).length;

  const statusCell = (() => {
    const s = itemStatus(item);
    if (item.availabilityState && !item._skipped) return { label: 'Blocked', tone: 'critical', hint: 'No stock anywhere' };
    if ((item.warehouseCards || []).some(c => (c.qty ?? 0) > c.totalAvailable)) return { label: 'Over', tone: 'warning', hint: 'Qty exceeds available' };
    if (s === 'done') return { label: 'Filled', tone: 'success', hint: `${whsUsed} warehouse${whsUsed === 1 ? '' : 's'}` };
    if (s === 'partial' && item._overrideReason) return { label: 'Override', tone: 'warning', hint: `${shortfall} short · reason on file` };
    if (s === 'partial') return { label: 'Compliant partial', tone: 'info', hint: `${shortfall} short` };
    if (totalReserving === 0) return { label: 'Not started', tone: 'default', hint: '' };
    return { label: 'In progress', tone: 'default', hint: '' };
  })();

  return (
    <div className="ops-shell">
      <button className="ops-shell__back" onClick={() => pushToast({ text: 'Would navigate to request.', tone: 'default' })}>
        <MI name="arrow_back" /> Back to request
      </button>
      <h1 className="ops-shell__title">Allocate items · {window.ALLOCATION_DATA.package.code}</h1>
      <p className="ops-shell__sub">Reserve inventory against each item. The system orders warehouses by FEFO or FIFO — you can add more, adjust quantities, or accept partial fulfillment.</p>

      <div className="ops-context-strip" role="status">
        <MI name="policy" />
        <span>
          <strong>{window.ALLOCATION_DATA.package.policy}</strong> — earlier-expiring stock is drawn down first.
        </span>
        <span className="ops-context-strip__divider" />
        <MI name="domain" /><span><strong>{window.ALLOCATION_DATA.package.authority}</strong></span>
        <span className="ops-context-strip__divider" />
        <MI name="schedule" /><span>Deadline <strong>{window.ALLOCATION_DATA.package.deadline}</strong></span>
        <span className="ops-context-strip__divider" />
        <MI name="assignment" /><span>Request <strong>{window.ALLOCATION_DATA.package.requestCode}</strong></span>
      </div>

      <div className="ops-stepper" role="list" aria-label="Fulfillment steps">
        <div className="ops-stepper__step ops-stepper__step--done" role="listitem">
          <span className="ops-stepper__dot"><MI name="check" style={{fontSize: 12}} /></span>
          Review
        </div>
        <span className="ops-stepper__sep" />
        <div className="ops-stepper__step ops-stepper__step--done" role="listitem">
          <span className="ops-stepper__dot"><MI name="check" style={{fontSize: 12}} /></span>
          Package details
        </div>
        <span className="ops-stepper__sep" />
        <div className="ops-stepper__step ops-stepper__step--current" role="listitem">
          <span className="ops-stepper__dot">3</span>
          Allocate
        </div>
        <span className="ops-stepper__sep" />
        <div className="ops-stepper__step" role="listitem">
          <span className="ops-stepper__dot">4</span>
          Confirm
        </div>
      </div>

      <div className="ops-layout">
        {/* Items rail */}
        <aside className="ops-items-rail" aria-label="Items to fulfill">
          <div className="ops-eyebrow">Items to fulfil</div>
          <div className="ops-items-rail__list" role="list">
            {items.map((it, i) => {
              const st = itemStatus(it);
              const reservedTotal = (it.warehouseCards || []).reduce((s, c) => s + (c.qty ?? 0), 0);
              return (
                <button
                  key={it.itemId}
                  className={`ops-item-chip ops-item-chip--${st} ${i === selectedIdx ? 'ops-item-chip--selected ops-item-chip--current' : ''}`}
                  onClick={() => setSelectedIdx(i)}
                  role="listitem"
                >
                  <span className="ops-item-chip__state" aria-hidden="true">
                    {st === 'done' && <MI name="check" style={{ fontSize: 12 }} />}
                    {st === 'partial' && <MI name="pie_chart" style={{ fontSize: 11 }} />}
                    {st === 'blocked' && '!'}
                    {st === 'pending' && (i === selectedIdx ? '●' : '')}
                  </span>
                  <span>
                    <div className="ops-item-chip__name">{it.itemName}</div>
                    <div className="ops-item-chip__meta">
                      Req {it.requestedQty} · {reservedTotal > 0 ? `Reserving ${reservedTotal}` : (it.availabilityState ? 'No stock' : 'Not started')}
                    </div>
                  </span>
                  <span className="ops-item-chip__rule">{it.rankingPolicy}</span>
                </button>
              );
            })}
          </div>
          <div className="ops-items-rail__progress">
            {doneCount} of {items.length} items resolved
            <div className="ops-items-rail__bar"><span style={{ width: `${(doneCount / items.length) * 100}%` }} /></div>
          </div>
        </aside>

        {/* Main column */}
        <main className="ops-main">
          <section className="ops-item-header">
            <div>
              <h2 className="ops-item-header__title">{item.itemName}</h2>
              <div className="ops-item-header__code">{item.itemCode}</div>
            </div>
            <div className="ops-item-header__trail">
              <Chip tone="info" icon={item.rankingPolicy === 'FEFO' ? 'schedule' : 'history'}>
                {item.rankingPolicy}
              </Chip>
              <Button variant="ghost-icon" icon="help_outline" ariaLabel="About ranking" title="FEFO = First-Expired, First-Out. FIFO = First-In, First-Out." />
            </div>
          </section>

          <div className="ops-metric-strip">
            <Metric label="Requested" value={item.requestedQty} />
            <Metric label="Reserving" value={totalReserving} tone={totalReserving === 0 ? 'default' : (totalReserving >= item.requestedQty ? 'success' : 'info')} />
            <Metric label="Shortfall" value={shortfall} tone={shortfall === 0 ? 'default' : (item._partialAccepted ? 'info' : 'warning')} />
            <Metric label="Warehouses used" value={whsUsed} hint={whsUsed === 0 ? '—' : (whsUsed === 1 ? 'Primary only' : `Across ${whsUsed}`)} />
            <Metric label="Status" value={statusCell.label} hint={statusCell.hint} tone={statusCell.tone} />
          </div>

          {/* Stocked path vs blocker path */}
          {item.availabilityState && !item._skipped ? (
            <div className="ops-blocker">
              <div className="ops-blocker__icon"><MI name="inventory_2" /></div>
              <div>
                <h3 className="ops-blocker__title">{item.availabilityState.title}</h3>
                <p className="ops-blocker__body">{item.availabilityState.body}</p>
                <div className="ops-blocker__grid">
                  <div className="ops-blocker__cell">
                    <div className="ops-blocker__cell-label">Impact</div>
                    <div className="ops-blocker__cell-value">{item.availabilityState.impact}</div>
                  </div>
                  <div className="ops-blocker__cell">
                    <div className="ops-blocker__cell-label">Still needed</div>
                    <div className="ops-blocker__cell-value">{item.availabilityState.stillNeeded}</div>
                  </div>
                </div>
                <div className="ops-blocker__next">
                  <strong>Next step · </strong>
                  {item.availabilityState.nextStep}
                </div>
                <div className="ops-blocker__actions">
                  <Button variant="primary" icon="skip_next" onClick={skipBlockedItem}>Skip and mark partial</Button>
                  <Button variant="secondary" icon="inventory" onClick={() => pushToast({ text: 'Replenishment request drafted.', icon: 'inventory' })}>Request replenishment</Button>
                  <Button variant="link" icon="arrow_back">Back to request</Button>
                </div>
              </div>
            </div>
          ) : item._skipped ? (
            <div className="ops-blocker">
              <div className="ops-blocker__icon" style={{ background: 'var(--ops-info-bg)', color: 'var(--ops-info-fg)' }}>
                <MI name="skip_next" />
              </div>
              <div>
                <h3 className="ops-blocker__title">Item skipped — package will dispatch without it</h3>
                <p className="ops-blocker__body">No stock was available system-wide. The package is marked for partial fulfillment at this item.</p>
                <Button variant="link" icon="undo" onClick={() => updateItem({ ...item, _skipped: false, _partialAccepted: false })}>Un-skip</Button>
              </div>
            </div>
          ) : (
            <AllocationStack
              item={item}
              onItemChange={updateItem}
              partialAccepted={item._partialAccepted}
              onAcceptPartial={onAcceptPartial}
              onReopenPartial={reopenPartial}
            />
          )}
        </main>
      </div>

      {/* Step actions */}
      <div className="ops-form-actions">
        <div className="ops-form-actions__left">
          <Button variant="link" icon="arrow_back">Back to request</Button>
        </div>
        <div className="ops-form-actions__right">
          <Button variant="destructive" icon="cancel" onClick={confirmCancel}>Cancel</Button>
          <Button variant="secondary" icon="save" onClick={() => pushToast({ text: 'Draft saved.', tone: 'success', icon: 'check' })}>Save draft</Button>
          <Button
            variant="primary"
            iconRight="arrow_forward"
            disabled={!canContinue}
            onClick={() => pushToast({ text: 'Continuing to Confirm step…', tone: 'success', icon: 'check' })}
          >
            Continue
          </Button>
        </div>
      </div>

      {/* Dialogs */}
      {dialog?.kind === 'partial-compliant' && (
        <Dialog
          title={`Confirm partial fulfillment (${dialog.shortfall} short)`}
          onClose={() => setDialog(null)}
          actions={<>
            <Button variant="link" onClick={() => setDialog(null)}>Keep working</Button>
            <Button variant="primary" icon="check" onClick={confirmCompliantPartial}>Accept partial</Button>
          </>}
        >
          No other warehouses hold this item. The package will dispatch with{' '}
          <strong>{totalReserving} of {item.requestedQty}</strong>. This is a compliant partial —
          not an override — and requires no reason.
        </Dialog>
      )}

      {dialog?.kind === 'partial-override' && (
        <Dialog
          title="Accept partial despite available stock?"
          onClose={() => setDialog(null)}
          actions={<>
            <Button variant="link" onClick={() => setDialog(null)}>Keep working</Button>
            <Button
              variant="destructive"
              icon="flag"
              disabled={(dialog.reason || '').trim().length < 10}
              onClick={() => confirmOverridePartial(dialog.reason)}
            >
              Flag for override review
            </Button>
          </>}
        >
          <p style={{ margin: '0 0 12px' }}>
            {item.alternateWarehouses.length} other warehouse{item.alternateWarehouses.length === 1 ? '' : 's'} hold this item
            ({item.alternateWarehouses.map(a => `${a.warehouseName} ${a.available}`).join(', ')}).
            Accepting partial here flags this package for override review downstream.
          </p>
          <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 600, marginBottom: 4 }}>
            Reason (min 10 characters)
          </label>
          <textarea
            placeholder="E.g. remaining warehouses are outside delivery radius for the 16:00 deadline."
            value={dialog.reason}
            onChange={e => setDialog(d => ({ ...d, reason: e.target.value }))}
          />
        </Dialog>
      )}

      {dialog?.kind === 'cancel' && (
        <Dialog
          title="Cancel this fulfillment?"
          onClose={() => setDialog(null)}
          actions={<>
            <Button variant="link" onClick={() => setDialog(null)}>Keep working</Button>
            <Button variant="destructive" icon="restart_alt" onClick={doCancel}>Cancel fulfillment</Button>
          </>}
        >
          This releases any reserved stock and returns the record to the queue so another operator can start fresh. You cannot undo this.
        </Dialog>
      )}

      <Toast toasts={toasts} />

      <div className={`tweaks-panel ${tweaksOpen ? 'tweaks-panel--open' : ''}`}>
        <h4>Tweaks</h4>
        <label>
          Starting item
          <select value={selectedIdx} onChange={e => setSelectedIdx(parseInt(e.target.value, 10))}>
            {items.map((it, i) => <option key={it.itemId} value={i}>{i + 1}. {it.itemName}</option>)}
          </select>
        </label>
        <label>
          Preview variant
          <select onChange={(e) => {
            const v = e.target.value;
            if (v === 'filled') {
              // ensure first item filled
              setSelectedIdx(0);
            }
            if (v === 'blocker') {
              const idx = items.findIndex(x => x.availabilityState);
              if (idx >= 0) setSelectedIdx(idx);
            }
            if (v === 'partial-compliant') {
              const idx = items.findIndex(x => (x.warehouseCards||[]).length === 1 && x.warehouseCards[0].totalAvailable < x.requestedQty && (x.alternateWarehouses||[]).length === 0);
              if (idx >= 0) setSelectedIdx(idx);
            }
          }}>
            <option value="">Jump to…</option>
            <option value="filled">Multi-warehouse FEFO</option>
            <option value="partial-compliant">Compliant partial</option>
            <option value="blocker">No stock blocker</option>
          </select>
        </label>
        <p style={{ color: 'var(--ops-ink-subtle)', fontSize: '0.78rem', marginTop: 10, marginBottom: 0 }}>
          Toggle Tweaks off to hide this panel.
        </p>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
