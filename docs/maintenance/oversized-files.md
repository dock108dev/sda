# Oversized Source File Inventory

Current result: no maintained production source files are over 500 lines.

The cleanup size target excludes tests, shell scripts, migrations, generated
data, lockfiles, docs, build output, virtualenvs, and dependency directories.
Those files can be large for valid reasons and are not part of this source
refactor inventory.

Validation command from the sports workspace root:

```bash
find scroll-down-ios sports-data-admin -type f \
  \( -name '*.swift' -o -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' \) \
  ! -path '*Tests*' \
  ! -path '*/tests/*' \
  ! -path '*/__tests__/*' \
  ! -path '*/node_modules/*' \
  ! -path '*/.next/*' \
  ! -path '*/build/*' \
  ! -path '*/.build/*' \
  ! -path '*/DerivedData/*' \
  ! -path '*/.venv/*' \
  ! -path '*/.venv-*/*' \
  ! -path '*/venv/*' \
  ! -path '*/versions/*' \
  ! -path '*/coverage_html/*' \
  ! -name '*.sh' \
  -print0 | xargs -0 wc -l | awk '$1 > 500 {print}'
```
