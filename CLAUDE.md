# DMIS Supply Replenishment Module - Claude Code Context

## Project Overview

DMIS (Disaster Management Information System) for Jamaica's ODPEM. This module (EP-02) handles:
- Stock monitoring and burn rate calculation
- Time-to-stockout predictions
- Needs list generation and approval workflows
- Three Horizons replenishment (Transfers → Donations → Procurement)

## Tech Stack

- **Frontend**: Angular 21+, Angular Material, TypeScript
- **Backend**: Django 4.2 (LTS), Django REST Framework
- **Database**: PostgreSQL 18+
- **Auth**: Keycloak OIDC

## Primary User: Kemar (Logistics Manager)

- Field-first mindset, works on mobile
- Low tolerance for messy data
- Needs fast, accurate, real-time visibility
- "If it's not logged, it didn't happen"

## Key Business Logic

### Event Phases
| Phase | Demand Window | Planning Window |
|-------|---------------|-----------------|
| SURGE | 6 hours | 72 hours |
| STABILIZED | 72 hours | 7 days |
| BASELINE | 30 days | 30 days |

### Core Formulas
```
Burn Rate = Fulfilled Qty / Demand Window (hrs)
Time-to-Stockout = Available Stock / Burn Rate  
Required Qty = Burn Rate × Planning Window × 1.25
Gap = Required Qty - (Available + Confirmed Inbound)
```

### Status Severity
- **CRITICAL** (red): Time-to-Stockout < 8 hours
- **WARNING** (amber): 8-24 hours
- **WATCH** (yellow): 24-72 hours
- **OK** (green): > 72 hours

### Data Freshness
- **HIGH** (green): < 2 hours old
- **MEDIUM** (amber): 2-6 hours old
- **LOW** (red): > 6 hours old - show warning!

### Three Horizons
- **A (Transfers)**: 6-8 hour lead time, use first
- **B (Donations)**: 2-7 day lead time, fills remaining gap
- **C (Procurement)**: 14+ day lead time, last resort

## Current UI/UX Focus Areas

### Priority 1: Dashboard Improvements
- [ ] Critical items must be immediately visible (red, top of list)
- [ ] Add data freshness indicator with last sync time
- [ ] Default sort by Time-to-Stockout (most urgent first)
- [ ] "Generate Needs List" button prominent when items are critical

### Priority 2: Burn Rate & Time-to-Stockout Display  
- [ ] Show units: "50 units/hr" not just "50"
- [ ] Add trend indicator (up/down arrow)
- [ ] Show confidence level based on data freshness
- [ ] Countdown-style time-to-stockout: "4h 30m"

### Priority 3: Needs List Workflow
- [ ] 3-step wizard: Scope → Preview → Submit
- [ ] Allow quantity adjustment with mandatory reason
- [ ] Show approval path (who will approve)
- [ ] Visual stepper showing workflow status

### Priority 4: Mobile Experience
- [ ] Stack cards vertically
- [ ] Tables become card lists on small screens
- [ ] FAB button for "Generate Needs List"
- [ ] Collapsible filter panel

## Coding Standards

### Angular Patterns
- Standalone components preferred (Angular 21+ default)
- Signals-based reactivity preferred over RxJS where appropriate
- OnPush change detection where possible
- Services for API calls, components for display
- Reactive forms for inputs

### UI Patterns
- Use Angular Material components as base
- Create DMIS-prefixed shared components
- Status colors must have text/icon backup (accessibility)
- All loading states need skeletons, not spinners

### Error Handling
- Toast for network errors with retry
- Inline validation for forms
- Empty states with helpful actions
- Never fail silently

## File Structure
```
src/app/features/replenishment/
├── components/
│   ├── dashboard/
│   ├── needs-list/
│   ├── stock-detail/
│   └── shared/
├── services/
│   └── replenishment.service.ts
├── models/
│   └── replenishment.models.ts
├── store/ (if using NgRx)
└── replenishment.routes.ts
```

## API Endpoints

```
GET  /api/replenishment/stock-status/
GET  /api/replenishment/burn-rates/?warehouse_id=X
POST /api/replenishment/needs-list/generate/
GET  /api/replenishment/needs-list/{id}/
POST /api/replenishment/needs-list/{id}/submit/
POST /api/replenishment/needs-list/{id}/approve/
```

## Quick Reference Commands

```bash
# Run Angular dev server
ng serve

# Run tests
ng test --watch=false

# Build for production  
ng build --configuration=production

# Run Django backend
python manage.py runserver

# Run Django tests
python manage.py test replenishment
```

## Non-Negotiable Requirements

1. **No auto-actions**: System recommends, humans approve
2. **Audit everything**: All changes logged with user, timestamp, reason
3. **Data freshness visible**: User must know when data is stale
4. **Strict inbound**: Only count DISPATCHED transfers, IN-TRANSIT donations, SHIPPED procurement
5. **Mobile-friendly**: Kemar is often in the field

## When in Doubt

Ask: "Would Kemar be able to use this in the field during a hurricane response?"

If the answer is no, simplify it.

---

## Workflow Orchestration

### 1. Plan Node Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep the main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project context

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behaviour between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

---

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

---

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing unintended side effects.
