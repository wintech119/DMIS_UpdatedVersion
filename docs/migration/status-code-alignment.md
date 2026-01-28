# Status Code Alignment

This document locks the status-code vocabulary used during migration.

## Donations
- The DB/model vocabulary is **E / V / P**.
- This is authoritative and must remain the source of truth.
- Do **not** rewrite to A / P / C.

## Transfers
- Status codes observed in models and `transfers.py` are **D / C / V / P**.
- There is ambiguity in the meaning of these codes that must be resolved against the PRD and appendices.

## Source of Truth
- The PRD and appendices are the canonical reference.
- Where mappings conflict, we will align code to the PRD/appendices and the actual DB enums.
