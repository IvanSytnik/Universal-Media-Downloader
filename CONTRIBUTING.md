# Contributing

Thanks for taking the time to look at Universal Media Downloader. This
guide covers the local setup, the checks CI runs, the commit format, and
the two kinds of extension the architecture expects: a new source
platform and a new port.

Before you start:

- Security problems go through [SECURITY.md](SECURITY.md), not a public issue.
- Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
- For anything larger than a small fix, open an issue first so the
  approach can be agreed before you write the code.

## Development environment

Requirements:

- **Python 3.13** (`requires-python = ">=3.13"` in `pyproject.toml`).
- **ffmpeg** on `PATH`. `tests/unit/test_media_facts.py` runs `ffprobe`
  on a real clip and is skipped without it, and CI fails on unexpected
  skips.
- **Docker with Compose v2**, only for running the bot itself and for the
  PostgreSQL migration tests.
- Optionally **[uv](https://docs.astral.sh/uv/)**, which installs exactly
  the versions in `uv.lock`, as CI and the Docker image do.

### With the Makefile

The local `make` targets run against the active Python environment
(`PYTHON ?= python3`), so create and activate a virtual environment first:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
make install        # pip install -e ".[dev]"
make help           # list all targets
```

Without activating the environment, point the targets at it instead:
`make PYTHON=.venv/bin/python test`.

`make install` resolves dependencies from the version ranges in
`pyproject.toml`, not from `uv.lock`. If something passes locally but
fails in CI, reinstall from the lock file to get the CI versions.

### With uv (same versions as CI)

```bash
uv sync --locked --extra dev
```

`--locked` fails when `uv.lock` is out of date with `pyproject.toml`. If
you change dependencies, run `uv lock` and commit the updated `uv.lock`.
After `uv sync`, the `make` targets work with `PYTHON=.venv/bin/python`
or inside the activated `.venv`.

## Tests and linters

| Command | What it runs |
|---|---|
| `make lint` | `ruff check`, `ruff format --check` and `mypy --strict` on `src` and `tests/unit/test_ytdlp_downloader.py` |
| `make format` | `ruff format` and `ruff check --fix` on `src` and `tests` |
| `make test` | the full `pytest` suite |
| `make test-cov` | the suite with the 90% coverage gate on `src/domain` and `src/application` |

Before opening a pull request, run:

```bash
make lint test-cov
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the
same checks from `uv.lock` and also:

- fails the test job on any skipped test except the PostgreSQL migration
  tests;
- runs those migration tests against PostgreSQL 16 in a separate job,
  which fails if they are skipped;
- builds the Docker image from `infra/docker/bot.Dockerfile`.

### Migration tests

The migration tests are opt-in. Point them at a PostgreSQL server with
`UMD_MIGRATION_TEST_PG=host:port`. Credentials come from
`POSTGRES_USER` / `POSTGRES_PASSWORD` and default to `umd` / `umd`. The
Compose stack publishes PostgreSQL on `127.0.0.1:${HOST_POSTGRES_PORT:-5433}`:

```bash
docker compose up -d postgres
UMD_MIGRATION_TEST_PG=127.0.0.1:5433 python -m pytest -v \
  tests/integration/test_migration_0005.py tests/integration/test_migration_0006.py
```

### Guards that run as tests

A few project rules are enforced by tests, so breaking one shows up as a
test failure rather than a review comment:

| Test | Rule |
|---|---|
| `tests/unit/test_architecture.py` | the dependency rule between layers (see below) |
| `tests/unit/test_no_cyrillic_literals.py` | no Cyrillic in code: user-facing text lives in `locales/` |
| `tests/unit/test_i18n.py` | `locales/en` and `locales/ru` have the same keys |
| `tests/unit/test_env_example.py` | every setting in `Settings` is documented in `.env.example` |

### Running the bot locally

See [Quick start](README.md#quick-start) in the README. The Compose
shortcuts:

| Command | What it does |
|---|---|
| `make up` | build and start the stack in the background |
| `make logs` | follow the `bot` and `worker` logs |
| `make migrate` | apply Alembic migrations (one-shot `migrate` service) |
| `make down` | stop the stack; volumes are kept |

Changes to start-up, migrations or extraction need a live run in Docker
as well as the unit tests, because unit tests check the yt-dlp options,
not the file that comes out ([architecture.md, Testing
strategy](docs/architecture.md#testing-strategy)).

## Code conventions

- **Layers.** `domain` imports only the standard library and itself;
  `application` imports `domain` and `src.shared`; `presentation` imports
  anything except `src.infrastructure`; `infrastructure` implements domain
  ports. The two documented exceptions are in
  [architecture.md](docs/architecture.md#layers-and-the-dependency-rule).
- **User-facing text** goes into `locales/en/messages.ftl` **and**
  `locales/ru/messages.ftl` with the same key, never into Python code.
  Errors carry an `error_key`, and the presentation layer or the worker
  renders it. Raw exception text goes to logs, not to the user
  ([architecture.md, Errors and localization](docs/architecture.md#errors-and-localization)).
- **Settings.** A new setting goes into `src/config/settings.py` and
  `.env.example`. If users are likely to change it, add it to the
  configuration table in the README too.
- **Migrations** go into `infra/alembic/versions/` with the next number
  (`0007_...`). A migration that changes existing data or constraints
  needs an upgrade/downgrade test against PostgreSQL, like
  `tests/integration/test_migration_0006.py`.
- **Decisions** that were debated or are easy to undo by accident get an
  ADR in `docs/adr/`, numbered after the last one.
- Comments and documentation are in English.

## Adding a source platform

Downloading is done by yt-dlp, so a new site needs no new downloader,
only configuration, tests and a live check. Assume the site is one yt-dlp
already supports:

1. **Allow the domain.** Add it to the default `allowed_domains` in
   `src/config/settings.py` and to `ALLOWED_DOMAINS` in `.env.example`.
   Matching is per label, so `example.com` also covers `www.example.com`.
   If a subdomain must stay out, add it to `blocked_domains` /
   `BLOCKED_DOMAINS`. Cover the new host in `tests/unit/test_url_allowlist.py`.
   `/help` lists platforms from the allowlist, so it needs no change.
2. **Map its errors.** yt-dlp reports most failures as `DownloadError`,
   and `src/infrastructure/downloader/error_classifier.py` maps message
   fragments (`_SIGNATURES`) to domain exceptions. If the site words
   "private", "geo-blocked" or "removed" differently, add the fragments
   there and a case to `tests/unit/test_error_classifier.py`. Unknown
   failures fall back to the generic `error-extraction-failed` message.
3. **Pin format selection on real data.** Add a capture to
   `tests/fixtures/ytdlp_formats/`: `<name>.json` (an `extract_info`
   result trimmed to `extractor_key` and the format fields that drive
   sorting, as in the existing files) and `<name>.formats.txt` (the
   `yt-dlp -F` listing). Then add a case to
   `tests/unit/test_format_selection_fixtures.py`, which runs yt-dlp's
   own selector with the production options and checks the quality
   buttons `FormatPolicy` offers.
4. **Restrict formats by configuration, not code.** If a format makes no
   sense for the site, use the `DISABLED_FORMATS` kill switch, keyed by
   the lowercased yt-dlp extractor key
   ([ADR 0002](docs/adr/0002-format-policy-kill-switch.md)).
5. **Run it live** in Docker with a real link, and note anything the bot
   cannot do on that site under *Limitations* in the README.

## Adding a port

Ports are `Protocol`s in `src/domain/interfaces/`; the list is in
[architecture.md, Ports](docs/architecture.md#ports). To add one:

1. Define the `Protocol` in `src/domain/interfaces/`, using only domain
   types in its signatures.
2. Implement the adapter in `src/infrastructure/<area>/`.
3. Wire it in the composition roots: `src/main.py` and
   `src/composition.py` for the bot, and
   `src/infrastructure/queue/worker_settings.py` for the worker.
4. Give the application layer a fake in the tests. Use cases are unit
   tested against fakes, and the coverage gate applies to `domain` and
   `application`.

`tests/unit/test_architecture.py` fails if the new code imports across
layers the wrong way.

## Commits and pull requests

Commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<optional scope>): <summary in the imperative, lower case>
```

Types used in this repository: `feat`, `fix`, `docs`, `test`, `refactor`,
`build`, `ci`, `style`, `chore`. Scopes name the area touched, for example
`feat(worker): …`, `fix(i18n): …`, `build(compose): …`. Keep each commit
to one change that builds and passes the tests.

Pull requests target `main`. In the pull request:

- describe what changed and why, and link the issue;
- add an entry under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md)
  for anything a user or operator would notice. The changelog follows
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
  project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html);
- confirm that `make lint test-cov` passes and, where it applies, that
  you ran the change live in Docker.

By contributing you agree that your contribution is licensed under the
[MIT License](LICENSE).
