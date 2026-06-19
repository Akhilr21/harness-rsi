# harness-rsi

A minimal CLI lab for measuring harness-level improvement with a fixed model.

The first goal is deliberately small: run a model through versioned harness
configs, capture traces, evaluate outputs, ask for a harness patch proposal, and
explicitly promote or reject the candidate.

```text
task input -> prompt/program -> model -> trace -> eval -> proposal -> promote/reject
```

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Development workflow

Use PRs for changes going forward. Keep `main` as the stable branch, do active
work on `dev` or short-lived feature branches, and merge only after review.

## Quickstart

Initialize local harness artifacts:

```bash
harness-rsi init
```

Run the sample tasks without calling an API:

```bash
harness-rsi run --mock
```

Ask the model to propose a harness improvement from the latest run:

```bash
harness-rsi improve --mock
```

Promote or reject the proposal:

```bash
harness-rsi promote .rsi/proposals/<proposal-id>.json
harness-rsi reject .rsi/proposals/<proposal-id>.json --reason "overfit to toy task"
```

## Benchmark quickstart

Create the first synthetic benchmark environment and baseline harness:

```bash
harness-rsi benchmark init
```

Create a candidate `H1` from a proposal, then run `H0` and `H1` on heldout:

```bash
harness-rsi harness create-candidate \
  --parent H0 \
  --candidate H1 \
  --proposal .rsi/proposals/<proposal-id>.json

harness-rsi benchmark run --split heldout --harness H0 --mock
harness-rsi benchmark run --split heldout --harness H1 --mock
```

Compare and gate the runs:

```bash
harness-rsi benchmark compare \
  --baseline-run .rsi/runs/<h0-run> \
  --candidate-run .rsi/runs/<h1-run>

harness-rsi benchmark gate \
  --baseline-run .rsi/runs/<h0-run> \
  --candidate-run .rsi/runs/<h1-run> \
  --min-pass-rate-delta 0.01 \
  --max-allowed-drop 0
```

The benchmark layer enforces fixed-model comparison, matching task order, and
matching task/evaluator definitions.

Promote the existing candidate only after a promote gate:

```bash
harness-rsi harness promote \
  --candidate H1 \
  --gate .rsi/gates/<gate-id>.json
```

This mutates `.rsi/harnesses/H1.json` from `status: candidate` to
`status: promoted` and records lineage back to the parent, proposal, gate,
benchmark split, and run evidence. Promotion refuses rejected gates,
parent/candidate mismatches, missing or mismatched behavior digests, existing
promotions, and model changes.

## Real model runs

Set an API key and omit `--mock`:

```bash
export OPENAI_API_KEY=...
harness-rsi run --model gpt-5.5
harness-rsi improve --model gpt-5.5
```

`gpt-5.5` is the default model in the starter config, but every command keeps it
overrideable so experiments can pin a model explicitly.

## Artifact layout

`harness-rsi init` creates:

```text
.rsi/
  harness.json          # model, prompt, tools, retry policy
  harnesses/H0.json     # versioned baseline harness
  benchmarks/synthetic/ # train, heldout, regression splits
  tasks/sample.jsonl    # small task input suite
  memory/learnings.md   # promoted learnings the harness reads
  runs/                 # trace + eval artifacts
  proposals/            # candidate harness patches
  decisions/            # promotion/rejection records
  gates/                # benchmark promotion gate decisions
```

## What each piece means

- **Task input**: JSONL tasks with `id`, `instruction`, and `eval`.
- **Tool access**: explicit config for shell availability and allowed commands.
- **Prompt/program**: the harness system prompt in `.rsi/harness.json`.
- **Memory/learnings**: promoted notes in `.rsi/memory/learnings.md`.
- **Retry policy**: `max_retries` in `.rsi/harness.json`.
- **Trace capture**: each attempt is written to `.rsi/runs/<run-id>/trace.jsonl`.
- **Evaluation**: simple deterministic checks in task `eval`.
- **Patch proposal**: `improve` writes a candidate JSON file.
- **Promotion/rejection**: `promote` appends accepted changes; `reject` records why.

This is not an agent framework. It is the smallest useful experiment engine for
the question: with the model fixed, can the harness improve?

## Tool calls

The raw tool protocol is intentionally primitive. If shell access is enabled in
`.rsi/harness.json`, the model may return:

```json
{"tool":{"name":"shell","command":"python --version"}}
```

The harness checks `tools.shell`, `tools.allowed_commands`, and
`tools.timeout_seconds`, writes the observation to the trace, and gives the
observation back to the model on the next attempt.

## Design docs

- `docs/evaluation-architecture.md`
- `docs/change-management.md`
