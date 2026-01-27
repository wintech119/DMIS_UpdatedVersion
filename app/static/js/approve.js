/**
 * Package Approval - CSP-compliant JavaScript
 * Handles inventory validation, status dropdown logic, and allocation tracking
 */

document.addEventListener('DOMContentLoaded', function() {
    // Load inventory levels for all items
    loadAllInventory();
    
    // Add event listeners for allocation inputs
    document.querySelectorAll('.allocation-input').forEach(input => {
        input.addEventListener('input', function() {
            const itemId = this.dataset.itemId;
            const warehouseId = this.dataset.warehouseId;
            
            // Update warehouse stock display in real-time
            updateWarehouseStock(itemId, warehouseId);
            
            // Update item calculations and metrics
            updateItemCalculations(itemId);
            updateMetrics();
        });
    });
    
    // Form validation on submit
    const packagingForm = document.getElementById('packagingForm');
    if (packagingForm) {
        packagingForm.addEventListener('submit', function(e) {
            // Skip validation for cancel button
            const submitter = e.submitter;
            if (!submitter) return; // Browser compatibility
            
            const action = submitter.value || submitter.getAttribute('value');
            
            // Only validate for submit actions, not cancel or save_draft
            if (action === 'submit_for_approval' || action === 'approve_and_dispatch') {
                if (!validateAllAllocations()) {
                    e.preventDefault();
                    alert('Please fix allocation errors before submitting. Check that:\n- No allocation exceeds available stock\n- No total allocation exceeds requested quantity');
                }
            }
        });
    }
    
    // Calculate initial state for pre-populated allocations
    const itemIds = [...new Set([...document.querySelectorAll('.item-row')].map(row => row.dataset.itemId))];
    itemIds.forEach(itemId => {
        updateItemCalculations(itemId);
    });
    
    // Update initial metrics
    updateMetrics();
    
    // Initialize reason fields on page load
    const statusDropdowns = document.querySelectorAll('.status-dropdown');
    statusDropdowns.forEach(dropdown => {
        const itemId = dropdown.dataset.itemId;
        if (itemId) {
            toggleReasonField(itemId);
        }
        
        // Add change event listener for status dropdowns
        dropdown.addEventListener('change', function() {
            toggleReasonField(itemId);
        });
    });
    
    // Search input for filtering
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('keyup', filterItems);
    }
    
    // Filter dropdown
    const filterDropdown = document.getElementById('filterDropdown');
    if (filterDropdown) {
        filterDropdown.addEventListener('change', filterItems);
    }
    
    // Jump to first unallocated button
    const jumpBtn = document.querySelector('[data-action="jump-unallocated"]');
    if (jumpBtn) {
        jumpBtn.addEventListener('click', jumpToFirstUnallocated);
    }
    
    // Select batches buttons (event delegation)
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.select-batches-btn');
        if (btn) {
            const itemId = btn.dataset.itemId;
            const itemName = btn.dataset.itemName;
            const requestQty = btn.dataset.requestQty;
            openBatchDrawer(itemId, itemName, requestQty);
        }
    });
});

function loadAllInventory() {
    document.querySelectorAll('.allocation-input').forEach(input => {
        const itemId = input.dataset.itemId;
        const warehouseId = input.dataset.warehouseId;
        loadInventory(itemId, warehouseId);
    });
}

function loadInventory(itemId, warehouseId) {
    const stockElement = document.getElementById(`stock_${itemId}_${warehouseId}`);
    
    fetch(`/packaging/api/inventory/${itemId}/${warehouseId}`)
        .then(response => response.json())
        .then(data => {
            const usable = parseFloat(data.usable_qty || 0);
            const reserved = parseFloat(data.reserved_qty || 0);
            
            // Store both usable and reserved quantities
            stockElement.dataset.usableQty = usable;
            stockElement.dataset.reservedQty = reserved;
            
            // Calculate original available as usable - reserved (consistent with DB logic)
            const originalAvailable = Math.max(0, usable - reserved);
            stockElement.dataset.originalQty = originalAvailable;
            
            // Update display with current allocation
            updateWarehouseStock(itemId, warehouseId);
        })
        .catch(error => {
            stockElement.textContent = '?';
            stockElement.classList.add('text-danger');
            stockElement.title = 'Error loading stock';
            console.error('Inventory load error:', error);
        });
}

