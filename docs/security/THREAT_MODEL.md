# DMIS Threat Model

## Overview

This document identifies key threats to the Disaster Management Information System (DMIS) and the mitigations implemented to address them. Based on STRIDE threat modeling methodology.

## Threat Categories (STRIDE)

### S - Spoofing Identity

#### Threat: Credential Theft

| Aspect | Details |
|--------|---------|
| **Description** | Attacker steals user credentials through phishing, brute force, or credential stuffing |
| **Impact** | Unauthorized access to system, data breach, fraudulent transactions |
| **Likelihood** | High |
| **Severity** | Critical |

**Mitigations:**
- Rate limiting on login endpoint (5 attempts/minute)
- Password hashing with Werkzeug (PBKDF2-SHA256)
- Account lockout after failed attempts
- Session timeout and secure cookie settings
- Audit logging of all authentication events

#### Threat: Session Hijacking

| Aspect | Details |
|--------|---------|
| **Description** | Attacker steals or forges session tokens |
| **Impact** | Impersonation of legitimate users |
| **Likelihood** | Medium |
| **Severity** | High |

**Mitigations:**
- Secure, HttpOnly, SameSite=Lax cookies
- TLS for all connections (HSTS enabled)
- Session regeneration on login
- IP-based session validation (optional)

### T - Tampering with Data

#### Threat: SQL Injection

| Aspect | Details |
|--------|---------|
| **Description** | Attacker injects malicious SQL through input fields |
| **Impact** | Data breach, data modification, privilege escalation |
| **Likelihood** | Medium |
| **Severity** | Critical |

**Mitigations:**
- SQLAlchemy ORM with parameterized queries
- Input validation on all user inputs
- Database user with minimal privileges
- SAST scanning with Bandit and Semgrep

#### Threat: Donation/Inventory Manipulation

| Aspect | Details |
|--------|---------|
| **Description** | Malicious insider modifies donation or inventory records |
| **Impact** | Financial loss, audit trail corruption |
| **Likelihood** | Low |
| **Severity** | High |

**Mitigations:**
- Optimistic locking (version_nbr) on all records
- Audit logging of all data modifications
- Role-based access control (separation of duties)
- Two-stage verification workflow for donations

### R - Repudiation

#### Threat: Denial of Actions

| Aspect | Details |
|--------|---------|
| **Description** | User denies performing actions (approvals, dispatches) |
| **Impact** | Inability to hold users accountable, legal disputes |
| **Likelihood** | Medium |
| **Severity** | Medium |

**Mitigations:**
- Comprehensive audit logging (NIST 800-53 AU controls)
- Structured log format for SIEM ingestion
- User ID, timestamp, action, and outcome recorded
- Logs include IP address for correlation
- Jamaica timezone standardization for legal compliance

### I - Information Disclosure

#### Threat: Sensitive Data Exposure

| Aspect | Details |
|--------|---------|
| **Description** | Unauthorized access to PII, donation details, or credentials |
| **Impact** | Privacy violation, reputational damage, legal liability |
| **Likelihood** | Medium |
| **Severity** | High |

**Mitigations:**
- TLS encryption in transit
- PostgreSQL encryption at rest (Neon-managed)
- No sensitive data in URLs (query string protection)
- Email obfuscation in logs
- Generic error messages (no stack traces to users)
- Content Security Policy (CSP) to prevent data exfiltration

#### Threat: Error Message Information Leak

| Aspect | Details |
|--------|---------|
| **Description** | Detailed error messages reveal system internals |
| **Impact** | Information useful for further attacks |
| **Likelihood** | Medium |
| **Severity** | Medium |

**Mitigations:**
- Production-safe error handling (DEBUG=false by default)
- Generic user-facing error messages
- Server-side logging with sanitization
- Custom error pages (403, 404, 429, 500)

### D - Denial of Service

#### Threat: Application-Level DoS

| Aspect | Details |
|--------|---------|
| **Description** | Attacker floods endpoints with requests |
| **Impact** | System unavailable during disaster response |
| **Likelihood** | High |
| **Severity** | High |

**Mitigations:**
- Flask-Limiter rate limiting on all endpoints
- Tiered limits: auth (5/min), API (60/min), exports (3/hour)
- NGINX rate limiting at reverse proxy
- Default limits: 200/hour, 50/minute
- Rate limit exceeded events logged for alerting

#### Threat: Resource Exhaustion

| Aspect | Details |
|--------|---------|
| **Description** | Attacker triggers expensive operations (exports, reports) |
| **Impact** | Database/server overload |
| **Likelihood** | Medium |
| **Severity** | Medium |

**Mitigations:**
- Rate limiting on expensive endpoints (10/min)
- Export limits (3/hour)
- Query timeouts
- Connection pool limits

### E - Elevation of Privilege

#### Threat: RBAC Bypass

| Aspect | Details |
|--------|---------|
| **Description** | User accesses resources beyond their role |
| **Impact** | Unauthorized data access or actions |
| **Likelihood** | Low |
| **Severity** | High |

**Mitigations:**
- Centralized RBAC with @role_required decorator
- Feature registry with role-based access
- Server-side authorization checks on all routes
- Client-side restrictions for UX only (not security)

#### Threat: Privilege Escalation via Role Assignment

| Aspect | Details |
|--------|---------|
| **Description** | Lower-privilege user assigns admin roles |
| **Impact** | Complete system compromise |
| **Likelihood** | Low |
| **Severity** | Critical |

**Mitigations:**
- Role assignment validation (can only assign roles you're permitted)
- CUSTODIAN cannot assign SYSTEM_ADMINISTRATOR
- Audit logging of all role changes
- Server-side validation of role assignments

## OWASP Top 10 Coverage

| Risk | Mitigation Status |
|------|-------------------|
| A01 - Broken Access Control | RBAC, role_required decorator, server-side checks |
| A02 - Cryptographic Failures | TLS 1.2+, PBKDF2 password hashing, secure cookies |
| A03 - Injection | SQLAlchemy ORM, parameterized queries, input validation |
| A04 - Insecure Design | Threat modeling, security architecture review |
| A05 - Security Misconfiguration | Production-safe defaults, SAST scanning |
| A06 - Vulnerable Components | pip-audit, safety dependency scanning |
| A07 - Auth Failures | Rate limiting, session security, lockout |
| A08 - Data Integrity | Optimistic locking, audit logging |
| A09 - Security Logging | NIST 800-53 compliant audit logging |
| A10 - Server-Side Request Forgery | SafeApiClient with domain allowlist |

## Risk Summary Matrix

| Threat | Likelihood | Severity | Risk Level | Mitigation Status |
|--------|------------|----------|------------|-------------------|
| Credential Theft | High | Critical | Critical | Mitigated |
| Session Hijacking | Medium | High | High | Mitigated |
| SQL Injection | Medium | Critical | High | Mitigated |
| Data Manipulation | Low | High | Medium | Mitigated |
| Action Repudiation | Medium | Medium | Medium | Mitigated |
| Information Disclosure | Medium | High | High | Mitigated |
| Denial of Service | High | High | High | Mitigated |
| Privilege Escalation | Low | Critical | Medium | Mitigated |

---

*Document Version: 1.0*
*Last Updated: December 2025*
*Owner: ODPEM IT Security Team*
*Review Frequency: Quarterly*
