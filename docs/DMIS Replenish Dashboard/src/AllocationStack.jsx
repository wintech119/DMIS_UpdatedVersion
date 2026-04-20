// AllocationStack — ranked cards + add-warehouse + aggregate summary.
function AllocationStack({
  item,
  onItemChange,
  onAcceptPartial,
  partialAccepted,
  onReopenPartial,
}) {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [enteringId, setEnteringId] = React.useState(null);

  const cards = item.warehouseCards || [];
  const alt = (item.alternateWarehouses || []).filter(a => !cards.some(c => c.warehouseId === a.warehouseId));

  const totalReserving = cards.reduce((s, c) => s + (c.qty ?? 0), 0);
  const shortfall = Math.max(0, item.requestedQty - totalReserving);
  const anyOver = cards.some(c => (c.qty ?? 0) > c.totalAvailable);

  // FEFO bypass detection: primary card qty=0 AND at least one later card has qty>0
  const primary = cards.find(c => c.issuanceOrder === 1);
  const laterHasQty = cards.some(c => c.issuanceOrder > 1 && (c.qty ?? 0) > 0);
  const fefoBypassActive = primary && (primary.qty ?? 0) === 0 && laterHasQty;
  const overrideFlagged = fefoBypassActive ||
    (partialAccepted && shortfall > 0 && alt.length > 0) ||
    cards.some(c => c.bypassReason && c.bypassReason.trim().length > 0);

  // Aggregate status
  let aggregate;
  if (anyOver) aggregate = { key: 'OVER', tone: 'warning', icon: 'warning_amber', title: 'Over — exceeds available' };
  else if (totalReserving === 0) aggregate = { key: 'DRAFT', tone: 'draft', icon: 'radio_button_unchecked', title: 'Draft' };
  else if (totalReserving >= item.requestedQty) aggregate = { key: 'FILLED', tone: 'filled', icon: 'check_circle', title: `Filled · ${cards.filter(c => c.qty > 0).length} warehouse${cards.filter(c => c.qty > 0).length === 1 ? '' : 's'}` };
  else if (partialAccepted) {
    aggregate = overrideFlagged
      ? { key: 'PARTIAL_OVERRIDE', tone: 'override', icon: 'flag', title: `Override flagged · ${shortfall} short` }
      : { key: 'PARTIAL_COMPLIANT', tone: 'partial', icon: 'check_circle', title: `Compliant partial · ${shortfall} short` };
  }
  else aggregate = { key: 'PENDING', tone: 'partial', icon: 'info', title: `Reserving ${totalReserving} of ${item.requestedQty}` };

  const updateCard = (warehouseId, patch) => {
    const nextCards = cards.map(c => c.warehouseId === warehouseId ? { ...c, ...patch } : c);
    onItemChange({ ...item, warehouseCards: nextCards });
  };
  const addWarehouse = (alt) => {
    const remaining = Math.max(0, item.requestedQty - totalReserving);
    const newCard = {
      warehouseId: alt.warehouseId,
      warehouseName: alt.warehouseName,
      totalAvailable: alt.available,
      suggestedQty: Math.min(alt.available, remaining),
      qty: Math.min(alt.available, remaining),
      issuanceOrder: cards.length + 1,
      rankReason: cards.length === 0 ? 'EARLIEST_RECEIPT' : 'COVERS_REMAINDER',
      rankReasonDate: alt.nextExpiryDate,
      batches: [
        { batchId: `b-${alt.warehouseId}-sim`, lotNo: `SIM-${alt.warehouseId.slice(-4).toUpperCase()}`, receiptDate: 'Auto', expiryDate: alt.nextExpiryDate || null, available: alt.available, qtyToReserve: Math.min(alt.available, remaining) },
      ],
    };
    setEnteringId(alt.warehouseId);
    setTimeout(() => setEnteringId(null), 400);
    onItemChange({ ...item, warehouseCards: [...cards, newCard] });
    setMenuOpen(false);
  };
  const removeCard = (warehouseId) => {
    const nextCards = cards
      .filter(c => c.warehouseId !== warehouseId)
      .map((c, i) => ({ ...c, issuanceOrder: i + 1 }));
    onItemChange({ ...item, warehouseCards: nextCards });
  };

  const addButtonCopy = shortfall > 0
    ? (alt.length > 0 ? `+ Add next warehouse (${alt.length} available)` : 'No further warehouses hold this item')
    : (alt.length > 0 ? '+ Add another warehouse' : '');

  const addDisabled = alt.length === 0;
  const addEmphasis = shortfall > 0 && alt.length > 0;

  let runningOthers = 0;
  const cardsWithContext = cards.map(c => {
    const othersTotal = totalReserving - (c.qty ?? 0);
    return { card: c, others: othersTotal };
  });

  return (
    <div className="ops-alloc-stack" role="region" aria-label={`Warehouse stack for ${item.itemName}`}>
      {cardsWithContext.map(({ card, others }) => (
        <AllocationCard
          key={card.warehouseId}
          card={card}
          requestedQty={item.requestedQty}
          rankingPolicy={item.rankingPolicy}
          totalReservingFromOthers={others}
          canRemove={cards.length > 1}
          onQtyChange={(qty) => updateCard(card.warehouseId, { qty })}
          onBatchQtyChange={(batchId, qty) => {
            const nextBatches = card.batches.map(b => b.batchId === batchId ? { ...b, qtyToReserve: qty } : b);
            const total = nextBatches.reduce((s, b) => s + b.qtyToReserve, 0);
            updateCard(card.warehouseId, { batches: nextBatches, qty: total });
          }}
          onRemove={() => removeCard(card.warehouseId)}
          onBypassReasonChange={(reason) => updateCard(card.warehouseId, { bypassReason: reason })}
          showBypassReason={fefoBypassActive && card.issuanceOrder === 1}
          isEntering={enteringId === card.warehouseId}
        />
      ))}

      {(alt.length > 0 || (shortfall > 0 && alt.length === 0)) && (
        <div className="ops-alloc-add">
          <button
            className={`ops-alloc-add__btn ${addEmphasis ? 'ops-alloc-add__btn--emphasis' : ''}`}
            onClick={() => !addDisabled && setMenuOpen(o => !o)}
            disabled={addDisabled}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            <MI name={addDisabled ? 'info' : 'add'} />
            {addButtonCopy}
          </button>
          {menuOpen && alt.length > 0 && (
            <div className="ops-alloc-menu" role="menu" onMouseLeave={() => setMenuOpen(false)}>
              {alt.map(a => (
                <button
                  key={a.warehouseId}
                  className="ops-alloc-menu__item"
                  role="menuitem"
                  onClick={() => addWarehouse(a)}
                >
                  <Chip tone="neutral-outline">+{cards.length + (a.issuanceOrder - cards.length)} · {item.rankingPolicy}</Chip>
                  <div>
                    <div className="ops-alloc-menu__item-name">{a.warehouseName}</div>
                    <div className="ops-alloc-menu__item-meta">
                      {a.nextExpiryDate ? `Next expiry ${a.nextExpiryDate}` : 'No expiry tracked (FIFO)'}
                    </div>
                  </div>
                  <span className="ops-alloc-menu__item-avail">{a.available} avail</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Aggregate summary — always visible */}
      <div className={`ops-alloc-summary ops-alloc-summary--${aggregate.tone}`} role="status" aria-live="polite">
        <div className="ops-alloc-summary__lead">
          <MI name={aggregate.icon} />
          <span>
            <strong>{aggregate.title}</strong>
            {' · '}
            Reserving <strong>{totalReserving}</strong> of <strong>{item.requestedQty}</strong>
            {shortfall > 0 && <> · Shortfall <strong>{shortfall}</strong></>}
          </span>
        </div>
        <div className="ops-alloc-summary__actions">
          {shortfall > 0 && !partialAccepted && (
            <Button variant="secondary" icon="check" onClick={() => onAcceptPartial({ shortfall, alternatesAvailable: alt.length > 0 })}>
              Accept partial ({shortfall} short)
            </Button>
          )}
          {partialAccepted && (
            <Button variant="link" icon="undo" onClick={onReopenPartial}>
              Reopen
            </Button>
          )}
          {shortfall > 0 && alt.length > 0 && !partialAccepted && (
            <Button variant="primary" icon="add" onClick={() => setMenuOpen(true)}>
              Add next warehouse
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

window.AllocationStack = AllocationStack;
