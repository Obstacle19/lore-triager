# lore-triager

`lore-triager` is an offline CLI for triaging manually downloaded `mbox` archives from `lore.kernel.org` or other `public-inbox` sources.

The intended workflow is simple:

1. Search on the website yourself.
2. Download the resulting `.mbox.gz`.
3. Manually decompress it into `.mbox`.
4. Import that file locally.
5. Run LLM triage on the imported messages.
6. Review the generated Markdown reports in `docs/`.

This project no longer tries to reproduce website search options such as `/all/?q=...`. If you already downloaded and decompressed an `mbox`, that local file is the dataset.

## What `query` and `scope` mean now

`--query` and `--scope` are optional local filters on your imported database.

They are useful only when:

- you imported several datasets into the same database
- you want a second pass of local filtering before sending messages to the LLM

If your downloaded `mbox` already comes from a website search like `rust bug`, you can skip both options and triage the imported dataset directly.

## Minimal workflow

```bash
cd /root/shaoshuai/lore-triager
gzip -dc data/raw/results-rust-bug.mbox.gz > data/raw/results-rust-bug.mbox
PYTHONPATH=src python3 -m mbox_triager init
PYTHONPATH=src python3 -m mbox_triager ingest-mbox data/raw/results-rust-bug.mbox
PYTHONPATH=src python3 -m mbox_triager triage --limit 20
```

## Directory layout

- `src/`: application code
- `data/raw/`: manually downloaded archives and your decompressed `.mbox` files
- `data/main.db`: local SQLite database
- `docs/`: generated triage reports
- `tests/`: test suite

## LLM configuration

Create a local `.env` file:

```bash
cp .env.example .env
```

Then fill in:

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=...
OPENAI_OUTPUT_MODE=auto
```

`OPENAI_OUTPUT_MODE`:

- `auto`: try structured schema first, then fall back to more compatible JSON modes
- `json_schema`: require structured schema output
- `json_object`: require JSON object mode
- `plain`: prompt for JSON without `response_format`

If `OPENAI_API_KEY` or `OPENAI_MODEL` is missing, the tool falls back to a heuristic classifier.

## Commands

### Initialize

```bash
PYTHONPATH=src python3 -m mbox_triager init
```

Creates the database and output directories.

### Decompress and import downloaded archives

```bash
gzip -dc data/raw/results-rust-bug.mbox.gz > data/raw/results-rust-bug.mbox
PYTHONPATH=src python3 -m mbox_triager ingest-mbox data/raw/results-rust-bug.mbox
```

`ingest-mbox` only accepts a decompressed `.mbox`.

Use `--list-name` only when the imported file does not contain a useful `List-Id` and you want to force a local label:

```bash
PYTHONPATH=src python3 -m mbox_triager ingest-mbox data/raw/foo.mbox --list-name rust-for-linux
```

### Inspect imported messages

```bash
PYTHONPATH=src python3 -m mbox_triager search --limit 10
PYTHONPATH=src python3 -m mbox_triager search --query "unsafe" --limit 20
PYTHONPATH=src python3 -m mbox_triager search --scope rust-for-linux --limit 20
```

If `--query` is omitted, the command simply lists recent imported messages.

### Run triage

```bash
PYTHONPATH=src python3 -m mbox_triager triage --limit 20
```

This is the normal command when your downloaded `mbox` is already the dataset you want to analyze.

Optional local filtering is still available:

```bash
PYTHONPATH=src python3 -m mbox_triager triage --query "unsafe" --limit 20
PYTHONPATH=src python3 -m mbox_triager triage --scope rust-for-linux --limit 20
```

### Inspect runtime configuration

```bash
PYTHONPATH=src python3 -m mbox_triager doctor
```

## Notes

- The default database path is `data/main.db`.
- If you want to keep different downloaded datasets separate, use a different database per dataset:

```bash
LORE_BUG_DB_PATH=data/results-rust-bug.db PYTHONPATH=src python3 -m mbox_triager init
gzip -dc data/raw/results-rust-bug.mbox.gz > data/raw/results-rust-bug.mbox
LORE_BUG_DB_PATH=data/results-rust-bug.db PYTHONPATH=src python3 -m mbox_triager ingest-mbox data/raw/results-rust-bug.mbox
LORE_BUG_DB_PATH=data/results-rust-bug.db PYTHONPATH=src python3 -m mbox_triager triage --limit 50
```

## Development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
