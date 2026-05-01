# Security Exception: uuid (sockjs transitive)

Date: 2026-04-30
Scope: `frontend/`
Status: Active suppression - re-evaluate on sunset condition below.

## 1. Advisory

- ID: GHSA-w5hq-g745-h8pq
- CWE: CWE-787 / CWE-1285 ("uuid: Missing buffer bounds check in v3/v5/v6 when buf is provided")
- Severity (npm audit): moderate
- Vulnerable range as flagged: `uuid <14.0.0`
- Trigger: caller passes a user-controlled `buf` argument to `uuid.v3()`, `uuid.v5()`, or `uuid.v6()`.

## 2. Dependency path

```text
@angular-devkit/build-angular@21.2.9
  -> webpack-dev-server@5.2.3
      -> sockjs@0.3.24
          -> uuid@8.3.2
```

`frontend/package.json` declares `@angular-devkit/build-angular` as `^21.2.5`;
`frontend/package-lock.json` currently resolves it to `21.2.9`. The wrapping
packages are dev tooling. None ship in the production Angular bundle produced
by `npm run build`.

## 3. Worktree evidence - call site is not vulnerable

Inspected `frontend/node_modules/sockjs/lib/transport.js`:

- Line 9: `uuidv4 = require('uuid').v4;`
- Line 37: `this.id = uuidv4();`

sockjs imports only `uuid.v4` and invokes it with **no arguments** (no caller-provided buffer). The advisory targets `v3`/`v5`/`v6` *with* a `buf` argument; sockjs does not exercise either condition. The advisory is a transitive false-positive for this dependency path.

## 4. Risk decision

Not exploitable as configured. Suppression is accepted on the following grounds:

- **Code-path analysis**: sockjs's only `uuid` call site is `v4()` with no buffer - outside the advisory's vulnerable surface.
- **Runtime exposure**: dev-tooling only. `webpack-dev-server` is a direct dependency of the resolved `@angular-devkit/build-angular@21.2.9` toolchain and may be loaded during `ng serve`, so this exception treats sockjs as dev-time reachable. The published production bundle does not include `uuid`, `sockjs`, or `webpack-dev-server`.
- **Compatibility cost of forcing a fix**: `uuid@12+` no longer supports CommonJS, so `uuid@14` would not be compatible with this CommonJS call site (`require('uuid').v4`) if webpack-dev-server is ever loaded by any tooling path. `uuid@11.x` retains CJS but `npm audit` keys this advisory as `<14.0.0`, so an `11.1.1` pin would not necessarily clear the audit gate while still requiring dependency materialization.
- **Supply-chain hold**: project-level hold on `npm install` / `npm audit fix` is currently in effect; introducing an `overrides` entry without materialization would create lockfile drift.

Decision: do not introduce a `uuid` override. Document the exception and leave the transitive in place.

## 5. Sunset conditions

Remove this suppression and re-run `npm audit` when **any** of the following becomes true:

1. Angular CLI / `@angular-devkit/build-angular` ships a release whose `webpack-dev-server` -> `sockjs` -> `uuid` chain has resolved the advisory upstream (i.e. `npm audit` reports 0 advisories on the chain after a routine devkit minor/patch bump).
2. The next time dependency materialization is approved, re-check the current advisory metadata first, then decide whether to retire, renew, or replace this exception.
3. sockjs's call site changes (e.g. starts passing a caller-controlled `buf` to `v3`/`v5`/`v6`), which would invalidate the code-path analysis above.

Anyone re-running `npm audit` on this repository should treat advisories matching the chain in section 2 as covered by this exception until the sunset condition is met.
