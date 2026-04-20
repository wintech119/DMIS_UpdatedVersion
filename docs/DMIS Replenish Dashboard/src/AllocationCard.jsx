// AllocationCard — one warehouse card in the stack.
const { useState: useStateCard } = React;

function AllocationCard({
  card,
  requestedQty,
  rankingPolicy,
  totalReservingFromOthers,
  canRemove,
  onQtyChange,
  onBatchQtyChange,
  onRemove,
  onBypassReasonChange,
  showBypassReason,
  isEntering,
}) {
  const [batchOpen, setBatchOpen] = useStateCard(false);
  const [menuOpen, setMenuOpen] = useStateCard(false);

  const qty = card.qty ?? 0;
  const over = qty > card.totalAvailable;
  const neededAcrossAll = requestedQty;
  const myContributionAgainstNeed = Math.max(0, neededAcrossAll - totalReservingFromOthers);

  // Card-local status pill
  let pillTone = 'neutral-outline';
  let pillIcon = 'radio_button_unchecked';
  let pillText = 'Not yet allocated';
  if (over) {
    pillTone = 'warning';
    pillIcon = 'warning_amber';
    pillText = 'Exceeds available';
  } else if (qty === 0) {
    // draft
  } else if (qty + totalReservingFromOthers >= requestedQty) {
    pillTone = 'success';
    pillIcon = 'check_circle';
    pillText = 'Filled from this warehouse';
  } else if (qty === card.totalAvailable) {
    pillTone = 'info';
    pillIcon = 'trending_up';
    pillText = 'Fully drawn — at capacity';
  } else {
    pillTone = 'info-outline';
    pillIcon = 'pie_chart';
    pillText = 'Partial from this warehouse';
  }

  const cardPolicy = card.rankingPolicy || rankingPolicy;
  const cardForLabel = { ...card, rankingPolicy: cardPolicy };
  const reason = rankReasonCopy(card, requestedQty);

  const bumpQty = (delta) => {
    const next = Math.max(0, Math.min(card.totalAvailable, qty + delta));
    onQtyChange(next);
  };
  const useMax = () => {
    const maxSensible = Math.min(card.totalAvailable, qty + myContributionAgainstNeed);
    onQtyChange(maxSensible);
  };
  const clear = () => onQtyChange(0);

  return (
    <article
      className={`ops-alloc-card ${card.issuanceOrder === 1 ? 'ops-alloc-card--primary' : ''} ${isEntering ? 'ops-alloc-card--enter' : ''}`}
      role="group"
      aria-label={`Warehouse allocation: ${card.warehouseName}, rank ${card.issuanceOrder}`}
    >
      <div className="ops-alloc-card__header">
        <div className="ops-alloc-card__identity">
          <div className="ops-alloc-card__icon"><MI name="warehouse" /></div>
          <div style={{ minWidth: 0 }}>
            <h3 className="ops-alloc-card__name">{card.warehouseName}</h3>
            <div className="ops-alloc-card__sub">
              <Chip tone={card.issuanceOrder === 1 ? 'info' : 'neutral-outline'}>
                {rankLabel(cardForLabel)}
              </Chip>
              <span><strong>{card.totalAvailable}</strong> available</span>
              {card.batches?.[0]?.expiryDate && (
                <>
                  <span className="dot" />
                  <span>Earliest expiry {card.batches[0].expiryDate}</span>
                </>
              )}
              {cardPolicy === 'FIFO' && card.batches?.[0]?.receiptDate && (
                <>
                  <span className="dot" />
                  <span>Received {card.batches[0].receiptDate}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="ops-alloc-card__trail">
          <Chip tone={pillTone} icon={pillIcon}>{pillText}</Chip>
          <div style={{ position: 'relative' }}>
            <Button variant="ghost-icon" icon="more_vert" ariaLabel="Warehouse actions" onClick={() => setMenuOpen(o => !o)} />
            {menuOpen && (
              <div className="ops-alloc-menu" style={{ left: 'auto', right: 0, width: 240, bottom: 'auto', top: 'calc(100% + 6px)' }}
                   onMouseLeave={() => setMenuOpen(false)}>
                <button className="ops-alloc-menu__item" style={{ gridTemplateColumns: '1fr' }} onClick={() => { useMax(); setMenuOpen(false); }}>
                  <span>Use max available here</span>
                </button>
                <button className="ops-alloc-menu__item" style={{ gridTemplateColumns: '1fr' }} onClick={() => { clear(); setMenuOpen(false); }}>
                  <span>Clear allocation</span>
                </button>
                <button
                  className="ops-alloc-menu__item"
                  style={{ gridTemplateColumns: '1fr', color: canRemove ? 'var(--ops-critical-fg)' : 'var(--ops-ink-subtle)' }}
                  onClick={() => { if (canRemove) { onRemove(); setMenuOpen(false); } }}
                  disabled={!canRemove}
                  title={canRemove ? '' : 'At least one warehouse must remain'}
                >
                  <span>Remove warehouse</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {reason && (
        <div className="ops-alloc-card__reason">
          <MI name="info" />
          <span>{reason}</span>
        </div>
      )}

      {showBypassReason && (
        <div className="ops-bypass">
          <div className="ops-bypass__title">
            <MI name="warning_amber" />
            FEFO bypass — reason required
          </div>
          <div className="ops-bypass__body">
            You have skipped the earliest-expiry warehouse while later-ranked stock still has quantity.
            Record why so reviewers and dispatch understand the decision.
          </div>
          <textarea
            placeholder="E.g. Port Antonio inaccessible due to road closure; using Sav-la-Mar instead."
            value={card.bypassReason || ''}
            onChange={e => onBypassReasonChange(e.target.value)}
            aria-label="Reason for skipping the earliest-expiry warehouse"
          />
        </div>
      )}

      <div className="ops-alloc-card__body">
        <div className="ops-alloc-qty">
          <div className="ops-alloc-qty__label">Allocating from this warehouse</div>
          <div className="ops-alloc-qty__input-wrap" role="group" aria-label="Quantity">
            <button className="ops-alloc-qty__step" onClick={() => bumpQty(-1)} disabled={qty <= 0} aria-label="Decrement">−</button>
            <input
              type="number"
              className="ops-alloc-qty__input"
              value={qty}
              min={0}
              max={card.totalAvailable}
              onChange={e => onQtyChange(Math.max(0, parseInt(e.target.value || '0', 10)))}
              aria-describedby={`qty-ctx-${card.warehouseId}`}
              inputMode="numeric"
            />
            <button className="ops-alloc-qty__step" onClick={() => bumpQty(1)} disabled={qty >= card.totalAvailable} aria-label="Increment">+</button>
          </div>
          <div className="ops-alloc-qty__ctx" id={`qty-ctx-${card.warehouseId}`}>
            of <strong>{card.totalAvailable}</strong> available
          </div>
          <Button variant="secondary" size="small" onClick={useMax}>Use max</Button>
          <Button variant="link" size="small" onClick={clear}>Clear</Button>
        </div>

        {over && (
          <div className="ops-alloc-card__validation">
            <MI name="warning_amber" />
            Cannot exceed {card.totalAvailable} available at {card.warehouseName}.
          </div>
        )}

        {card.batches && card.batches.length > 0 && (
          <div className="ops-alloc-card__batch">
            <button
              className={`ops-alloc-card__batch-toggle ${batchOpen ? 'ops-alloc-card__batch-toggle--open' : ''}`}
              onClick={() => setBatchOpen(o => !o)}
              aria-expanded={batchOpen}
            >
              <MI name="chevron_right" />
              {batchOpen ? 'Hide' : 'Show'} batch detail ({card.batches.length} {card.batches.length === 1 ? 'batch' : 'batches'})
            </button>
            {batchOpen && (
              <table className="ops-batch-table">
                <thead>
                  <tr>
                    <th>Lot no.</th>
                    <th>Received</th>
                    <th>Expires</th>
                    <th style={{ textAlign: 'right' }}>Available</th>
                    <th style={{ textAlign: 'right' }}>Reserve</th>
                  </tr>
                </thead>
                <tbody>
                  {card.batches.map((b, i) => (
                    <tr key={b.batchId}>
                      <td className={i === 0 && cardPolicy === 'FEFO' ? 'fefo-top' : ''} style={{ fontFamily: 'var(--ops-mono)' }}>{b.lotNo}</td>
                      <td>{b.receiptDate}</td>
                      <td>{b.expiryDate || <span style={{ color: 'var(--ops-ink-subtle)' }}>—</span>}</td>
                      <td className="num">{b.available}</td>
                      <td className="num">
                        <input
                          type="number"
                          style={{ width: 64, textAlign: 'right', padding: '4px 6px', border: '1px solid var(--ops-outline-stronger)', borderRadius: 4, fontFamily: 'var(--ops-mono)' }}
                          value={b.qtyToReserve}
                          min={0}
                          max={b.available}
                          onChange={e => onBatchQtyChange(b.batchId, Math.max(0, Math.min(b.available, parseInt(e.target.value || '0', 10))))}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

window.AllocationCard = AllocationCard;