function updateWarehouseStock(itemId, warehouseId) {
    const stockElement = document.getElementById(`stock_${itemId}_${warehouseId}`);
    const allocationInput = document.getElementById(`allocation_${itemId}_${warehouseId}`);
    
    const usableQty = parseFloat(stockElement.dataset.usableQty || 0);
    const reservedQty = parseFloat(stockElement.dataset.reservedQty || 0);
    const originalAvailable = parseFloat(stockElement.dataset.originalQty || 0);
    const allocated = parseFloat(allocationInput.value || 0);
    const remaining = Math.max(0, originalAvailable - allocated);
    
    stockElement.textContent = remaining.toFixed(0);
    
    // Build tooltip with detailed breakdown
    const tooltip = `Usable: ${usableQty.toFixed(0)}, Reserved (other packages): ${reservedQty.toFixed(0)}, Available: ${originalAvailable.toFixed(0)}, Allocated (this package): ${allocated.toFixed(0)}, Remaining: ${remaining.toFixed(0)}`;
    
    // Update color classes
    stockElement.classList.remove('text-danger', 'text-warning', 'text-dark');
    if (remaining === 0) {
        stockElement.classList.add('text-danger');
    } else if (allocated > 0) {
        stockElement.classList.add('text-warning');
    } else {
        stockElement.classList.add('text-dark');
    }
    stockElement.title = tooltip;
}

function updateItemCalculations(itemId) {
    // Get allocation inputs for this item
    const allocationInputs = document.querySelectorAll(`.allocation-input[data-item-id="${itemId}"]`);
    
    // Get requested quantity
    const row = document.querySelector(`tr[data-item-id="${itemId}"]`);
    const requestedQty = parseFloat(row.querySelector('[data-requested-qty]').dataset.requestedQty);
    
    let totalAllocated = 0;
    
    if (allocationInputs.length > 0) {
        // Calculate from allocation inputs (after batch drawer use)
        allocationInputs.forEach(input => {
            totalAllocated += parseFloat(input.value || 0);
        });
        
        // Update displayed totals
        const totalElement = document.getElementById(`total_${itemId}`);
        totalElement.textContent = totalAllocated.toFixed(2);
        
        const remaining = requestedQty - totalAllocated;
        const remainingElement = document.getElementById(`remaining_${itemId}`);
        remainingElement.textContent = remaining.toFixed(2);
    } else {
        // Read from displayed values (server-calculated on page load)
        const totalElement = document.getElementById(`total_${itemId}`);
        totalAllocated = parseFloat(totalElement.textContent || 0);
    }
    
    // Always update status dropdown and validation (even on page load)
    updateStatusDropdown(itemId, totalAllocated, requestedQty);
    validateQuantityLimit(itemId, totalAllocated, requestedQty);
}

function updateStatusDropdown(itemId, allocated, requested) {
    const statusDropdown = document.getElementById(`status_${itemId}`);
    if (!statusDropdown) return;
    
    const autoStatus = statusDropdown.dataset.autoStatus;
    const currentValue = statusDropdown.value;
    
    // Determine auto status based on allocation
    let newAutoStatus;
    if (allocated === 0) {
        newAutoStatus = 'R';  // Requested
    } else if (allocated >= requested) {
        newAutoStatus = 'F';  // Filled
    } else {
        newAutoStatus = 'P';  // Partly filled
    }
    
    // Update data attribute
    statusDropdown.dataset.autoStatus = newAutoStatus;
    
    // CRITICAL: Update allowed options FIRST (rebuilds dropdown with correct options)
    // Then set the value (otherwise 'P' option might not exist when trying to select it)
    updateAllowedStatusOptions(itemId, allocated, requested);
    
    // Auto-select if current status doesn't match the new allocation state
    // Only auto-change for automatic statuses (R, P, F), not manual ones (D, U, W, L)
    const autoStatuses = ['R', 'P', 'F'];
    if (autoStatuses.includes(currentValue)) {
        statusDropdown.value = newAutoStatus;
    }
}

