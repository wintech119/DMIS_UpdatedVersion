# DMIS Security Controls Matrix

## Overview

This document maps security controls across application, infrastructure, and process layers for the Disaster Management Information System (DMIS).

## Application Security Controls

### Authentication & Session Management

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| APP-AUTH-01 | Password Hashing | PBKDF2-SHA256 via Werkzeug | Implemented |
| APP-AUTH-02 | Session Security | Secure, HttpOnly, SameSite=Lax cookies | Implemented |
| APP-AUTH-03 | Brute Force Protection | Rate limiting (5/min on login) | Implemented |
| APP-AUTH-04 | Account Lockout | Lock after failed attempts | Implemented |
| APP-AUTH-05 | Session Timeout | Configurable session lifetime | Implemented |
| APP-AUTH-06 | Logout | Session invalidation, audit logging | Implemented |

### Authorization

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| APP-AUTHZ-01 | Role-Based Access Control | Flask decorators, feature registry | Implemented |
| APP-AUTHZ-02 | Role Hierarchy | Executive > Manager > Officer > Agency | Implemented |
| APP-AUTHZ-03 | Feature Registry | Centralized access control definitions | Implemented |
| APP-AUTHZ-04 | Role Assignment Validation | Restrict who can assign which roles | Implemented |
| APP-AUTHZ-05 | Server-Side Enforcement | All routes protected at backend | Implemented |

### Input Validation

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| APP-INPUT-01 | Parameter Validation | app/security/param_validation.py | Implemented |
| APP-INPUT-02 | Query String Protection | app/security/query_string_protection.py | Implemented |
| APP-INPUT-03 | Path Traversal Prevention | app/security/safe_path.py | Implemented |
| APP-INPUT-04 | URL Safety Validation | app/security/url_safety.py | Implemented |
| APP-INPUT-05 | File Upload Validation | Content-type, size limits | Implemented |

### Output Encoding

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| APP-OUTPUT-01 | Template Auto-Escaping | Jinja2 autoescape=True | Implemented |
| APP-OUTPUT-02 | Content Security Policy | Nonce-based CSP | Implemented |
| APP-OUTPUT-03 | Error Message Sanitization | Generic user messages | Implemented |
| APP-OUTPUT-04 | Log Sanitization | app/security/log_sanitizer.py | Implemented |

### API Security

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| APP-API-01 | Rate Limiting | Flask-Limiter, tiered limits | Implemented |
| APP-API-02 | CORS Configuration | Domain allowlist, credentials handling | Implemented |
| APP-API-03 | CSRF Protection | Flask-WTF with token validation | Implemented |
| APP-API-04 | Safe External API Calls | SafeApiClient with validation | Implemented |

### Data Protection

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| APP-DATA-01 | SQL Injection Prevention | SQLAlchemy ORM, parameterized queries | Implemented |
| APP-DATA-02 | Optimistic Locking | version_nbr on all entities | Implemented |
| APP-DATA-03 | Sensitive Data Handling | No secrets in logs, email obfuscation | Implemented |
| APP-DATA-04 | Cache Control | No-cache headers for sensitive pages | Implemented |

### Audit & Logging

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| APP-AUDIT-01 | Security Event Logging | app/security/audit_logger.py | Implemented |
| APP-AUDIT-02 | Structured Log Format | SIEM-compatible format | Implemented |
| APP-AUDIT-03 | Authentication Logging | Login success/failure/lockout | Implemented |
| APP-AUDIT-04 | Data Access Logging | CRUD operations on key entities | Implemented |
| APP-AUDIT-05 | User Management Logging | Create, update, role changes | Implemented |

## Infrastructure Security Controls

### Network Security

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| INFRA-NET-01 | TLS Encryption | TLS 1.2+ with modern ciphers | Required |
| INFRA-NET-02 | HSTS | 1 year max-age, includeSubDomains | Required |
| INFRA-NET-03 | Reverse Proxy | NGINX in front of application | Required |
| INFRA-NET-04 | Rate Limiting (Network) | NGINX limit_req module | Recommended |

