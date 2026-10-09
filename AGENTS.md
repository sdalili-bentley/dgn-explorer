# DGN Explorer Agent Guide

Read [README.md](README.md) for implemented behavior, [PLAN.md](PLAN.md) for
pending work, and [DEPENDENCY_POLICY.md](DEPENDENCY_POLICY.md) before dependencies.

- Current code: `dgn_folder.py` (CLI/codecs), `dgn_fixture_catalog.py` (optional
  fixture helper), `test_dgn_folder.py` (unittest). No UI or AI skill exists yet.
- Keep one codec implementation; preserve v1/v2, aliases, identities, original
  snapshots, unknown bytes and strict reversible encodings. Never overwrite inputs.
- Every code/UI change adds extensive, reusable tests; every bug fix adds a
  regression. Reuse synthetic fixtures/helpers and test observable behavior.
- Run `python -m unittest discover -s . -p test_dgn_folder.py -v` after changes.
  Sample tests require the specific baseline via `DGN_EXPLORER_SAMPLE`; report
  skipped/platform gaps, never call them passed. UI work also needs Qt tests.
- Do not execute embedded targets/startup content or upload document data.
  Application checks are isolated and distinct from container verification.
- No SQLite, MCP, network service or new GUI/theme dependency without an explicit
  scope decision. Follow official-upstream, age, hash and security admission gates.
- Keep docs short and accurate; distinguish implemented from planned behavior.
  Update task evidence/gaps, never claim a GUI, policy-approved release or license
  approval without evidence. Do not commit DGN/workspaces/secrets/build artifacts.