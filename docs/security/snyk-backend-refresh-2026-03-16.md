# Snyk Backend Refresh Notes

Date: 2026-03-16
Repository branch: `prototype-supply-replenishment`
Repository commit: `733c44fc7263656a375dbca0b1739551be38bb71`

## Current backend dependency facts

- Backend manifest: `backend/requirements.txt`
- Python runtime in local backend venv: `3.13.12`
- Django pinned: `4.2.29`
- PyJWT pinned: `2.12.0`
- Added `backend/.snyk` with `language-settings.python: "3.13"` so SCM imports can bind the backend manifest to Python 3.13.

## Why Snyk Web can still look stale

- The Snyk Web project snapshot can lag behind the repository state if the monitored Project was imported before the backend manifest or policy metadata changed.
- Snyk documents that for SCM scans, Python version is controlled at the Organization level unless a `.snyk` file in the manifest directory overrides it.
- Snyk also documents that if the `.snyk` file was not present at the initial import, the Project must be re-imported for that metadata to take effect.

## Local refresh attempts performed on 2026-03-16

### Fresh CLI test attempt

Command run from `backend/`:

```powershell
npx -y snyk@latest test --file=requirements.txt --package-manager=pip --command="C:\Users\wbowe\OneDrive\Desktop\project\DMIS_UpdatedVersion\backend\.venv\Scripts\python.exe" --skip-unresolved --severity-threshold=low
```

Result:

- Failed in Snyk's pip resolver.
- Debug trace showed:
  - `pip_resolve.py`, line 7
  - `ModuleNotFoundError: No module named 'utils'`
- Interaction ID: `urn:snyk:interaction:17f70ea6-bafb-4d0a-bc87-f00448e649db`

### Fresh CLI monitor attempt

Command run from repo root:

```powershell
npx -y snyk@latest monitor --file=backend\requirements.txt --package-manager=pip --command="C:\Users\wbowe\OneDrive\Desktop\project\DMIS_UpdatedVersion\backend\.venv\Scripts\python.exe" --project-name=DMIS_UpdatedVersion-backend
```

Result:

- Failed during dependency extraction.
- Debug trace ended at `getDepsFromPlugin ... undefined`
- Interaction ID: `urn:snyk:interaction:21b2f40e-4923-4c18-a36c-f422f5276a4b`

## Recommended Snyk Web remediation

1. In Snyk Web, locate the backend Open Source Project for this repository and inspect the dependency snapshot.
2. Confirm whether the snapshot still shows package versions older than `Django 4.2.29` or `PyJWT 2.12.0`.
3. Check the Organization Import Log for pip import errors tied to this repository and backend manifest.
4. If the Project was imported before `backend/.snyk` existed, delete or deactivate the stale imported Project and re-import the repository so the backend manifest is rescanned with the new project-level Python setting.
5. In Organization settings for Snyk Open Source, verify the Pip Python version is compatible with Python 3.13 if the Organization relies on org-wide Python settings.
6. If re-import still fails, open a Snyk support case and include both interaction IDs above plus the pip resolver error.

## Expected post-refresh result

After a successful re-import or re-monitor, the backend Open Source Project should reflect:

- Django `4.2.29`
- PyJWT `2.12.0`
- backend policy metadata from `backend/.snyk`

At that point, stale package advisories such as the Django 4.2 line vulnerabilities and the older PyJWT signature-verification advisory should drop from the current backend snapshot.
