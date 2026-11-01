# Contributing to amigoact-be

Thanks for your interest in contributing! This guide explains how to set up the backend and how to send changes.

By participating in this project, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Prerequisites

- [Python 3.14](https://www.python.org/downloads/) (the version is pinned in `.python-version`)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for dependency and environment management

## Getting Started

```bash
uv sync
uv run main.py
```

`uv sync` creates the virtual environment in `.venv` and installs the locked dependencies from `uv.lock`.

The database schema is defined in [`schema.sql`](../schema.sql). Review it before changing any data model.

## Making Changes

1. Create a branch from the default branch with a short, descriptive name:

   ```bash
   git checkout -b feat/event-registration
   ```

2. Make your changes. Keep each commit focused on one logical change.
3. Check that the project still runs with `uv run main.py`.
4. Push your branch and open a pull request.

## Managing Dependencies

Add or remove packages with uv so that `pyproject.toml` and `uv.lock` stay in sync:

```bash
uv add <package>
uv remove <package>
```

Commit both `pyproject.toml` and `uv.lock` in the same pull request.

## Pull Requests

A good pull request:

- Has a clear title and a description of what changed and why
- Links to the related issue, if one exists
- Explains how you tested the change
- Stays small enough to review in one sitting

## Reporting Bugs and Requesting Features

Open an issue on GitHub. For bugs, include the steps to reproduce, what you expected, and what happened instead.

Do not report security vulnerabilities in public issues. See [SECURITY.md](SECURITY.md) for the private reporting process.
