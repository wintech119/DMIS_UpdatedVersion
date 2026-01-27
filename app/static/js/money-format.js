/**
 * Money Format Utilities - CSP-compliant currency formatting
 * Provides consistent money formatting across all cost fields
 * Format: $1,000.00 (currency symbol, thousand separators, 2 decimal places)
 */

(function() {
    'use strict';

    /**
     * Parse a money string to a numeric value
     * Handles formats like "$1,234.56", "1234.56", "1,234", etc.
     * @param {string} value - The value to parse
     * @returns {number|null} - The numeric value or null if invalid
     */
    function parseMoneyValue(value) {
        if (value === null || value === undefined || value === '') {
            return null;
        }
        
        var cleaned = String(value).replace(/[$,\s]/g, '').trim();
        
        if (cleaned === '' || cleaned === '-') {
            return null;
        }
        
        var num = parseFloat(cleaned);
        return isNaN(num) ? null : num;
    }

    /**
     * Format a number as money string
     * @param {number|string} value - The value to format
     * @param {boolean} includeSymbol - Whether to include $ symbol (default: true)
     * @returns {string} - Formatted money string like "$1,234.56"
     */
    function formatMoney(value, includeSymbol) {
        if (includeSymbol === undefined) {
            includeSymbol = true;
        }
        
        var num = parseMoneyValue(value);
        
        if (num === null) {
            return '';
        }
        
        var fixed = Math.abs(num).toFixed(2);
        var parts = fixed.split('.');
        var intPart = parts[0];
        var decPart = parts[1];
        
        var formatted = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        
        var result = formatted + '.' + decPart;
        
        if (num < 0) {
            result = '-' + result;
        }
        
        if (includeSymbol) {
            result = '$' + result;
        }
        
        return result;
    }

    /**
     * Get raw numeric value from a formatted money input
     * @param {HTMLInputElement} input - The input element
     * @returns {string} - Clean numeric string for form submission
     */
    function getRawValue(input) {
        var num = parseMoneyValue(input.value);
        return num !== null ? num.toFixed(2) : '';
    }

    /**
     * Initialize money formatting on an input field
     * @param {HTMLInputElement} input - The input element to format
     */
    function initMoneyInput(input) {
        if (!input || input.dataset.moneyInitialized) {
            return;
        }
        
        input.dataset.moneyInitialized = 'true';
        
        var hiddenInput = null;
        var inputName = input.name;
        
        if (inputName && !input.hasAttribute('readonly')) {
            hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.name = inputName;
            input.name = '';
            input.parentNode.insertBefore(hiddenInput, input.nextSibling);
            
            var initialValue = parseMoneyValue(input.value);
            if (initialValue !== null) {
                hiddenInput.value = initialValue.toFixed(2);
                input.value = formatMoney(initialValue);
            }
        } else if (input.value) {
            var val = parseMoneyValue(input.value);
            if (val !== null) {
                input.value = formatMoney(val);
            }
        }
        
        input.addEventListener('focus', function() {
            var num = parseMoneyValue(this.value);
            if (num !== null && num !== 0) {
                this.value = num.toFixed(2);
            } else {
                this.value = '';
            }
            this.select();
        });
        
        input.addEventListener('blur', function() {
            var num = parseMoneyValue(this.value);
            
            if (num !== null) {
                this.value = formatMoney(num);
                if (hiddenInput) {
                    hiddenInput.value = num.toFixed(2);
                }
            } else {
                this.value = '';
                if (hiddenInput) {
                    hiddenInput.value = '';
                }
            }
        });
        
        input.addEventListener('keydown', function(e) {
            var allowed = [
                'Backspace', 'Delete', 'Tab', 'Escape', 'Enter',
                'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown',
                'Home', 'End'
            ];
            
            if (allowed.indexOf(e.key) !== -1) {
                return;
            }
            
            if ((e.ctrlKey || e.metaKey) && ['a', 'c', 'v', 'x', 'z'].indexOf(e.key.toLowerCase()) !== -1) {
                return;
            }
            
            if (/^[0-9]$/.test(e.key)) {
                return;
            }
            
            if (e.key === '.' && this.value.indexOf('.') === -1) {
                return;
            }
            
            if (e.key === '-' && this.selectionStart === 0 && this.value.indexOf('-') === -1) {
                return;
            }
            
            e.preventDefault();
        });
    }

    /**
     * Initialize all money inputs on the page
     * Looks for inputs with data-money-format="true" or class "money-input"
     */
    function initAllMoneyInputs() {
        var selectors = [
            'input[data-money-format="true"]',
            'input.money-input',
            'input[name="tot_item_cost"]',
            'input[name="storage_cost"]',
            'input[name="haulage_cost"]',
            'input[name="other_cost"]',
            'input[name="item_cost"]',
            'input[name="unit_cost"]',
            'input#new_item_cost'
        ];
        
        var inputs = document.querySelectorAll(selectors.join(','));
        inputs.forEach(function(input) {
            initMoneyInput(input);
        });
    }

    /**
     * Update a readonly money display field
     * @param {HTMLInputElement} input - The readonly input to update
     * @param {number} value - The numeric value to display
     */
    function updateMoneyDisplay(input, value) {
        if (!input) return;
        var num = parseFloat(value);
        if (!isNaN(num)) {
            input.value = formatMoney(num);
        } else {
            input.value = formatMoney(0);
        }
    }

    document.addEventListener('DOMContentLoaded', initAllMoneyInputs);

    window.DRIMS = window.DRIMS || {};
    window.DRIMS.money = {
        format: formatMoney,
        parse: parseMoneyValue,
        getRaw: getRawValue,
        init: initMoneyInput,
        initAll: initAllMoneyInputs,
        updateDisplay: updateMoneyDisplay
    };

})();
