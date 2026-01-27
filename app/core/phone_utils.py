"""
Phone Number Utilities for DRIMS

Enforces consistent phone number format across the entire application:
+1 (XXX) XXX-XXXX

All phone_no fields must follow this exact format for:
- Warehouses
- Agencies
- Custodians
- Donors
- Relief Requests
- User Management
- Any other phone number fields
"""
import re

# Phone number format regex: +1 (XXX) XXX-XXXX
PHONE_REGEX = r'^\+1 \(\d{3}\) \d{3}-\d{4}$'
PHONE_FORMAT_EXAMPLE = '+1 (XXX) XXX-XXXX'
PHONE_FORMAT_ERROR = f'Phone number must follow the format {PHONE_FORMAT_EXAMPLE}.'


def validate_phone_format(phone_no):
    """
    Validate that phone number matches the required format: +1 (XXX) XXX-XXXX
    
    Args:
        phone_no (str): Phone number to validate
    
    Returns:
        bool: True if valid, False otherwise
    """
    if not phone_no:
        return False
    return re.match(PHONE_REGEX, phone_no.strip()) is not None


def normalize_phone_number(phone_no):
    """
    Convert various phone number formats to standard: +1 (XXX) XXX-XXXX
    
    Handles formats like:
    - 8765551234 -> +1 (876) 555-1234
    - (876)-555-1234 -> +1 (876) 555-1234
    - 876 555 1234 -> +1 (876) 555-1234
    - +1 876 555 1234 -> +1 (876) 555-1234
    - +18765551234 -> +1 (876) 555-1234
    
    Args:
        phone_no (str): Phone number in any format
    
    Returns:
        str or None: Normalized phone number or None if cannot be parsed
    """
    if not phone_no:
        return None
    
    # Strip all non-digit characters except leading +
    cleaned = phone_no.strip()
    
    # Extract all digits
    digits = re.sub(r'\D', '', cleaned)
    
    # If starts with +1, remove the 1
    if cleaned.startswith('+1'):
        digits = digits[1:] if len(digits) > 10 else digits
    elif cleaned.startswith('1') and len(digits) == 11:
        # Remove leading 1 if 11 digits (assume it's country code)
        digits = digits[1:]
    
    # Must have exactly 10 digits (area code + 7-digit number)
    if len(digits) != 10:
        return None
    
    # Format as +1 (XXX) XXX-XXXX
    area_code = digits[0:3]
    prefix = digits[3:6]
    line_number = digits[6:10]
    
    return f'+1 ({area_code}) {prefix}-{line_number}'


def get_phone_validation_error(field_name='Phone number'):
    """
    Get standardized phone number validation error message
    
    Args:
        field_name (str): Name of the field for error message
    
    Returns:
        str: Formatted error message
    """
    return f'{field_name} must follow the format {PHONE_FORMAT_EXAMPLE}.'
