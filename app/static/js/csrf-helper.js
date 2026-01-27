/**
 * CSRF Protection Helper for AJAX Requests
 * Automatically includes CSRF token in all state-changing requests
 */

function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

function csrfFetch(url, options = {}) {
    const csrfToken = getCSRFToken();
    
    // Add CSRF token to headers for POST, PUT, PATCH, DELETE methods
    const method = (options.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        options.headers = options.headers || {};
        options.headers['X-CSRFToken'] = csrfToken;
    }
    
    return fetch(url, options);
}

// Export for use in other scripts
window.csrfFetch = csrfFetch;
window.getCSRFToken = getCSRFToken;