function updateAllowedStatusOptions(itemId, allocated, requested) {
    const statusDropdown = document.getElementById(`status_${itemId}`);
    if (!statusDropdown) return;
    
    // Get status map from global variable (injected by template)
    const statusMap = window.DMIS_STATUS_MAP || {};
    
    // Determine allowed status codes based on allocation
    // D, U, W can override any allocation
    // L (Allowed Limit) can be used for partial or full allocations
    let allowedCodes;
    if (allocated === 0) {
        allowedCodes = ['R', 'D', 'U', 'W'];
    } else if (allocated >= requested) {
        allowedCodes = ['F', 'L', 'D', 'U', 'W'];
    } else {
        allowedCodes = ['P', 'L', 'D', 'U', 'W'];
    }
    
    // Get current value before updating options
    const currentValue = statusDropdown.value;
    
    // CRITICAL: Preserve current selection even if outside allowed codes
    // This prevents discarding legitimate manual statuses (e.g., Denied after partial allocation)
    const finalAllowedCodes = [...allowedCodes];
    if (currentValue && !allowedCodes.includes(currentValue)) {
        finalAllowedCodes.push(currentValue);
    }
    
    // Rebuild dropdown options
    statusDropdown.innerHTML = '';
    finalAllowedCodes.forEach(code => {
        const option = document.createElement('option');
        option.value = code;
        option.textContent = statusMap[code]?.desc || code;
        if (code === currentValue) {
            option.selected = true;
        }
        statusDropdown.appendChild(option);
    });
    
    // Update data attribute with allowed codes
    statusDropdown.dataset.allowedCodes = allowedCodes.join(',');
}

function validateQuantityLimit(itemId, allocated, requested) {
    const errorDiv = document.getElementById(`status_error_${itemId}`);
    const statusDropdown = document.getElementById(`status_${itemId}`);
    
    if (allocated > requested) {
        statusDropdown.classList.add('is-invalid');
        errorDiv.textContent = `Total allocated (${allocated.toFixed(2)}) exceeds requested (${requested.toFixed(2)})`;
        errorDiv.classList.remove('d-none');
        errorDiv.classList.add('d-block');
        return false;
    } else {
        statusDropdown.classList.remove('is-invalid');
        errorDiv.classList.remove('d-block');
        errorDiv.classList.add('d-none');
        return true;
    }
}

function toggleReasonField(itemId) {
    const statusDropdown = document.getElementById(`status_${itemId}`);
    const reasonWrapper = document.getElementById(`reason_wrapper_${itemId}`);
    const reasonField = document.getElementById(`status_reason_${itemId}`);
    
    if (!statusDropdown || !reasonWrapper) return;
    
    const selectedStatus = statusDropdown.value;
    
    // Show reason field for D (Denied) or L (Allowed Limit)
    if (selectedStatus === 'D' || selectedStatus === 'L') {
        reasonWrapper.classList.remove('d-none');
        reasonWrapper.classList.add('d-block');
        reasonField.setAttribute('required', 'required');
    } else {
        reasonWrapper.classList.remove('d-block');
        reasonWrapper.classList.add('d-none');
        reasonField.removeAttribute('required');
        reasonField.value = ''; // Clear the field when hidden
    }
}

function updateMetrics() {
    const totalItems = document.querySelectorAll('.item-row').length;
    let fullyAllocated = 0;
    let partiallyAllocated = 0;
    let unallocated = 0;
    
    document.querySelectorAll('.item-row').forEach(row => {
        const itemId = row.dataset.itemId;
        const requestedQty = parseFloat(row.querySelector('[data-requested-qty]').dataset.requestedQty);
        
        // Read the displayed total allocated value (which may be server-calculated or JS-updated)
        const totalAllocatedElement = document.getElementById(`total_${itemId}`);
        const totalAllocated = parseFloat(totalAllocatedElement.textContent || 0);
        
        if (totalAllocated === 0) {
            unallocated++;
        } else if (totalAllocated >= requestedQty) {
            fullyAllocated++;
        } else {
            partiallyAllocated++;
        }
    });
    
    document.getElementById('metric-total').textContent = totalItems;
    document.getElementById('metric-filled').textContent = fullyAllocated;
    document.getElementById('metric-partial').textContent = partiallyAllocated;
    document.getElementById('metric-unallocated').textContent = unallocated;
}

