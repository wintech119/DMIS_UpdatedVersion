/**
 * Batch Allocation Module
 * Handles batch selection and drawer UI
 */

const BatchAllocation = (function() {
    // State
    let currentItemId = null;
    let currentItemData = null;
    let currentBatches = {};
    let currentAllocations = {};
    
    // DOM elements
    const elements = {
        overlay: null,
        drawer: null,
        closeBtn: null,
        cancelBtn: null,
        applyBtn: null,
        itemName: null,
        requestedQty: null,
        allocatedQty: null,
        remainingQty: null,
        issuanceOrder: null,
        batchList: null,
        emptyState: null,
        loadingState: null,
        batchItemTemplate: null
    };
    
    /**
     * Initialize the batch allocation module
     */
    function init() {
        // Get DOM elements
        elements.overlay = document.getElementById('batchDrawerOverlay');
        elements.drawer = document.getElementById('batchDrawer');
        elements.closeBtn = document.getElementById('batchDrawerClose');
        elements.cancelBtn = document.getElementById('batchDrawerCancel');
        elements.applyBtn = document.getElementById('batchDrawerApply');
        elements.itemName = document.getElementById('batchDrawerItemName');
        elements.requestedQty = document.getElementById('batchRequestedQty');
        elements.allocatedQty = document.getElementById('batchAllocatedQty');
        elements.remainingQty = document.getElementById('batchRemainingQty');
        elements.issuanceOrder = document.getElementById('batchIssuanceOrder');
        elements.batchList = document.getElementById('batchList');
        elements.emptyState = document.getElementById('batchEmptyState');
        elements.loadingState = document.getElementById('batchLoadingState');
        elements.batchItemTemplate = document.getElementById('batchItemTemplate');
        
        // Attach event listeners
        if (elements.closeBtn) elements.closeBtn.addEventListener('click', closeDrawer);
        if (elements.cancelBtn) elements.cancelBtn.addEventListener('click', closeDrawer);
        if (elements.applyBtn) elements.applyBtn.addEventListener('click', applyAllocations);
        if (elements.overlay) elements.overlay.addEventListener('click', closeDrawer);
        
        // Event delegation for Select Batches buttons
        document.addEventListener('click', function(e) {
            const btn = e.target.closest('.select-batches-btn');
            if (btn) {
                const itemId = parseInt(btn.dataset.itemId);
                const itemName = btn.dataset.itemName || 'Unknown Item';
                const requestedQty = parseFloat(btn.dataset.requestedQty);
                openDrawer(itemId, itemName, requestedQty);
            }
        });
        
        // Expose open function globally (for backwards compatibility)
        window.openBatchDrawer = openDrawer;
    }
    
    /**
     * Open the batch drawer for a specific item
     * @param {number} itemId - Item ID
     * @param {string} itemName - Item name
     * @param {number} requestedQty - Requested quantity
     * @param {string} requiredUom - Required UOM (optional)
     */
    function openDrawer(itemId, itemName, requestedQty, requiredUom) {
        currentItemId = itemId;
        currentItemData = {
            itemId: itemId,
            itemName: itemName,
            requestedQty: requestedQty,
            requiredUom: requiredUom || null
        };
        
        // Update header
        elements.itemName.textContent = `${itemName}`;
        elements.requestedQty.textContent = formatNumber(requestedQty);
        
        // Show drawer
        elements.overlay.classList.add('active');
        elements.drawer.classList.add('active');
        document.body.classList.add('body-no-scroll');
        
        // Load batches
        loadBatches(itemId);
    }
    
    /**
     * Close the batch drawer
     */
    function closeDrawer() {
        elements.overlay.classList.remove('active');
        elements.drawer.classList.remove('active');
        document.body.classList.remove('body-no-scroll');
        
        // Reset state after animation
        setTimeout(() => {
            currentItemId = null;
            currentItemData = null;
            currentBatches = {};
            currentAllocations = {};
            elements.batchList.innerHTML = '';
        }, 300);
    }
    
    /**
     * Load available batches for the current item
     * @param {number} itemId - Item ID
     */
    async function loadBatches(itemId) {
        showLoading();
        
        try {
            // Load existing allocations to calculate remaining qty
            loadExistingAllocations();
            const alreadyAllocated = getTotalAllocated();
            const remainingQty = currentItemData.requestedQty - alreadyAllocated;
            
            // Build API URL with query parameters
            const params = new URLSearchParams();
            // Always include remaining_qty, even if 0 (for consistent API response format)
            params.append('remaining_qty', remainingQty);
            if (currentItemData.requiredUom) {
                params.append('required_uom', currentItemData.requiredUom);
            }
            // Include allocated batch IDs so they're always shown for editing
            const allocatedBatchIds = Object.keys(currentAllocations);
            if (allocatedBatchIds.length > 0) {
                params.append('allocated_batch_ids', allocatedBatchIds.join(','));
            }
            // Include current allocations so API can "release" them when calculating available qty
            if (Object.keys(currentAllocations).length > 0) {
                params.append('current_allocations', JSON.stringify(currentAllocations));
            }
            
            const url = `/packaging/api/item/${itemId}/batches?${params.toString()}`;
            console.log('Fetching batches from:', url);
            const response = await fetch(url);
            console.log('Response status:', response.status, response.statusText);
            const data = await response.json();
            console.log('Response data:', data);
            
            if (!response.ok) {
                throw new Error(data.error || 'Failed to load batches');
            }
            
            // Store item configuration
            currentItemData.issuanceOrder = data.issuance_order || 'FIFO';
            currentItemData.canExpire = data.can_expire;
            currentItemData.isBatched = data.is_batched;
            currentItemData.totalAvailable = data.total_available || 0;
            currentItemData.shortfall = data.shortfall || 0;
            currentItemData.canFulfill = data.can_fulfill || false;
            
            // Update issuance order display
            elements.issuanceOrder.textContent = data.issuance_order || 'FIFO';
            
            // Store batches (now a flat array with priority_group)
            currentBatches = {};
            const allBatches = Array.isArray(data.batches) ? data.batches : [];
            
            console.log(`API returned ${allBatches.length} batches:`, allBatches.map(b => `${b.batch_id} (${b.batch_no})`));
            
            allBatches.forEach(batch => {
                currentBatches[batch.batch_id] = batch;
            });
            
            // Check if previously allocated batches are in the list
            console.log('Previously allocated batch IDs:', Object.keys(currentAllocations));
            Object.keys(currentAllocations).forEach(batchId => {
                const found = currentBatches[batchId];
                console.log(`  - Batch ${batchId}: ${found ? 'FOUND in list' : 'NOT FOUND in list'}`);
            });
            
            // Show shortfall warning if needed
            if (currentItemData.shortfall > 0) {
                showShortfallWarning(currentItemData.totalAvailable, currentItemData.shortfall);
            }
            
            // Render batches
            renderBatches(allBatches);
            hideLoading();
            
        } catch (error) {
            console.error('Error loading batches:', error);
            hideLoading();
            showEmptyState();
            alert('Failed to load batches: ' + error.message);
        }
    }
    
    /**
     * Load existing allocations from the main form
     */
    function loadExistingAllocations() {
        currentAllocations = {};
        
        // Look for hidden inputs with pattern: batch_allocation_{itemId}_{batchId}
        const inputs = document.querySelectorAll(`input[name^="batch_allocation_${currentItemId}_"]`);
        
        console.log(`Loading existing allocations for item ${currentItemId}, found ${inputs.length} inputs`);
        
        inputs.forEach(input => {
            const parts = input.name.split('_');
            if (parts.length >= 4) {
                const batchId = parseInt(parts[3]);
                const qty = parseFloat(input.value) || 0;
                if (qty > 0) {
                    currentAllocations[batchId] = qty;
                    console.log(`  - Loaded allocation: batch ${batchId} = ${qty}`);
                }
            }
        });
        
        console.log('Current allocations:', currentAllocations);
        updateTotals();
    }
    
    /**
     * Show shortfall warning when batches cannot fully fulfill request
     * @param {number} totalAvailable - Total available across all batches
     * @param {number} shortfall - Amount that cannot be fulfilled
     */
    function showShortfallWarning(totalAvailable, shortfall) {
        const container = document.getElementById('batchListContainer');
        
        // Remove any existing warning
        const existingWarning = container.querySelector('.batch-shortfall-warning');
        if (existingWarning) {
            existingWarning.remove();
        }
        
        // Create new warning
        const warning = document.createElement('div');
        warning.className = 'batch-drawer-warning';
        warning.innerHTML = `
            <div class="batch-drawer-warning-content">
                <i class="bi bi-exclamation-triangle-fill batch-drawer-warning-icon"></i>
                <div class="batch-drawer-warning-body">
                    <div class="batch-drawer-warning-title">Insufficient Stock</div>
                    <div class="batch-drawer-warning-text">
                        Maximum available: <strong>${formatNumber(totalAvailable)}</strong> | 
                        Shortfall: <strong>${formatNumber(shortfall)}</strong>
                    </div>
                    <div class="batch-drawer-warning-note">
                        Partial fulfillment allowed. The request cannot be fully satisfied with current stock.
                    </div>
                </div>
            </div>
        `;
        
        container.insertBefore(warning, container.firstChild);
    }
    
    /**
     * Render the batch list grouped by warehouse
     * @param {Array} batches - Array of batch objects
     */
    function renderBatches(batches) {
        console.log(`Rendering ${batches.length} batches grouped by warehouse`);
        elements.batchList.innerHTML = '';
        
        if (batches.length === 0) {
            showEmptyState();
            hideJumpControl();
            return;
        }
        
        // Group batches by warehouse
        const warehouseGroups = groupBatchesByWarehouse(batches);
        
        // Render each warehouse section
        // Warehouse order doesn't matter - FEFO applies within each warehouse
        Object.keys(warehouseGroups).forEach(warehouseId => {
            const warehouseData = warehouseGroups[warehouseId];
            const warehouseSection = createWarehouseSection(warehouseId, warehouseData);
            elements.batchList.appendChild(warehouseSection);
        });
        
        // Populate jump-to-warehouse dropdown
        populateJumpControl(warehouseGroups);
        showJumpControl();
        
        hideEmptyState();
    }
    
    /**
     * Group batches by warehouse
     * Batches within each warehouse are already FEFO/FIFO sorted by backend
     * @param {Array} batches - Array of batch objects (FEFO sorted within each warehouse)
     * @returns {Object} Warehouses grouped by warehouse_id
     */
    function groupBatchesByWarehouse(batches) {
        const groups = {};
        
        batches.forEach(batch => {
            const warehouseId = batch.warehouse_id;
            if (!groups[warehouseId]) {
                groups[warehouseId] = {
                    warehouse_id: warehouseId,
                    warehouse_name: batch.warehouse_name,
                    batches: [],
                    total_available: 0
                };
            }
            groups[warehouseId].batches.push(batch);
            groups[warehouseId].total_available += batch.available_qty;
        });
        
        return groups;
    }
    
    /**
     * Create a warehouse section element
     * @param {string} warehouseId - Warehouse ID
     * @param {Object} warehouseData - Warehouse data with batches
     * @returns {HTMLElement} Warehouse section element
     */
    function createWarehouseSection(warehouseId, warehouseData) {
        const template = document.getElementById('warehouseSectionTemplate').content.cloneNode(true);
        const container = template.querySelector('.batch-warehouse-section');
        
        // Set warehouse ID
        container.dataset.warehouseId = warehouseId;
        container.id = `warehouse-section-${warehouseId}`;
        
        // Populate warehouse header
        container.querySelector('.warehouse-name-text').textContent = warehouseData.warehouse_name;
        container.querySelector('.warehouse-batch-count').textContent = `${warehouseData.batches.length} batch${warehouseData.batches.length !== 1 ? 'es' : ''}`;
        container.querySelector('.warehouse-total-qty').textContent = `${formatNumber(warehouseData.total_available)} available`;
        
        // Add batches to warehouse body
        const warehouseBody = container.querySelector('[data-warehouse-body]');
        warehouseData.batches.forEach(batch => {
            const batchElement = createBatchElement(batch);
            warehouseBody.appendChild(batchElement);
        });
        
        // Add collapse/expand functionality
        const collapseBtn = container.querySelector('.batch-warehouse-collapse-btn');
        const warehouseHeader = container.querySelector('.batch-warehouse-header');
        
        const toggleCollapse = () => {
            const isExpanded = collapseBtn.getAttribute('aria-expanded') === 'true';
            collapseBtn.setAttribute('aria-expanded', !isExpanded);
            warehouseBody.classList.toggle('collapsed');
        };
        
        collapseBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleCollapse();
        });
        
        warehouseHeader.addEventListener('click', () => {
            toggleCollapse();
        });
        
        // Update warehouse allocated summary when allocations change
        container.updateAllocationSummary = function() {
            updateWarehouseAllocationSummary(container, warehouseData);
        };
        
        // Initial allocation summary
        updateWarehouseAllocationSummary(container, warehouseData);
        
        return container;
    }
    
    /**
     * Update warehouse allocation summary
     * @param {HTMLElement} container - Warehouse section container
     * @param {Object} warehouseData - Warehouse data
     */
    function updateWarehouseAllocationSummary(container, warehouseData) {
        let totalAllocated = 0;
        warehouseData.batches.forEach(batch => {
            if (currentAllocations[batch.batch_id]) {
                totalAllocated += currentAllocations[batch.batch_id];
            }
        });
        
        const valueElement = container.querySelector('.warehouse-allocated-value');
        valueElement.textContent = formatNumber(totalAllocated);
    }
    
    /**
     * Populate jump-to-warehouse dropdown
     * @param {Object} warehouseGroups - Grouped warehouses
     */
    function populateJumpControl(warehouseGroups) {
        const select = document.getElementById('warehouseJumpSelect');
        if (!select) return;
        
        // Clear existing options except first (placeholder)
        select.innerHTML = '<option value="">Select warehouse...</option>';
        
        // Add warehouse options
        Object.keys(warehouseGroups).forEach(warehouseId => {
            const warehouse = warehouseGroups[warehouseId];
            const option = document.createElement('option');
            option.value = warehouseId;
            option.textContent = warehouse.warehouse_name;
            select.appendChild(option);
        });
        
        // Add change event listener
        select.addEventListener('change', function() {
            if (this.value) {
                jumpToWarehouse(this.value);
            }
        });
    }
    
    /**
     * Jump to a specific warehouse section
     * @param {string} warehouseId - Warehouse ID
     */
    function jumpToWarehouse(warehouseId) {
        const section = document.getElementById(`warehouse-section-${warehouseId}`);
        if (section) {
            section.scrollIntoView({ behavior: 'smooth', block: 'start' });
            
            // Flash highlight
            section.classList.add('batch-highlight');
            setTimeout(() => {
                section.classList.remove('batch-highlight');
            }, 1000);
        }
    }
    
    /**
     * Show jump-to-warehouse control
     */
    function showJumpControl() {
        const control = document.getElementById('warehouseJumpControl');
        if (control) {
            control.classList.remove('d-none');
            control.classList.add('d-block');
        }
    }
    
    /**
     * Hide jump-to-warehouse control
     */
    function hideJumpControl() {
        const control = document.getElementById('warehouseJumpControl');
        if (control) {
            control.classList.remove('d-block');
            control.classList.add('d-none');
        }
    }
    
    /**
     * Create a batch DOM element from template
     * @param {Object} batch - Batch data
     * @returns {HTMLElement} Batch element
     */
    function createBatchElement(batch) {
        const template = elements.batchItemTemplate.content.cloneNode(true);
        const container = template.querySelector('.batch-item');
        
        // Set batch ID and priority group
        container.dataset.batchId = batch.batch_id;
        container.dataset.priorityGroup = batch.priority_group !== undefined ? batch.priority_group : -1;
        
        // Populate batch details (warehouse name now in section header, not batch item)
        container.querySelector('.batch-number').textContent = batch.batch_no;
        container.querySelector('.batch-batch-date').textContent = formatDate(batch.batch_date) || 'N/A';
        container.querySelector('.batch-expiry-date').textContent = formatDate(batch.expiry_date) || 'N/A';
        container.querySelector('.batch-available-qty').textContent = formatNumber(batch.available_qty);
        
        const sizeUom = batch.size_spec ? `${batch.size_spec} ${batch.uom_code}` : batch.uom_code;
        container.querySelector('.batch-size-uom').textContent = sizeUom;
        
        // Check if expired or expiring soon
        const today = new Date();
        const expiryDate = batch.expiry_date ? new Date(batch.expiry_date) : null;
        
        if (expiryDate) {
            const daysToExpiry = Math.ceil((expiryDate - today) / (1000 * 60 * 60 * 24));
            
            if (daysToExpiry < 0) {
                container.classList.add('expired');
                const statusBadge = document.createElement('span');
                statusBadge.className = 'batch-item-status expired';
                statusBadge.textContent = 'Expired';
                container.querySelector('.batch-item-status-container').appendChild(statusBadge);
            } else if (daysToExpiry <= 30) {
                const statusBadge = document.createElement('span');
                statusBadge.className = 'batch-item-status expiring-soon';
                statusBadge.textContent = `Expires in ${daysToExpiry}d`;
                container.querySelector('.batch-item-status-container').appendChild(statusBadge);
            }
        }
        
        // Allocation input
        const input = container.querySelector('[data-batch-allocation-input]');
        input.max = batch.available_qty;
        const existingQty = currentAllocations[batch.batch_id];
        if (existingQty) {
            console.log(`Setting batch ${batch.batch_id} input to ${existingQty}`);
            input.value = existingQty;
        } else {
            input.value = '';
        }
        
        // Disable if expired
        if (container.classList.contains('expired')) {
            input.disabled = true;
        }
        
        // Input change event with pick order validation
        input.addEventListener('input', () => {
            const qty = parseFloat(input.value) || 0;
            
            // Validate quantity limits
            if (qty > batch.available_qty) {
                input.value = batch.available_qty;
            }
            if (qty < 0) {
                input.value = 0;
            }
            
            // Update allocations
            const finalQty = parseFloat(input.value) || 0;
            if (finalQty > 0) {
                currentAllocations[batch.batch_id] = finalQty;
                container.classList.add('has-allocation');
            } else {
                delete currentAllocations[batch.batch_id];
                container.classList.remove('has-allocation');
            }
            
            updateTotals();
        });
        
        // "Use Max" button
        const maxBtn = container.querySelector('[data-batch-max-btn]');
        maxBtn.addEventListener('click', () => {
            const remainingQty = currentItemData.requestedQty - getTotalAllocated();
            const maxQty = Math.min(batch.available_qty, remainingQty + (currentAllocations[batch.batch_id] || 0));
            
            input.value = maxQty;
            input.dispatchEvent(new Event('input'));
        });
        
        // Add has-allocation class if already allocated
        if (currentAllocations[batch.batch_id]) {
            container.classList.add('has-allocation');
        }
        
        return container;
    }
    
    /**
     * Validate pick order - ensure batches are picked in priority group order
     * @returns {Object} Validation result {isValid: boolean, error: string}
     */
    function validatePickOrder() {
        const batchElements = elements.batchList.querySelectorAll('.batch-item');
        if (batchElements.length === 0) {
            return {isValid: true, error: ''};
        }
        
        // Group batches by priority
        const priorityGroups = {};
        batchElements.forEach(el => {
            const batchId = parseInt(el.dataset.batchId);
            const priorityGroup = parseInt(el.dataset.priorityGroup);
            const batch = currentBatches[batchId];
            
            if (!batch) return;
            
            if (!priorityGroups[priorityGroup]) {
                priorityGroups[priorityGroup] = [];
            }
            
            priorityGroups[priorityGroup].push({
                batchId: batchId,
                priorityGroup: priorityGroup,
                availableQty: batch.available_qty,
                allocatedQty: currentAllocations[batchId] || 0,
                batchNo: batch.batch_no
            });
        });
        
        // Check each priority group in order
        const sortedGroupIds = Object.keys(priorityGroups).map(Number).sort((a, b) => a - b);
        
        for (let i = 0; i < sortedGroupIds.length; i++) {
            const groupId = sortedGroupIds[i];
            const group = priorityGroups[groupId];
            
            // Check if any later group has allocations
            const laterGroups = sortedGroupIds.slice(i + 1);
            const hasLaterAllocations = laterGroups.some(laterGroupId => {
                return priorityGroups[laterGroupId].some(b => b.allocatedQty > 0);
            });
            
            if (hasLaterAllocations) {
                // Check if current group is fully allocated
                const groupTotalAvailable = group.reduce((sum, b) => sum + b.availableQty, 0);
                const groupTotalAllocated = group.reduce((sum, b) => sum + b.allocatedQty, 0);
                
                if (groupTotalAllocated < groupTotalAvailable) {
                    // Clear error styling from all batches
                    batchElements.forEach(el => el.classList.remove('pick-order-error'));
                    
                    // Highlight problematic batches
                    laterGroups.forEach(laterGroupId => {
                        priorityGroups[laterGroupId].forEach(b => {
                            if (b.allocatedQty > 0) {
                                const el = elements.batchList.querySelector(`[data-batch-id="${b.batchId}"]`);
                                if (el) el.classList.add('pick-order-error');
                            }
                        });
                    });
                    
                    const remaining = groupTotalAvailable - groupTotalAllocated;
                    return {
                        isValid: false,
                        error: `Pick order violation: ${formatNumber(remaining)} units still available in higher-priority batches. You must allocate from earlier batches before picking from later ones.`
                    };
                }
            }
        }
        
        // Clear any error styling
        batchElements.forEach(el => el.classList.remove('pick-order-error'));
        return {isValid: true, error: ''};
    }
    
    /**
     * Apply allocations to the main form
     */
    function applyAllocations() {
        // Validate total allocated doesn't exceed requested
        const totalAllocated = getTotalAllocated();
        const remaining = currentItemData.requestedQty - totalAllocated;
        if (totalAllocated > currentItemData.requestedQty) {
            alert(`Total allocated (${formatNumber(totalAllocated)}) exceeds requested quantity (${formatNumber(currentItemData.requestedQty)})`);
            return;
        }
        
        console.log(`Applying allocations for item ${currentItemId}:`, currentAllocations);
        
        // Remove existing allocation inputs for this item
        const existingInputs = document.querySelectorAll(`input[name^="batch_allocation_${currentItemId}_"]`);
        console.log(`Removing ${existingInputs.length} existing inputs`);
        existingInputs.forEach(input => input.remove());
        
        // Create new hidden inputs for each allocation
        const form = document.querySelector('form');
        console.log('Form element:', form);
        
        for (const [batchId, qty] of Object.entries(currentAllocations)) {
            if (qty > 0) {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = `batch_allocation_${currentItemId}_${batchId}`;
                input.value = qty;
                form.appendChild(input);
                console.log(`  - Created hidden input: ${input.name} = ${input.value}`);
            }
        }
        
        // Verify inputs were added
        const verifyInputs = document.querySelectorAll(`input[name^="batch_allocation_${currentItemId}_"]`);
        console.log(`Verification: Found ${verifyInputs.length} hidden inputs after adding`);
        verifyInputs.forEach(input => {
            console.log(`  - ${input.name} = ${input.value}`);
        });
        
        // Update the main page display
        updateMainPageDisplay();
        
        // Close drawer
        closeDrawer();
    }
    
    /**
     * Update the main page to show allocated quantities
     */
    function updateMainPageDisplay() {
        const totalAllocated = getTotalAllocated();
        const requestedQty = currentItemData.requestedQty;
        const remaining = Math.max(0, requestedQty - totalAllocated);
        
        // Update allocated quantity display in main form (if element exists)
        const allocatedDisplay = document.getElementById(`allocated_${currentItemId}`);
        if (allocatedDisplay) {
            allocatedDisplay.textContent = formatNumber(totalAllocated);
        }
        
        // Update Allocated column (approve.html uses total_${itemId})
        const totalDisplay = document.getElementById(`total_${currentItemId}`);
        if (totalDisplay) {
            totalDisplay.textContent = formatNumber(totalAllocated);
        }
        
        // Update Remaining column
        const remainingDisplay = document.getElementById(`remaining_${currentItemId}`);
        if (remainingDisplay) {
            remainingDisplay.textContent = formatNumber(remaining);
        }
        
        // Use the main page's updateAllocation function which has the complete logic
        // This handles allocation activity tracking, status dropdown updates, and validation
        if (typeof window.updateAllocation === 'function') {
            console.log(`[Batch Drawer] Calling updateAllocation for item ${currentItemId}`);
            window.updateAllocation(currentItemId, true); // Pass true to indicate batch allocations exist
        } else {
            console.warn(`[Batch Drawer] updateAllocation function not found, falling back to manual status update`);
            
            // Fallback: Update status dropdown manually if updateAllocation doesn't exist
            const statusDropdown = document.getElementById(`status_${currentItemId}`);
            if (statusDropdown) {
                console.log(`[Status Update] Item ${currentItemId}:`, {
                    totalAllocated,
                    requestedQty,
                    currentStatus: statusDropdown.value
                });
                
                // CRITICAL: Call the new updateStatusDropdown function from prepare.html if available
                if (typeof window.updateStatusDropdown === 'function') {
                    window.updateStatusDropdown(currentItemId, totalAllocated, requestedQty);
                }
            }
        }
        
        // Update "Select Batches" button to show allocation count
        const selectBtn = document.querySelector(`.select-batches-btn[data-item-id="${currentItemId}"]`);
        if (selectBtn) {
            const batchCount = Object.keys(currentAllocations).filter(key => currentAllocations[key] > 0).length;
            
            if (batchCount > 0) {
                // Count unique warehouses from allocations
                const warehouseIds = new Set();
                for (const batchId of Object.keys(currentAllocations)) {
                    if (currentAllocations[batchId] > 0) {
                        const batch = currentBatches[batchId];
                        if (batch && batch.warehouseId) {
                            warehouseIds.add(batch.warehouseId);
                        }
                    }
                }
                const warehouseCount = warehouseIds.size;
                
                selectBtn.innerHTML = `<i class="bi bi-eye"></i> View/Edit Batches <span class="badge bg-light text-success ms-1">${batchCount}</span>`;
                selectBtn.classList.add('btn-success');
                selectBtn.classList.remove('btn-outline-secondary');
                
                // Update warehouse summary text (if it exists)
                const summaryDiv = selectBtn.parentElement.querySelector('.text-muted');
                if (summaryDiv) {
                    summaryDiv.textContent = `${warehouseCount} warehouse${warehouseCount > 1 ? 's' : ''}`;
                } else {
                    // Create summary div if it doesn't exist
                    const newSummary = document.createElement('div');
                    newSummary.className = 'text-muted text-small mt-1';
                    newSummary.textContent = `${warehouseCount} warehouse${warehouseCount > 1 ? 's' : ''}`;
                    selectBtn.parentElement.appendChild(newSummary);
                }
            } else {
                selectBtn.innerHTML = '<i class="bi bi-clipboard-check"></i> Select Batches';
                selectBtn.classList.remove('btn-success');
                selectBtn.classList.add('btn-outline-secondary');
                
                // Remove warehouse summary if it exists
                const summaryDiv = selectBtn.parentElement.querySelector('.text-muted');
                if (summaryDiv) {
                    summaryDiv.remove();
                }
            }
        }
    }
    
    /**
     * Calculate total allocated quantity
     * @returns {number} Total allocated
     */
    function getTotalAllocated() {
        return Object.values(currentAllocations).reduce((sum, qty) => sum + qty, 0);
    }
    
    /**
     * Update summary totals
     */
    function updateTotals() {
        const requested = currentItemData.requestedQty;
        const allocated = getTotalAllocated();
        const remaining = Math.max(0, requested - allocated);
        
        elements.allocatedQty.textContent = formatNumber(allocated);
        elements.remainingQty.textContent = formatNumber(remaining);
        
        // Update remaining color
        if (remaining === 0) {
            elements.remainingQty.classList.remove('warning');
            elements.remainingQty.classList.add('highlight');
        } else {
            elements.remainingQty.classList.remove('highlight');
            elements.remainingQty.classList.add('warning');
        }
        
        // Update warehouse allocation summaries
        const warehouseSections = elements.batchList.querySelectorAll('.batch-warehouse-section');
        warehouseSections.forEach(section => {
            const updateAllocationSummary = section.updateAllocationSummary;
            if (typeof updateAllocationSummary === 'function') {
                updateAllocationSummary();
            }
            
            // Manual update as fallback
            const warehouseId = section.dataset.warehouseId;
            const batches = Array.from(section.querySelectorAll('.batch-item'));
            let warehouseAllocated = 0;
            
            batches.forEach(batchEl => {
                const batchId = parseInt(batchEl.dataset.batchId);
                if (currentAllocations[batchId]) {
                    warehouseAllocated += currentAllocations[batchId];
                }
            });
            
            const valueElement = section.querySelector('.warehouse-allocated-value');
            if (valueElement) {
                valueElement.textContent = formatNumber(warehouseAllocated);
            }
        });
    }
    
    /**
     * Show loading state
     */
    function showLoading() {
        elements.batchList.classList.add('d-none');
        elements.emptyState.classList.add('d-none');
        elements.loadingState.classList.remove('d-none');
        elements.loadingState.classList.add('d-flex');
    }
    
    /**
     * Hide loading state
     */
    function hideLoading() {
        elements.loadingState.classList.add('d-none');
        elements.loadingState.classList.remove('d-flex');
        elements.batchList.classList.remove('d-none');
        elements.batchList.classList.add('d-flex');
    }
    
    /**
     * Show empty state
     */
    function showEmptyState() {
        elements.batchList.classList.add('d-none');
        elements.emptyState.classList.remove('d-none');
        elements.emptyState.classList.add('d-block');
    }
    
    /**
     * Hide empty state
     */
    function hideEmptyState() {
        elements.emptyState.classList.add('d-none');
        elements.emptyState.classList.remove('d-block');
    }
    
    /**
     * Format a number with commas
     * @param {number} num - Number to format
     * @returns {string} Formatted number
     */
    function formatNumber(num) {
        if (num === null || num === undefined) return '0';
        return parseFloat(num).toLocaleString('en-US', {
            minimumFractionDigits: 0,
            maximumFractionDigits: 4
        });
    }
    
    /**
     * Format a date string
     * @param {string} dateStr - ISO date string
     * @returns {string} Formatted date
     */
    function formatDate(dateStr) {
        if (!dateStr) return null;
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    }
    
    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    
    // Public API
    return {
        openDrawer: openDrawer,
        closeDrawer: closeDrawer
    };
})();
