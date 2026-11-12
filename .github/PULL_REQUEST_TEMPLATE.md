## What and why

<!-- What this pull request changes and why. Link the issue: "Closes #123". -->

## How it was tested

<!-- Tests added or changed; for start-up, migration or extraction changes, the live run in Docker (link, result). -->

## Checklist

- [ ] `make lint test-cov` passes locally
- [ ] Commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) (`feat(worker): …`, `fix(i18n): …`)
- [ ] User-facing text is in both `locales/en/messages.ftl` and `locales/ru/messages.ftl`
- [ ] New settings are in `src/config/settings.py` and `.env.example` (and in the README table if users will change them)
- [ ] Schema changes have a numbered migration in `infra/alembic/versions/`
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]` for anything a user or operator would notice
- [ ] Ran live in Docker (needed for start-up, migration or extraction changes)
