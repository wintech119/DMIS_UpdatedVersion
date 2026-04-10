# Production Readiness Checklist

Last updated: 2026-04-09
Status: Pre-production gate checklist

Use this checklist together with:

- `docs/implementation/production_hardening_and_flask_retirement_strategy.md`
- `docs/security/SECURITY_ARCHITECTURE.md`
- `docs/security/THREAT_MODEL.md`
- `docs/security/CONTROLS_MATRIX.md`

## 1. Security Baseline

- [ ] production and staging require OIDC/JWT authentication
- [ ] no production frontend build includes dev-user impersonation logic
- [ ] no production backend runtime accepts dev-user override behavior
- [ ] Django runs with `DEBUG = False`
- [ ] HTTPS redirect is enabled
- [ ] secure session cookies are enabled
- [ ] secure CSRF cookies are enabled
- [ ] HSTS is enabled with approved policy
- [ ] privileged roles have MFA or an approved equivalent control before launch
- [ ] global API throttling exists in addition to any endpoint-specific throttles

## 2. Authorization and Tenant Safety

- [ ] backend authorization is the source of truth for all sensitive workflows
- [ ] frontend route guards cover all sensitive feature routes
- [ ] tenant membership and tenant-scope checks are validated for high-risk workflows
- [ ] cross-tenant actions are explicitly governed and auditable
- [ ] privileged role assignment and review process is defined

## 3. Platform Reliability and Availability

- [ ] Redis is mandatory in production
- [ ] liveness endpoint exists
- [ ] readiness endpoint checks critical dependencies
- [ ] API, DB, cache, and queue telemetry are available
- [ ] alerting exists for dependency failure and sustained error-rate spikes
- [ ] backup procedure is documented
- [ ] restore test has been executed successfully
- [ ] rollback procedure is documented and assigned

## 4. Performance and Scalability

- [ ] critical workflows have identified hot queries and optimization owners
- [ ] long-running or retryable work is offloaded to workers
- [ ] critical list and dashboard flows use bounded server-side loading patterns
- [ ] capacity targets and representative load criteria are defined
- [ ] large frontend route chunks or oversized workflow files have an active reduction plan

## 5. Data and Audit Integrity

- [ ] critical workflow artifacts are durably stored
- [ ] audit logging exists for privileged and state-changing operations
- [ ] request or trace correlation can link frontend, API, and worker activity
- [ ] recovery expectations for critical records and artifacts are documented

## 6. Delivery and Governance

- [ ] architecture, threat model, and controls docs match the deployed stack
- [ ] release signoff includes security, observability, and recovery evidence
- [ ] dependency and vulnerability scanning are part of release review
- [ ] known risks have owners, priorities, and due dates

## 7. Flask Retirement

- [ ] all live Flask entry points are inventoried
- [ ] each Flask capability is marked as replaced, retired, or rollback-only
- [ ] live navigation no longer routes users to Flask
- [ ] release notes and QA evidence reflect the Flask cutover state
- [ ] Flask is not a hidden live dependency for normal operations
- [ ] a final decommission plan exists for removing Flask from deployment

## Exit Rule

DMIS should not be labeled production-ready until every `Production Gate` item in the controls matrix and every applicable item in this checklist are either complete or explicitly accepted as a launch risk by the responsible decision-makers.
