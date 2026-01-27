document.addEventListener('DOMContentLoaded', function() {
    function recalculateUsableQty(itemId) {
        var defectiveInput = document.getElementById('defective_qty_' + itemId);
        var expiredInput = document.getElementById('expired_qty_' + itemId);
        var usableInput = document.getElementById('usable_qty_' + itemId);
        var errorDiv = document.querySelector('.qty-error-' + itemId);
        var errorText = document.querySelector('.qty-error-text-' + itemId);
        
        if (!defectiveInput || !expiredInput || !usableInput) {
            console.error('Could not find input elements for item ' + itemId);
            return;
        }
        
        var intakeTotal = parseFloat(defectiveInput.getAttribute('data-intake-total')) || 0;
        var defective = parseFloat(defectiveInput.value) || 0;
        var expired = parseFloat(expiredInput.value) || 0;
        var usable = intakeTotal - defective - expired;
        
        usableInput.value = usable.toFixed(2);
        
        if (errorDiv && errorText) {
            if (defective + expired > intakeTotal) {
                errorDiv.classList.remove('d-none');
                errorText.textContent = 'Defective + Expired cannot exceed intake quantity (' + intakeTotal.toFixed(2) + ')';
                usableInput.classList.add('is-invalid');
            } else if (usable < 0) {
                errorDiv.classList.remove('d-none');
                errorText.textContent = 'Usable quantity cannot be negative';
                usableInput.classList.add('is-invalid');
            } else {
                errorDiv.classList.add('d-none');
                usableInput.classList.remove('is-invalid');
            }
        }
    }
    
    var qtyAdjustInputs = document.querySelectorAll('.qty-adjust');
    
    qtyAdjustInputs.forEach(function(input) {
        input.addEventListener('input', function(e) {
            var itemId = e.target.getAttribute('data-item-id');
            if (itemId) {
                recalculateUsableQty(itemId);
            }
        });
        
        input.addEventListener('change', function(e) {
            var itemId = e.target.getAttribute('data-item-id');
            if (itemId) {
                recalculateUsableQty(itemId);
            }
        });
        
        input.addEventListener('keyup', function(e) {
            var itemId = e.target.getAttribute('data-item-id');
            if (itemId) {
                recalculateUsableQty(itemId);
            }
        });
    });
    
    var verifyForm = document.getElementById('verifyForm');
    if (verifyForm) {
        verifyForm.addEventListener('submit', function(e) {
            var hasErrors = false;
            
            var errorDivs = document.querySelectorAll('.invalid-feedback[class*="qty-error-"]');
            errorDivs.forEach(function(el) {
                if (!el.classList.contains('d-none')) {
                    hasErrors = true;
                }
            });
            
            var usableInputs = document.querySelectorAll('input[id^="usable_qty_"]');
            usableInputs.forEach(function(input) {
                var usable = parseFloat(input.value) || 0;
                if (usable < 0) {
                    hasErrors = true;
                }
            });
            
            if (hasErrors) {
                e.preventDefault();
                alert('Please correct the quantity errors before verifying.');
            }
        });
    }
});
