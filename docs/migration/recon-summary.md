# Recon Summary

Continuity notes from initial reconnaissance.

## Serving Stack
- Entry points: `main.py` / `wsgi.py`
- Runtime: Gunicorn
- Edge: NGINX templates located in the repo

## RBAC Entry Points
- `rbac.py`
- `decorators.py`
- `feature_registry.py`
- DB tables: `Role`, `Permission`, `RolePermission`

## Audit Logging
- `audit_logger.py` supports READ events without DB changes.

## Data Sources for Needs List Preview
- Inventory: `Inventory`
- Transfers: `Transfer`, `TransferItem`
- Donations: `Donation`, `DonationIntake`, `DonationIntakeItem`
- Burn proxies: `ReliefPkg`, `ReliefRqstItem`, and raw SQL in `transaction`

## Known Gaps
- Procurement tables are missing.
- Transfer intake tables appear commented out.
- `transaction` access is raw SQL only.
