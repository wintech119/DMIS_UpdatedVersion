"""
Safe path handling utilities to prevent directory traversal attacks.

This module provides functions to ensure file operations stay within
designated base directories, preventing OS access violations.
"""

import os
import re
from typing import Optional


def safe_join(base: str, *paths: str) -> str:
    """
    Safely join paths, preventing directory traversal attacks.
    
    This function preserves the original filename if it's already safe,
    only applying sanitization when necessary to prevent traversal.
    
    Args:
        base: The base directory that all paths must stay within
        *paths: Path components to join to the base
        
    Returns:
        The absolute path that is guaranteed to be within base
        
    Raises:
        ValueError: If the resulting path would escape the base directory
    """
    if not base:
        raise ValueError("Base directory cannot be empty")
    
    abs_base = os.path.abspath(base)
    
    cleaned_paths = []
    for path in paths:
        if path:
            basename = os.path.basename(str(path))
            if not basename or '..' in basename or basename.startswith('/'):
                raise ValueError(f"Invalid filename: {path}")
            if '\x00' in basename:
                raise ValueError("Null byte in filename")
            cleaned_paths.append(basename)
    
    if not cleaned_paths:
        raise ValueError("No valid path components provided")
    
    final_path = os.path.abspath(os.path.join(abs_base, *cleaned_paths))
    
    if not final_path.startswith(abs_base + os.sep) and final_path != abs_base:
        raise ValueError("Attempted directory traversal detected")
    
    return final_path


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to remove potentially dangerous characters.
    
    Args:
        filename: The filename to sanitize
        
    Returns:
        A safe filename with only allowed characters
    """
    if not filename:
        return ""
    
    filename = os.path.basename(str(filename))
    
    filename = filename.replace('\x00', '')
    
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    filename = re.sub(r'\.\.+', '.', filename)
    
    while filename.startswith('.'):
        filename = filename[1:]
    
    filename = filename.strip()
    
    max_length = 255
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[:max_length - len(ext)] + ext
    
    return filename


def is_safe_path(base: str, path: str) -> bool:
    """
    Check if a path is safely within a base directory.
    
    Args:
        base: The base directory
        path: The path to check
        
    Returns:
        True if path is within base, False otherwise
    """
    try:
        abs_base = os.path.abspath(base)
        abs_path = os.path.abspath(path)
        return abs_path.startswith(abs_base + os.sep) or abs_path == abs_base
    except (TypeError, ValueError):
        return False


def validate_upload_path(upload_folder: str, filename: str) -> Optional[str]:
    """
    Validate and return a safe path for file uploads.
    
    Args:
        upload_folder: The configured upload directory
        filename: The user-provided filename
        
    Returns:
        A safe absolute file path, or None if validation fails
    """
    if not upload_folder or not filename:
        return None
    
    try:
        return safe_join(upload_folder, filename)
    except ValueError:
        return None


def ensure_directory_exists(path: str, base: str) -> bool:
    """
    Safely create a directory if it doesn't exist, ensuring it's within base.
    
    Args:
        path: The directory path to create
        base: The base directory that path must be within
        
    Returns:
        True if directory exists or was created, False if unsafe
    """
    try:
        if not is_safe_path(base, path):
            return False
        
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        return True
    except (OSError, ValueError):
        return False