function filterItems() {
    const searchInput = document.getElementById('searchInput');
    const filterDropdown = document.getElementById('filterDropdown');
    
    const searchTerm = searchInput ? searchInput.value.toLowerCase() : '';
    const filterValue = filterDropdown ? filterDropdown.value : 'all';
    
    document.querySelectorAll('.item-row').forEach(row => {
        const itemName = row.dataset.itemName.toLowerCase();
        const itemSku = row.dataset.itemSku.toLowerCase();
        const itemId = row.dataset.itemId;
        
        // Check search match
        const searchMatch = itemName.includes(searchTerm) || itemSku.includes(searchTerm);
        
        // Check filter match
        let filterMatch = true;
        if (filterValue !== 'all') {
            const requestedQty = parseFloat(row.querySelector('[data-requested-qty]').dataset.requestedQty);
            // Read the displayed total allocated value
            const totalAllocatedElement = document.getElementById(`total_${itemId}`);
            const totalAllocated = parseFloat(totalAllocatedElement.textContent || 0);
            
            if (filterValue === 'unallocated') {
                filterMatch = totalAllocated === 0;
            } else if (filterValue === 'partial') {
                filterMatch = totalAllocated > 0 && totalAllocated < requestedQty;
            } else if (filterValue === 'filled') {
                filterMatch = totalAllocated >= requestedQty;
            }
        }
        
        // Show or hide row
        if (searchMatch && filterMatch) {
            row.classList.remove('d-none');
        } else {
            row.classList.add('d-none');
        }
    });
}

function jumpToFirstUnallocated() {
    const rows = document.querySelectorAll('.item-row');
    
    for (let row of rows) {
        const itemId = row.dataset.itemId;
        // Read the displayed total allocated value
        const totalAllocatedElement = document.getElementById(`total_${itemId}`);
        const totalAllocated = parseFloat(totalAllocatedElement.textContent || 0);
        
        if (totalAllocated === 0 && !row.classList.contains('d-none')) {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            row.classList.add('bg-warning-light');
            setTimeout(() => {
                row.classList.remove('bg-warning-light');
            }, 2000);
            return;
        }
    }
    
    alert('No unallocated items found.');
}

function validateAllAllocations() {
    let valid = true;
    const errors = [];
    
    // Validate individual allocations against available stock (usable - reserved)
    document.querySelectorAll('.allocation-input').forEach(input => {
        const itemId = input.dataset.itemId;
        const warehouseId = input.dataset.warehouseId;
        const allocated = parseFloat(input.value || 0);
        const stockElement = document.getElementById(`stock_${itemId}_${warehouseId}`);
        const usableQty = parseFloat(stockElement.dataset.usableQty || 0);
        const reservedQty = parseFloat(stockElement.dataset.reservedQty || 0);
        const availableQty = usableQty - reservedQty;
        
        if (allocated > availableQty) {
            valid = false;
            input.classList.add('border-danger', 'shadow-danger');
        } else {
            input.classList.remove('border-danger', 'shadow-danger');
        }
    });
    
    // Validate total allocations don't exceed requested
    document.querySelectorAll('.item-row').forEach(row => {
        const itemId = row.dataset.itemId;
        const requestedQty = parseFloat(row.querySelector('[data-requested-qty]').dataset.requestedQty);
        
        let totalAllocated = 0;
        document.querySelectorAll(`.allocation-input[data-item-id="${itemId}"]`).forEach(input => {
            totalAllocated += parseFloat(input.value || 0);
        });
        
        const totalElement = document.getElementById(`total_${itemId}`);
        if (totalAllocated > requestedQty) {
            valid = false;
            totalElement.classList.add('text-danger');
        } else {
            totalElement.classList.remove('text-danger');
        }
    });
    
    return valid;
}

function handleCancelPackage() {
    if (confirm('Cancel package preparation?\n\nThis will:\n• Delete all draft allocations\n• Release all inventory reservations\n\nThis action cannot be undone.')) {
        // Create and submit a form to POST to the cancel route
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = window.DMIS_CANCEL_URL || '/packaging/pending_approval';
        
        // Add CSRF token
        const csrfInput = document.createElement('input');
        csrfInput.type = 'hidden';
        csrfInput.name = 'csrf_token';
        csrfInput.value = getCSRFToken();
        form.appendChild(csrfInput);
        
        document.body.appendChild(form);
        form.submit();
    }
}