### Server Hardening

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| INFRA-SRV-01 | Minimal Services | Only required services running | Required |
| INFRA-SRV-02 | Security Updates | Regular patching schedule | Required |
| INFRA-SRV-03 | Firewall | Only necessary ports open | Required |
| INFRA-SRV-04 | WAF | Web Application Firewall | Recommended |

### Database Security

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| INFRA-DB-01 | Encrypted Connections | SSL/TLS to PostgreSQL | Required |
| INFRA-DB-02 | Least Privilege | App user with minimal permissions | Required |
| INFRA-DB-03 | Encryption at Rest | Neon-managed encryption | Implemented |
| INFRA-DB-04 | Backup Security | Encrypted backups | Required |

### Secrets Management

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| INFRA-SEC-01 | Environment Variables | DMIS_* prefixed configuration | Implemented |
| INFRA-SEC-02 | No Secrets in Code | .env excluded from VCS | Implemented |
| INFRA-SEC-03 | Secret Rotation | Regular key rotation policy | Required |
| INFRA-SEC-04 | Secrets Storage | Platform secrets management | Implemented |

## Process Security Controls

### Development Practices

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| PROC-DEV-01 | SAST Scanning | Bandit, Semgrep | Implemented |
| PROC-DEV-02 | Dependency Scanning | pip-audit, safety | Implemented |
| PROC-DEV-03 | Code Review | Required for all changes | Required |
| PROC-DEV-04 | Security Testing | Security requirements in testing | Required |

### CI/CD Security

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| PROC-CICD-01 | Automated Security Scans | GitHub Actions workflow | Implemented |
| PROC-CICD-02 | Severity Gating | Block on High/Critical findings | Implemented |
| PROC-CICD-03 | SARIF Reporting | GitHub Security tab integration | Implemented |
| PROC-CICD-04 | Artifact Signing | Build artifact integrity | Recommended |

### Operational Security

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| PROC-OPS-01 | Incident Response | Security incident procedures | Required |
| PROC-OPS-02 | Vulnerability Management | CVE tracking and remediation | Required |
| PROC-OPS-03 | Security Monitoring | SIEM alerting rules | Required |
| PROC-OPS-04 | Access Reviews | Quarterly user access reviews | Required |

### Compliance

| Control ID | Control Name | Implementation | Status |
|------------|--------------|----------------|--------|
| PROC-COMP-01 | NIST 800-53 Alignment | AU controls for audit logging | Implemented |
| PROC-COMP-02 | GOJ Cybersecurity Policy | Aligned with GOJ requirements | In Progress |
| PROC-COMP-03 | Data Protection | PII handling procedures | Required |
| PROC-COMP-04 | Security Documentation | Architecture, threat model, controls | Implemented |

## Control Status Summary

| Layer | Total Controls | Implemented | Required | Recommended |
|-------|----------------|-------------|----------|-------------|
| Application | 26 | 26 | 0 | 0 |
| Infrastructure | 12 | 3 | 8 | 1 |
| Process | 12 | 4 | 7 | 1 |
| **Total** | **50** | **33** | **15** | **2** |

## Implementation Priority

### Immediate (Pre-Production)

1. TLS encryption (INFRA-NET-01)
2. HSTS configuration (INFRA-NET-02)
3. Database SSL (INFRA-DB-01)
4. Least privilege DB user (INFRA-DB-02)
5. NGINX reverse proxy (INFRA-NET-03)

### Short-Term (Post-Launch)

1. SIEM integration (PROC-OPS-03)
2. Incident response procedures (PROC-OPS-01)
3. Access review process (PROC-OPS-04)
4. Security testing integration (PROC-DEV-04)

### Medium-Term (Quarterly)

1. WAF implementation (INFRA-SRV-04)
2. Secret rotation policy (INFRA-SEC-03)
3. Penetration testing
4. Security awareness training

---

*Document Version: 1.0*
*Last Updated: December 2025*
*Owner: ODPEM IT Security Team*
*Review Frequency: Quarterly*
