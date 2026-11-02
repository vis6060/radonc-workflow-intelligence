# Publication security decision

## Local development repository

The original Git history is retained as a private local development record. A prior
commit contains a username-bearing Windows path. It is an acknowledged privacy
disclosure, not an AWS credential or authentication secret. The current tree removes
that path.

## Mandatory public-release restriction

**Do not push the original `master` history. Publish only the reviewed orphan `main`
branch, whose root commit has no parent.**

The sanitized publication process must:

1. create an orphan `main` branch from the reviewed source snapshot;
2. exclude raw and processed patient-level files, generated timelines, local traces,
   caches, environments, credentials, and account identifiers;
3. repeat credential, private-identifier, absolute-path, and restricted-data scans;
4. verify every screenshot uses the built-in synthetic fixture;
5. verify that `main` has exactly one root commit and no parent connection to the
   private development history; and
6. require a final human review before any remote or public release is created.

The original `master` branch and all development commits remain intact locally. A
future publication must push `main` explicitly—never `master`, tags, `--all`,
`--mirror`, or `--force`. M9B does not create a remote or publish source. **Public
GitHub release is NOT STARTED.**
