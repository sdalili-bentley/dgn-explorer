# DGN Explorer Agent Guide

Read [README.md](README.md) for implemented behavior, [PLAN.md](PLAN.md) for
pending work, and [DEPENDENCY_POLICY.md](DEPENDENCY_POLICY.md) before dependencies.

- Current code: `dgn_folder.py` owns codecs; `dgn_explorer/` owns the shared
  service/transactions/CLI/worker/policy and optional desktop. The CLI skill lives
  in `skills/dgn-explorer/`. Qt 6.11.2 desktop workflows and real relocated frozen
  GUI/CLI tests pass. Company release, clean-VM and native-product gates remain.
- Keep one codec implementation; preserve v1/v2, aliases, identities, original
  snapshots, unknown bytes and strict reversible encodings. Never overwrite inputs.
- Every code/UI change adds extensive, reusable tests; every bug fix adds a
  regression. Reuse synthetic fixtures/helpers and test observable behavior.
- Run `python -m unittest discover -s . -p 'test_*.py' -v` after changes.
  Sample tests require the specific baseline via `DGN_EXPLORER_SAMPLE`; report
  skipped/platform gaps, never call them passed. Shared COM fixtures are synthetic;
  Qt tests skip without admitted dependencies. See `TESTING.md` for remaining gates.
- Do not execute embedded targets/startup content or upload document data.
  Application checks are isolated and distinct from container verification.
- No SQLite, MCP, network service or new GUI/theme dependency without an explicit
  scope decision. Follow official-upstream, age, hash and security admission gates.
- Runtime/build/dev hash locks admit thirteen packages, including matched Qt
  6.11.2, for development only. Check the manifest before offline installation;
  the release gate rejects automated development evidence. Retain scoped native
  advisory decisions and re-review before font loading, print/PDF, image preview,
  new Qt modules/plugins or wheel changes. See `DEPENDENCY_CANDIDATES.md`.
- Keep docs short and accurate; distinguish implemented from planned behavior.
  Update task evidence/gaps, never claim a GUI, policy-approved release or license
  approval without evidence. Do not commit DGN/workspaces/secrets/build artifacts.
- Build development previews with `build-portable.ps1`; GitHub Actions performs
  exact offline installs, tests, real packaged verification and artifact upload.
  Use `prepare_dependencies.py` for fresh unchanged evidence; never renew review
  timestamps without queries or accept changed advisories without source review.
  Keep both executables and `_internal/` together; preserve receipts and notices.