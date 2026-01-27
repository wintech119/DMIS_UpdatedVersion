/**
 * Form Utilities - CSP-compliant event handlers
 * Common patterns for auto-submit, confirmations, print, etc.
 */

document.addEventListener('DOMContentLoaded', function() {
    
    // Auto-submit forms when select changes
    const autoSubmitSelects = document.querySelectorAll('select[data-auto-submit="true"]');
    autoSubmitSelects.forEach(function(select) {
        select.addEventListener('change', function() {
            this.form.submit();
        });
    });
    
    // Print buttons
    const printButtons = document.querySelectorAll('[data-action="print"]');
    printButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            window.print();
        });
    });
    
    // Go back buttons
    document.addEventListener('click', function(e) {
        const backBtn = e.target.closest('[data-action="go-back"]');
        if (backBtn) {
            history.back();
        }
    });
    
    // Close alert banners
    document.addEventListener('click', function(e) {
        const closeBtn = e.target.closest('[data-action="close-alert"]');
        if (closeBtn) {
            const alert = closeBtn.closest('.alert-banner, .alert');
            if (alert) {
                alert.remove();
            }
        }
    });
    
    // Stop propagation for nested clickable elements
    document.addEventListener('click', function(e) {
        const stopPropBtn = e.target.closest('[data-action="stop-propagation"]');
        if (stopPropBtn) {
            e.stopPropagation();
        }
    });
    
    // Clickable table rows with data-href attribute
    document.addEventListener('click', function(e) {
        const row = e.target.closest('tr[data-href]');
        if (row && !e.target.closest('[data-action="stop-propagation"]')) {
            const href = row.dataset.href;
            if (href) {
                window.location = href;
            }
        }
    });
    
    // Confirmation dialogs for forms
    const confirmForms = document.querySelectorAll('form[data-confirm]');
    confirmForms.forEach(function(form) {
        form.addEventListener('submit', function(e) {
            const message = this.dataset.confirm;
            if (!confirm(message)) {
                e.preventDefault();
                return false;
            }
        });
    });
    
    // Confirmation dialogs for buttons
    const confirmButtons = document.querySelectorAll('[data-confirm]');
    confirmButtons.forEach(function(btn) {
        // Skip forms (handled above)
        if (btn.tagName === 'FORM') return;
        
        btn.addEventListener('click', function(e) {
            const message = this.dataset.confirm;
            if (!confirm(message)) {
                e.preventDefault();
                return false;
            }
        });
    });
    
    // Navigate on select change (for period selectors, filters, etc.)
    document.addEventListener('change', function(e) {
        const target = e.target;
        if (target.dataset.action === 'navigate' && target.dataset.param) {
            const paramName = target.dataset.param;
            const paramValue = target.value;
            window.location.href = '?' + paramName + '=' + paramValue;
        }
    });
    
    // Toggle reason field visibility based on status selection (warehouses, agencies, etc.)
    document.addEventListener('change', function(e) {
        const select = e.target.closest('select[data-action="toggle-reason-field"]');
        if (select) {
            const reasonContainer = document.getElementById('reason_container');
            if (reasonContainer) {
                if (select.value === 'I') {
                    reasonContainer.classList.remove('d-none');
                } else {
                    reasonContainer.classList.add('d-none');
                }
            }
        }
    });
    
    // Show donation details when donation is selected
    document.addEventListener('change', function(e) {
        const select = e.target.closest('select[data-action="show-donation-details"]');
        if (select && select.value) {
            const option = select.options[select.selectedIndex];
            const detailsDiv = document.getElementById('donation-details');
            if (detailsDiv && option) {
                // Show the details div
                detailsDiv.classList.remove('d-none');
                
                // Populate details from data attributes
                const detailDonor = document.getElementById('detail-donor');
                const detailDate = document.getElementById('detail-date');
                const detailDesc = document.getElementById('detail-desc');
                const detailItems = document.getElementById('detail-items');
                
                if (detailDonor) detailDonor.textContent = option.dataset.donor || '';
                if (detailDate) detailDate.textContent = option.dataset.date || '';
                if (detailDesc) detailDesc.textContent = option.dataset.desc || '';
                
                if (detailItems && option.dataset.items) {
                    const items = option.dataset.items.split('|');
                    detailItems.innerHTML = items.map(item => 
                        '<span class="badge bg-light text-dark border">' + item + '</span>'
                    ).join('');
                }
            }
        } else {
            // Hide details if no selection
            const detailsDiv = document.getElementById('donation-details');
            if (detailsDiv) {
                detailsDiv.classList.add('d-none');
            }
        }
    });
    
    // User deactivation confirmation modal handler
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('[data-action="confirm-deactivate-user"]');
        if (btn) {
            const modal = btn.closest('.modal');
            if (modal) {
                const form = modal.previousElementSibling;
                if (form && form.id === 'deactivateForm') {
                    form.submit();
                }
            }
        }
    });
    
    // User activation confirmation modal handler
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('[data-action="confirm-activate-user"]');
        if (btn) {
            const modal = btn.closest('.modal');
            if (modal) {
                const form = modal.previousElementSibling;
                if (form && form.id === 'activateForm') {
                    form.submit();
                }
            }
        }
    });
});
