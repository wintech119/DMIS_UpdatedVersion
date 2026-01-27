# DMIS Security Architecture

## Overview

This document describes the security architecture of the Disaster Management Information System (DMIS), including system components, trust boundaries, and data flows.

## System Components

### Web Tier

| Component | Technology | Security Role |
|-----------|------------|---------------|
| **Reverse Proxy** | NGINX | TLS termination, rate limiting, security headers |
| **Web Application** | Flask 3.0.3 | Authentication, authorization, business logic |
| **Static Assets** | NGINX static serving | SRI integrity validation |

### Application Tier

| Component | Technology | Security Role |
|-----------|------------|---------------|
| **Authentication** | Flask-Login | Session management, credential validation |
| **Authorization** | Custom RBAC | Role-based access control, feature registry |
| **Rate Limiting** | Flask-Limiter | API abuse prevention |
| **CSRF Protection** | Flask-WTF | Cross-site request forgery prevention |
| **Content Security** | Custom CSP | XSS prevention, resource integrity |

### Data Tier

| Component | Technology | Security Role |
|-----------|------------|---------------|
| **Primary Database** | PostgreSQL 16+ | Data persistence, integrity constraints |
| **ORM** | SQLAlchemy 2.0 | SQL injection prevention, parameterized queries |
| **Connection Pool** | SQLAlchemy Pool | Connection security, timeout management |

## Trust Boundaries

```
                                    INTERNET
                                        |
                                        v
    +-------------------------------------------------------------------+
    |                     EXTERNAL TRUST BOUNDARY                       |
    +-------------------------------------------------------------------+
                                        |
                                        v
    +-------------------------------------------------------------------+
    |                        NGINX REVERSE PROXY                        |
    |                   (TLS, Rate Limiting, WAF)                       |
    +-------------------------------------------------------------------+
                                        |
                                        v
    +-------------------------------------------------------------------+
    |                     DMZ TRUST BOUNDARY                            |
    +-------------------------------------------------------------------+
                                        |
                                        v
    +-------------------------------------------------------------------+
    |                     FLASK APPLICATION                             |
    |              (Authentication, Authorization, CSP)                 |
    +-------------------------------------------------------------------+
                                        |
                                        v
    +-------------------------------------------------------------------+
    |                  APPLICATION TRUST BOUNDARY                       |
    +-------------------------------------------------------------------+
                                        |
                                        v
    +-------------------------------------------------------------------+
    |                      POSTGRESQL DATABASE                          |
    |              (Encrypted connections, Access controls)             |
    +-------------------------------------------------------------------+
                                        |
                                        v
    +-------------------------------------------------------------------+
    |                     DATA TRUST BOUNDARY                           |
    +-------------------------------------------------------------------+
```

## External Actors

### Public Users (Untrusted)

| Actor | Access | Trust Level |
|-------|--------|-------------|
| **Anonymous** | Account request form only | Untrusted |
| **Agency Staff** | After authentication only | Semi-trusted |

### Internal Users (Semi-Trusted)

| Role | Access Level | Trust Level |
|------|--------------|-------------|
| **Logistics Officer** | Create/edit donations, packages | Semi-trusted |
| **Logistics Manager** | Verify, dispatch, approve | Trusted |
| **Director (PEOD)** | Approve eligibility, view analytics | Trusted |
| **Deputy DG** | Executive dashboards, reports | Highly trusted |
| **DG** | Full executive access | Highly trusted |

### Administrative Users (Trusted)

| Role | Access Level | Trust Level |
|------|--------------|-------------|
| **System Administrator** | Full user management, system config | Highly trusted |
| **Custodian** | Limited user management | Trusted |

### External Systems

| System | Connection Type | Trust Level |
|--------|-----------------|-------------|
| **Currency Exchange API** | Outbound HTTPS | Untrusted (validated) |
| **Email Service** | Outbound SMTP | Semi-trusted |

## Data Classification

### High Sensitivity

- User credentials (password hashes)
- Session tokens
- API keys and secrets
- Personal identifiable information (PII)

### Medium Sensitivity

- Donation records
- Relief request details
- Inventory levels
- Transaction history

### Low Sensitivity

- Reference data (items, categories)
- Public agency information
- System configuration (non-secret)

## Network Segmentation

### Production Environment

```
[Internet] -> [WAF/CDN] -> [NGINX] -> [Flask App] -> [PostgreSQL]
                 |                        |
                 v                        v
           [Rate Limits]           [Audit Logs]
```

### Development Environment (Replit)

```
[Internet] -> [Replit Proxy] -> [Flask App (Debug)] -> [PostgreSQL (Neon)]
```

## Security Zones

| Zone | Components | Controls |
|------|------------|----------|
| **Public Zone** | NGINX, static assets | TLS, rate limiting, WAF |
| **Application Zone** | Flask, session data | Authentication, RBAC, CSRF |
| **Data Zone** | PostgreSQL | Encryption, access controls, audit |
| **Management Zone** | Admin interfaces | Strong authentication, logging |

## Key Security Boundaries

1. **Internet to DMZ**: TLS 1.2+, rate limiting, input validation
2. **DMZ to Application**: Session validation, CSRF tokens
3. **Application to Database**: Parameterized queries, connection pooling
4. **User to Role**: RBAC enforcement at every route

---

*Document Version: 1.0*
*Last Updated: December 2025*
*Owner: ODPEM IT Security Team*
