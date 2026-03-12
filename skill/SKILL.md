# OpenRouter Job Runner Skill

> Give it a job. It finds the best LLM. It runs it.

## What This Does

Queries the full OpenRouter model catalog (400+ models), analyzes what your task needs (modalities, capabilities, budget), picks the optimal model, and executes it.

This is NOT like `openrouter/auto` (which routes across ~6 curated models). This searches the **entire catalog** and filters/ranks based on what the task actually requires.

## Prerequisites

- `OPENROUTER_API_KEY` environment variable set
- Python 3.8+ with `requests` installed
- Script location: `~/.openclaw/skills/openrouter-jobrunner/`

## Usage

### Find the best model (dry run)
```bash
./jobrunner.sh "Write a Solidity smart contract" --dry-run --verbose
```

### Execute a task
```bash
./jobrunner.sh "Write a haiku about Ethereum gas fees"
```

### With media inputs
```bash
# Image analysis
./jobrunner.sh "Describe this image" --image https://example.com/photo.jpg

# Video analysis
./jobrunner.sh "Summarize this video" --video https://example.com/clip.mp4

# Audio transcription
./jobrunner.sh "Transcribe this" --audio https://example.com/audio.mp3

# File analysis
./jobrunner.sh "Summarize this PDF" --file report.pdf
```

### Budget control
```bash
# Free models only
./jobrunner.sh "Quick question" --budget free

# Cheapest option
./jobrunner.sh "Translate this" --budget cheap

# Best capability
./jobrunner.sh "Complex analysis" --budget best
```

### Preference boosts
```bash
# Coding-optimized model
./jobrunner.sh "Write a React component" --prefer coding

# Reasoning-optimized model
./jobrunner.sh "Prove this theorem" --prefer reasoning

# Speed-optimized model
./jobrunner.sh "Quick translation" --prefer fast
```

### Image generation
```bash
./jobrunner.sh "Generate pixel art of a lobster" --output-modality image
```

### JSON output (for piping)
```bash
./jobrunner.sh "Explain monads" --json | jq .model
```

### Force a specific model
```bash
./jobrunner.sh "Hello" --model anthropic/claude-sonnet-4
```

## CLI Flags

| Flag | Effect |
|---|---|
| `--budget free\|cheap\|best` | Budget mode |
| `--prefer coding\|reasoning\|fast` | Preference boost |
| `--input-modality X` | Force input modality filter |
| `--output-modality X` | Force output modality filter |
| `--min-context N` | Minimum context window |
| `--max-input-cost N` | Max $/M input tokens |
| `--image URL` | Image URL (repeatable) |
| `--video URL` | Video URL (repeatable) |
| `--audio URL` | Audio URL (repeatable) |
| `--file PATH` | File path or URL (repeatable) |
| `--dry-run` | Show model, don\'t execute |
| `--verbose` | Show selection reasoning |
| `--json` | JSON output |
| `--system TEXT` | System prompt |
| `--model ID` | Force specific model |

## Python API

```python
from jobrunner import JobRunner

runner = JobRunner(api_key="sk-or-...", verbose=True)

# Find best model
match = runner.find_model("Generate pixel art", output_modality="image")
print(f"Best model: {match.id}")

# Find and execute
result = runner.run("Write a haiku about Ethereum gas fees")
print(result.content)
print(f"Model: {result.model} | Cost: ${result.cost:.6f}")
```

## Output Behavior

- **Result content** → stdout (clean for piping)
- **Verbose/status info** → stderr
- **JSON mode** → structured output to stdout

## How Model Selection Works

1. **Task Analysis** — detects required modalities from keywords + flags
2. **Hard Filters** — modality match, context window, cost limits
3. **Soft Scoring** — preference boosts, provider reputation, capability
4. **Ranking** — sorted by composite score
5. **Execution** — top-ranked model runs the task
