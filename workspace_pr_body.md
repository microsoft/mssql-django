## What

Adds the shared scaffolding for the mssql-django release pipelines
(build-release-package / official-release / dummy-release), mirroring the
in-repo layout used by `microsoft/mssql-python`. **No pipeline definitions are
wired yet** — this PR only lands the variables and SDL/governance config the
pipelines will consume.

| File | Purpose |
|------|---------|
| `OneBranchPipelines/variables/common-variables.yml` | Paths, package identity, pip feed, and `regex_clr.dll` blob coordinates |
| `OneBranchPipelines/variables/onebranch-variables.yml` | OneBranch output dir, SDL/TSA toggles, Linux build image |
| `.config/tsaoptions.json` | TSA (Threat & Security Assessment) config |
| `.config/CredScanSuppressions.json` | CredScan suppression (`CONTRIBUTING.md` example) |
| `es-metadata.yml` | ES / OneBranch governance metadata |

## Why

Part of moving mssql-django's release machinery out of the standalone
`mssql-django-tools` ADO repo and into the product repo (parity with
`microsoft/mssql-python`), so build / release / sync all live and version
alongside the code.

## Notes

- mssql-django is pure-Python, so there is **no native/ODBC/symbol** tooling here.
- `regex_clr.dll` deliberately stays **out of the repo** (security policy) and is
  fetched at build time from the private storage account via **managed-identity
  auth** — wired in the follow-up build-pipeline PR.
- **Draft** until the follow-up build + release pipeline PRs land.
