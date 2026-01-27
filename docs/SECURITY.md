# DMIS Security Guide

This document describes how to run security scans on the DMIS (Disaster Management Information System) codebase and outlines the security controls implemented in the application.

## Table of Contents

- [Security Scanning Tools](#security-scanning-tools)
- [How to Run Security Scans Locally](#how-to-run-security-scans-locally)
- [CI/CD Integration](#cicd-integration)
- [Security Controls](#security-controls)
- [Reporting Security Issues](#reporting-security-issues)

---

## Security Scanning Tools

DMIS uses the following security scanning tools:

### Code Analysis (SAST)

| Tool | Purpose | Configuration |
|------|---------|---------------|
| **Bandit** | Python security linter | `bandit.yml` |
| **Semgrep** | Multi-language SAST scanner | `semgrep.yml` |

### Dependency Scanning

| Tool | Purpose | Configuration |
|------|---------|---------------|
| **pip-audit** | Python package vulnerability scanner | Uses PyPI advisory database |
| **safety** | Python dependency checker | Uses Safety DB |

### What They Detect

- **SQL Injection** - String formatting in SQL queries
- **Command Injection** - Unsafe subprocess/os.system calls
- **Cross-Site Scripting (XSS)** - Unescaped user input in templates
- **Code Injection** - Dangerous eval/exec usage
- **Weak Cryptography** - MD5/SHA1 for security purposes
- **Hardcoded Secrets** - Passwords and API keys in code
- **Path Traversal** - Unvalidated file paths
- **Open Redirect** - Unvalidated redirect URLs
- **SSRF** - Unvalidated outbound requests
- **Vulnerable Dependencies** - Known CVEs in third-party packages

---

## Vulnerability Management Policy

### Critical/High Severity Vulnerabilities

**Policy:** Must be remediated or justified before any release.

- All Critical and High severity findings must be resolved before code can be merged to protected branches
- If a vulnerability cannot be fixed immediately (e.g., no patch available), a documented risk exception is required
- Risk exceptions must include: vulnerability details, affected component, mitigation measures, and remediation timeline

### Medium/Low Severity Vulnerabilities

**Policy:** May be accepted temporarily with documented risk exception.

- Should be prioritized in upcoming sprints
- Track in the project's issue tracker with security label
- Review quarterly to ensure remediation progress

### Dependency Vulnerabilities

**Policy:** No deployment with known Critical/High CVEs in dependencies.

- Update vulnerable packages to patched versions when available
- If no patch exists, evaluate alternative packages or implement compensating controls
- Document any temporary exceptions with a clear remediation plan

**Note on Conservative Classification:**

The dependency scanner uses a conservative approach to severity classification:
- Vulnerabilities with explicit CVSS scores are classified accurately
- Vulnerabilities without parseable severity data default to **HIGH**
- This ensures no Critical/High CVE slips through the gate

If you believe a vulnerability is incorrectly classified as HIGH when it should be MEDIUM/LOW:
1. Review the original advisory for explicit severity information
2. If confirmed as lower severity, document and proceed with a risk exception
3. Consider contributing severity data back to the upstream vulnerability database

---

## How to Run Security Scans Locally

### Prerequisites

Install the scanning tools:

```bash
pip install bandit semgrep
```

### Quick Scan (Recommended)

Run the automated security scripts:

```bash
# Make scripts executable (first time only)
chmod +x scripts/run_sast.sh scripts/run_dep_scan.sh

# Run SAST code analysis
./scripts/run_sast.sh

# Run dependency vulnerability scan
./scripts/run_dep_scan.sh

# Quick mode (high severity only)
./scripts/run_sast.sh --quick

# Generate reports
./scripts/run_sast.sh --report
./scripts/run_dep_scan.sh --report
```

### Dependency Scanning

```bash
# Install scanning tools
pip install pip-audit safety

# Run automated dependency scan
./scripts/run_dep_scan.sh

# Scan installed environment
./scripts/run_dep_scan.sh --env

# Generate JSON reports
./scripts/run_dep_scan.sh --report
```

### Manual pip-audit

```bash
# Scan requirements.txt
pip-audit -r requirements.txt

# Scan installed packages
pip-audit

# JSON output
pip-audit -r requirements.txt --format json -o pip-audit-report.json
```

### Manual safety Check

```bash
# Scan requirements.txt
safety check -r requirements.txt

# Scan installed packages
safety check

# JSON output
safety check -r requirements.txt --output json > safety-report.json
```

### Manual Bandit Scan

```bash
# Full scan with configuration
bandit -r app/ drims_app.py -c bandit.yml

# High severity only
bandit -r app/ drims_app.py -c bandit.yml -ll

# Generate JSON report
bandit -r app/ drims_app.py -c bandit.yml -f json -o bandit-report.json

# Generate HTML report
bandit -r app/ drims_app.py -c bandit.yml -f html -o bandit-report.html
```

### Manual Semgrep Scan

```bash
# Scan with custom rules
semgrep --config semgrep.yml app/ drims_app.py

# Include community rules
semgrep --config semgrep.yml --config p/python --config p/flask app/ drims_app.py

# OWASP Top 10 rules
semgrep --config p/owasp-top-ten app/ drims_app.py

# Generate JSON report
semgrep --config semgrep.yml --json -o semgrep-report.json app/ drims_app.py

# Errors only
semgrep --config semgrep.yml --severity ERROR app/ drims_app.py
```

### Understanding Results

| Severity | Action Required |
|----------|-----------------|
| **HIGH/ERROR** | Must fix before deployment |
| **MEDIUM/WARNING** | Should fix, review for false positives |
| **LOW/INFO** | Review and fix if applicable |

---

## CI/CD Integration

### GitHub Actions

The `.github/workflows/security-sast.yml` workflow automatically runs on:

- Push to `main`, `master`, or `develop` branches
- Pull requests to protected branches
- Manual workflow dispatch

**Workflow Jobs:**

| Job | Purpose | Exit Behavior |
|-----|---------|---------------|
| `sast-scan` | Code analysis (Bandit, Semgrep) | Fails on Critical/High code issues |
| `dependency-scan` | Package vulnerabilities (pip-audit, safety) | Fails on Critical/High CVEs |
| `security-gate` | Final check | Fails if any scan failed |

**Workflow Behavior:**
- **FAIL** if Critical/High severity issues are detected (code or dependencies)
- **PASS** with warnings for Medium/Low issues
- Results are uploaded to GitHub Security tab (SARIF format)
- Artifacts available for download

### Running Locally Before Push

Always run both scans before pushing:

```bash
# Code analysis
./scripts/run_sast.sh

# Dependency vulnerabilities
./scripts/run_dep_scan.sh
```

If either scan fails (exit code 1), fix the issues before pushing.

---

## Security Controls

DMIS implements the following security controls:

### Application Security

| Control | Implementation |
|---------|----------------|
| CSRF Protection | Flask-WTF with token validation |
| XSS Prevention | Jinja2 auto-escaping, CSP headers |
| SQL Injection | SQLAlchemy ORM, parameterized queries |
| Authentication | Flask-Login with password hashing |
| Authorization | Role-Based Access Control (RBAC) |
| Session Security | Secure cookies (HttpOnly, SameSite) |

### Input Validation

| Control | Implementation |
|---------|----------------|
| Parameter Validation | `app/security/param_validation.py` |
| Query String Protection | `app/security/query_string_protection.py` |
| Path Traversal Prevention | `app/security/safe_path.py` |
| URL Safety | `app/security/url_safety.py` |

### Output Encoding

| Control | Implementation |
|---------|----------------|
| Error Messages | Generic user messages, server-side logging |
| Log Forging Prevention | `app/security/log_sanitizer.py` |
| Template Security | All paths hardcoded, SRI for CDN assets |

### HTTP Security Headers

| Header | Value |
|--------|-------|
| Content-Security-Policy | Nonce-based script/style policies |
| X-Content-Type-Options | nosniff |
| X-Frame-Options | SAMEORIGIN |
| Strict-Transport-Security | max-age=31536000; includeSubDomains |

---

## Configuration Hardening

### Environment Variables

DMIS uses environment variables for all sensitive configuration. Variables support the `DMIS_` prefix with fallback to legacy names for backward compatibility.

| Variable | Purpose | Default |
|----------|---------|---------|
| `DMIS_SECRET_KEY` | Flask session encryption key | Required in production |
| `DMIS_DATABASE_URL` | PostgreSQL connection string | Required |
| `DMIS_DEBUG` | Enable debug mode | `false` |
| `DMIS_TESTING` | Enable testing mode | `false` |
| `DMIS_UPLOAD_FOLDER` | File upload directory | `./uploads/donations` |
| `DMIS_LOG_TO_STDOUT` | Log to stdout instead of file | `false` |

**Security Notes:**
- `DMIS_DEBUG` defaults to `false` - production-safe by default
- `DMIS_SECRET_KEY` is required in production (error if missing)
- Never commit `.env` files with real credentials
- See `.env.example` for a complete template

### Secrets Management

1. **Local Development**: Use `.env` file (not committed to version control)
2. **Replit**: Use the Secrets tab in the Replit interface
3. **Production**: Use environment variables or secrets manager

Files excluded from version control (`.gitignore`):
- `.env`, `.env.*` (except `.env.example`)
- `*.pem`, `*.key`
- `secrets/`, `credentials/`
- `config.local.py`, `settings.local.py`

### Production Deployment

For production deployment behind NGINX:

1. Use the template at `deploy/nginx.conf.example`
2. Configure TLS with Let's Encrypt certificates
3. Enable HSTS (1 year max-age with includeSubDomains)
4. Run DMIS via Gunicorn (not Flask dev server):
   ```bash
   gunicorn --bind 127.0.0.1:8000 --workers 4 wsgi:app
   ```

See `deploy/nginx.conf.example` for complete NGINX configuration including:
- TLS 1.2+ with modern cipher suites
- Proxy headers (X-Forwarded-For, X-Forwarded-Proto)
- Rate limiting configuration
- Static file serving
- Security header additions (complementing app headers)

---

## API Security (OWASP API Top 10)

DMIS implements the following API security controls based on the OWASP API Security Top 10:

### Rate Limiting (API4:2023 - Unrestricted Resource Consumption)

| Endpoint Category | Limit | Implementation |
|-------------------|-------|----------------|
| Login | 5 requests/minute | Brute-force protection |
| Exports (CSV, PDF) | 3 requests/hour | Prevents resource abuse |
| Reports | 10 requests/minute | Balances usability and protection |
| Analytics Dashboards | 10 requests/minute | Expensive query protection |
| Bulk Operations | 5 requests/minute | Notification clear-all, etc. |
| Public Endpoints | 5 requests/minute | Account request submissions |

**Configuration:**
- Module: `app/security/rate_limiting.py`
- Backend: In-memory storage (Redis recommended for production multi-instance)
- Key Function: User ID for authenticated users, IP address for anonymous

**Rate Limit Headers:**
```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 9
X-RateLimit-Reset: 1234567890
Retry-After: 60
```

### CORS Configuration (API7:2023 - Security Misconfiguration)

| Setting | Value | Purpose |
|---------|-------|---------|
| Allowed Origins | ODPEM/JAMICTA subdomains | Domain allowlist |
| Credentials | Enabled for allowed origins only | Cookie/session support |
| Allowed Methods | GET, POST, PUT, DELETE | Standard REST methods |
| Max Age | 600 seconds | Preflight caching |

**Configuration:**
- Module: `app/security/cors_config.py`
- Pattern: `*.odpem.gov.jm`, `*.jamicta.gov.jm`
- No wildcards for credential-bearing requests

### External API Consumption (API10:2023 - Unsafe Consumption of APIs)

The `SafeApiClient` utility provides secure external API consumption:

| Protection | Implementation |
|------------|----------------|
| Domain Allowlist | Currency API domains only |
| Timeouts | 10s connect, 30s read |
| Retry Logic | Exponential backoff (3 attempts) |
| Response Validation | Content-Type, size limits |
| Response Sanitization | Control character removal |

**Usage:**
```python
from app.security.safe_api_client import SafeApiClient

client = SafeApiClient()
response = client.get('https://api.exchangerate.com/v1/rates')
```

### Additional API Protections

| OWASP Risk | Control | Implementation |
|------------|---------|----------------|
| API1 - BOLA | Authorization checks | `@role_required` decorator, user_id verification |
| API2 - Auth | Flask-Login session | Secure cookies, session timeout |
| API3 - Property Access | Output filtering | Response models, no internal fields exposed |
| API5 - Function Auth | RBAC | Role hierarchy, feature registry |
| API6 - Mass Assignment | WTForms validation | Explicit field whitelists |
| API8 - Security Misconfiguration | CSP, HSTS | Strict security headers |
| API9 - Inventory Management | Rate limiting | All endpoints protected |

---

## Monitoring and SIEM Integration

This section describes what logs should be ingested by a SIEM and what alerts should be configured.

### Audit Logging (NIST 800-53 AU Controls)

DMIS implements structured audit logging aligned with NIST 800-53 audit controls:

| Control | Implementation |
|---------|----------------|
| AU-2 (Audit Events) | Key security events logged via `app/security/audit_logger.py` |
| AU-3 (Content of Audit Records) | Timestamp, user ID, action, target entity, outcome, IP address |
| AU-8 (Time Stamps) | Jamaica timezone (UTC-05:00) for all timestamps |
| AU-12 (Audit Generation) | Automated logging at authentication, authorization, and data access points |

### Log Sources for SIEM Ingestion

Configure SIEM to ingest the following log sources:

| Source | Location | Content |
|--------|----------|---------|
| **DMIS Application Logs** | stdout/stderr or configured log file | Security events, errors, access logs |
| **DMIS Audit Logs** | `dmis.audit` logger | Structured security/audit events |
| **DMIS Security Logs** | `dmis.security` logger | Security-specific events |
| **NGINX Access Logs** | `/var/log/nginx/access.log` | HTTP requests, response codes |
| **NGINX Error Logs** | `/var/log/nginx/error.log` | Server errors, upstream issues |
| **PostgreSQL Logs** | Configured pg_log location | Database queries, errors |

### Recommended Alert Rules

Configure the following alerts in your SIEM:

#### Critical Alerts (Immediate Response)

| Alert | Condition | Threshold |
|-------|-----------|-----------|
| **Brute Force Attack** | LOGIN_FAILURE events from same IP | > 10 in 5 minutes |
| **Account Takeover Attempt** | LOGIN_FAILURE followed by LOGIN_SUCCESS | Correlation rule |
| **Privilege Escalation** | ROLE_ASSIGN to admin role by non-admin | Any occurrence |
| **Mass Data Export** | Multiple EXPORT actions | > 5 in 1 hour |

#### High Priority Alerts

| Alert | Condition | Threshold |
|-------|-----------|-----------|
| **Repeated Access Denied** | ACCESS_DENIED events | > 20 in 10 minutes |
| **Unusual Login Time** | LOGIN_SUCCESS outside business hours | Custom schedule |
| **Multiple Failed Logins** | LOGIN_FAILURE for single user | > 5 in 15 minutes |
| **Rate Limit Exceeded** | RATE_LIMIT_EXCEEDED events | > 50 in 10 minutes |

#### Medium Priority Alerts

| Alert | Condition | Threshold |
|-------|-----------|-----------|
| **Unusual Volume - Donations** | CREATE action on donations | > 50 in 1 hour |
| **Unusual Volume - Dispatches** | DISPATCH actions | > 20 in 1 hour |
| **Session Anomaly** | Multiple active sessions per user | > 3 concurrent |
| **CSRF Violation** | CSRF_VIOLATION events | Any occurrence |

### Log Format

Audit logs use structured format for easy parsing:

```
timestamp=<ISO8601> category=<CATEGORY> action=<ACTION> user_id=<ID> target=<entity:id> outcome=<OUTCOME> ip=<IP> details=<dict>
```

**Example:**
```
timestamp=2025-12-02T14:30:45-05:00 category=AUTHENTICATION action=LOGIN_SUCCESS user_id=123 outcome=SUCCESS ip=192.168.1.100 details={email=jo***@odpem.gov.jm}
```

### Event Categories

| Category | Events |
|----------|--------|
| AUTHENTICATION | LOGIN_SUCCESS, LOGIN_FAILURE, LOGIN_LOCKED, LOGIN_INACTIVE, LOGOUT |
| AUTHORIZATION | ACCESS_GRANTED, ACCESS_DENIED, ROLE_REQUIRED |
| USER_MGMT | USER_CREATE, USER_UPDATE, USER_DELETE, ROLE_ASSIGN, PASSWORD_CHANGE |
| DATA_ACCESS | CREATE, READ, UPDATE, DELETE, EXPORT, DISPATCH, APPROVE, VERIFY |
| SECURITY | RATE_LIMIT_EXCEEDED, CSRF_VIOLATION, INVALID_INPUT, SECURITY_ALERT |

### Infrastructure Notes

- SIEM configuration is performed on the infrastructure side
- These are recommendations for security monitoring
- Adjust thresholds based on operational baseline
- Review and tune alerts after deployment

---

## Reporting Security Issues

If you discover a security vulnerability in DMIS:

1. **Do NOT** create a public GitHub issue
2. Contact the ODPEM IT Security team directly
3. Provide:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact assessment
   - Suggested remediation (if any)

### Response Timeline

| Severity | Initial Response | Resolution Target |
|----------|------------------|-------------------|
| Critical | 4 hours | 24 hours |
| High | 24 hours | 72 hours |
| Medium | 72 hours | 2 weeks |
| Low | 1 week | Next release |

---

## Additional Resources

- [Bandit Documentation](https://bandit.readthedocs.io/)
- [Semgrep Documentation](https://semgrep.dev/docs/)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Flask Security Best Practices](https://flask.palletsprojects.com/en/latest/security/)

---

*Last Updated: December 2025*
