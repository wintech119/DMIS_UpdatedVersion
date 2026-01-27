/**
 * Phone Number Masked Input for DRIMS
 * 
 * Enforces consistent phone number format: +1 (XXX) XXX-XXXX
 * 
 * Usage:
 * 1. Add this script to your template:
 *    <script src="{{ url_for('static', filename='js/phone-mask.js') }}"></script>
 * 
 * 2. Add class 'phone-mask' to your phone input:
 *    <input type="tel" class="form-control phone-mask" name="phone_no" ...>
 * 
 * Features:
 * - Automatic formatting as user types
 * - +1 prefix cannot be deleted
 * - Auto-inserts parentheses, space, and dash
 * - Works with numeric keypad on mobile
 * - Validates 10-digit phone numbers
 */

(function() {
    'use strict';
    
    /**
     * Format phone number to +1 (XXX) XXX-XXXX
     */
    function formatPhoneNumber(value) {
        // Remove all non-digit characters
        const digits = value.replace(/\D/g, '');
        
        // Take only first 10 digits
        const limitedDigits = digits.substring(0, 10);
        
        // Format based on number of digits
        let formatted = '+1 ';
        
        if (limitedDigits.length > 0) {
            formatted += '(';
            formatted += limitedDigits.substring(0, 3);
            
            if (limitedDigits.length >= 3) {
                formatted += ') ';
                formatted += limitedDigits.substring(3, 6);
                
                if (limitedDigits.length >= 6) {
                    formatted += '-';
                    formatted += limitedDigits.substring(6, 10);
                }
            }
        }
        
        return formatted;
    }
    
    /**
     * Initialize phone mask on an input element
     */
    function initPhoneMask(input) {
        // Set initial value if exists
        if (input.value && !input.value.startsWith('+1')) {
            const digits = input.value.replace(/\D/g, '');
            if (digits.length > 0) {
                input.value = formatPhoneNumber(digits);
            } else {
                input.value = '+1 (';
            }
        } else if (!input.value) {
            input.value = '+1 (';
        }
        
        // Set input type to tel for mobile numeric keypad
        input.setAttribute('type', 'tel');
        
        // Set placeholder
        input.setAttribute('placeholder', '+1 (___) ___-____');
        
        // Handle input event
        input.addEventListener('input', function(e) {
            const cursorPosition = this.selectionStart;
            const oldValue = this.value;
            const oldLength = oldValue.length;
            
            // Get only digits
            let digits = this.value.replace(/\D/g, '');
            
            // Remove the country code "1" if it's at the beginning
            // This prevents the "1" from "+1" being counted as a user digit
            if (digits.startsWith('1') && digits.length > 1) {
                digits = digits.substring(1);
            } else if (digits === '1') {
                digits = '';
            }
            
            // Format the number
            const newValue = formatPhoneNumber(digits);
            
            // Update value
            this.value = newValue;
            
            // Restore cursor position (adjust for added characters)
            const newLength = newValue.length;
            const diff = newLength - oldLength;
            let newCursorPosition = cursorPosition + diff;
            
            // Don't let cursor go before +1 (
            if (newCursorPosition < 4) {
                newCursorPosition = 4;
            }
            
            // Set cursor position
            this.setSelectionRange(newCursorPosition, newCursorPosition);
        });
        
        // Handle keydown event (prevent deleting +1 prefix)
        input.addEventListener('keydown', function(e) {
            const cursorPosition = this.selectionStart;
            
            // Prevent deleting +1 prefix
            if ((e.key === 'Backspace' || e.key === 'Delete') && cursorPosition <= 4) {
                e.preventDefault();
                return false;
            }
        });
        
        // Handle focus event
        input.addEventListener('focus', function(e) {
            // If empty or just +1, set to +1 (
            if (!this.value || this.value === '+1') {
                this.value = '+1 (';
            }
            
            // Move cursor to end if at beginning
            if (this.selectionStart < 4) {
                const length = this.value.length;
                this.setSelectionRange(length, length);
            }
        });
        
        // Handle blur event - validate complete number
        input.addEventListener('blur', function(e) {
            const digits = this.value.replace(/\D/g, '');
            
            // If no digits entered, clear the field
            if (digits.length === 0) {
                this.value = '';
                return;
            }
            
            // If incomplete number, show validation message
            if (digits.length < 10) {
                this.setCustomValidity('Phone number must have 10 digits.');
                // Optionally trigger validation UI
                if (this.reportValidity) {
                    this.reportValidity();
                }
            } else {
                this.setCustomValidity('');
            }
        });
        
        // Handle paste event
        input.addEventListener('paste', function(e) {
            e.preventDefault();
            
            // Get pasted data
            const pastedData = (e.clipboardData || window.clipboardData).getData('text');
            
            // Extract digits
            const digits = pastedData.replace(/\D/g, '');
            
            // Format and set value
            if (digits.length > 0) {
                this.value = formatPhoneNumber(digits);
            }
        });
    }
    
    /**
     * Validate phone number format
     */
    function validatePhoneNumber(phoneNumber) {
        const regex = /^\+1 \(\d{3}\) \d{3}-\d{4}$/;
        return regex.test(phoneNumber);
    }
    
    /**
     * Initialize all phone mask inputs on page load
     */
    function initAllPhoneMasks() {
        const phoneInputs = document.querySelectorAll('.phone-mask, input[name="phone_no"], input[name="phone"]');
        phoneInputs.forEach(function(input) {
            initPhoneMask(input);
        });
    }
    
    // Auto-initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAllPhoneMasks);
    } else {
        initAllPhoneMasks();
    }
    
    // Export functions for manual initialization
    window.DRIMS = window.DRIMS || {};
    window.DRIMS.initPhoneMask = initPhoneMask;
    window.DRIMS.validatePhoneNumber = validatePhoneNumber;
    window.DRIMS.formatPhoneNumber = formatPhoneNumber;
    
})();
