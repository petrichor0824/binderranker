# Contributing to BinderRanker

Thank you for contributing to BinderRanker.

BinderRanker is an interpretable ranking and layered-screening system for
generated protein backbone candidates. Contributions should preserve the
separation between the deterministic scientific workflow and optional
conversational interfaces.

## Project boundaries

The public architecture distinguishes:

- **BinderRanker Engine** — scientific ranking and layered screening;
- **BinderRanker Core** — deterministic workflow, safety, provenance, and
  execution rules;
- **BinderRanker Tool API** — controlled application interface;
- **BinderRanker Agent** — optional conversational interaction.

Generic Agent infrastructure should not be reimplemented through growing
collections of keywords, regular expressions, or special-case natural-language
rules when a mature framework is the more appropriate long-term solution.

The deterministic BinderRanker domain logic remains project-owned.

## Scientific claim policy

Contributions must not present BinderRanker scores as proof of:

- binding affinity;
- protein stability;
- solubility;
- experimental success;
- biological function.

A high score is prioritization evidence within a candidate batch, not
biological proof.

See:

- `docs/SCIENTIFIC_METHOD.md`
- `docs/RESULT_INTERPRETATION.md`
- `docs/PUBLIC_IDENTITY.md`
- `docs/VALIDATION.md`

## Development setup

BinderRanker currently requires Python 3.10 or newer.

Create and activate a virtual environment, then install the development
dependencies:

    python -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"

On Windows, use the equivalent virtual-environment activation command for the
shell being used.

## Tests

Run the complete regression suite with:

    python -m pytest -q

For a focused change, run relevant tests first and then run the complete suite
before submitting the change.

Also check whitespace and patch formatting:

    git diff --check

Modified Python files should be syntax-checked where appropriate:

    python -m py_compile <modified-python-files>

## Release-facing changes

Changes affecting packaging, CLI entry points, packaged resources, or release
metadata should also validate the release artifacts.

Build distributions:

    rm -rf dist build src/*.egg-info
    python -m build --outdir dist

Generate release checksums from inside `dist` so that the manifest contains
asset basenames rather than local paths:

    (
      cd dist
      sha256sum \
        binderranker-*.whl \
        binderranker-*.tar.gz \
        > SHA256SUMS.txt
    )

Then run:

    python scripts/verify_release_assets.py dist

Release candidates should additionally be installed into a clean environment
and tested outside the source checkout.

## CLI compatibility

The canonical public CLI is:

    binderranker

The historical command:

    protein-design-agent

is retained only as a compatibility alias during the v0.3 transition.

New documentation and examples should use `binderranker` unless they are
explicitly documenting compatibility or project history.

The internal Python namespace `protein_design_agent` and the hidden
`.protein-design-agent` workspace path are compatibility implementation
details and must not be renamed casually.

## Backlog policy

Reasonable improvements that are intentionally deferred should be recorded in
`docs/IMPROVEMENT_BACKLOG.md`.

A backlog entry should describe:

- where the issue was found;
- the current problem;
- the suggested direction;
- why it is deferred;
- priority;
- suggested version or reconsideration point.

## Pull requests

Keep changes focused on one coherent problem whenever practical.

A pull request should explain:

- the problem being solved;
- the root cause;
- the behavioral change;
- tests or validation performed;
- compatibility implications;
- any intentionally deferred follow-up work.

Prefer fixing a problem category or root cause over adding isolated
special-case patches.

Do not commit local build products, virtual environments, credentials, API
keys, or generated workspaces.

## Security and credentials

Never commit API keys or private credentials.

Model-assisted features must preserve explicit network authorization and must
not weaken the deterministic approval and execution boundaries.

## License

By contributing to BinderRanker, you agree that your contribution may be
distributed under the project's Apache License 2.0.
