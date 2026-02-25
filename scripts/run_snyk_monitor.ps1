# Run Snyk monitor for all projects. Uses --skip-unresolved so Python
# projects (root + backend) don't fail when their venv isn't active.
$org = "87420496-a198-451a-88ab-84b779eba8e6"
npx snyk monitor --all-projects --org=$org --skip-unresolved
