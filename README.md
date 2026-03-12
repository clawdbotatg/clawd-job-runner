# 🦞 clawd-job-runner

> Give it a job. It finds the best LLM. It runs it.

A CLI tool that queries the **full OpenRouter model catalog** (400+ models), analyzes what your task needs, picks the optimal model, and executes it.

This is NOT like `openrouter/auto` (which routes across ~6 curated models). This searches the **entire catalog** and filters/ranks based on what the task actually requires — modalities, capabilities, budget, and preferences.

## Quick Start

```bash
# Clone
git clone https://github.com/clawdbotatg/clawd-job-runner.git
cd clawd-job-runner

# Install dependency
pip install requests

# Set your API key
cp .env.example .env
# Edit .env with your OpenRouter API key

# Run it
./jobrunner.sh "Write a haiku about Ethereum gas fees"
```

## How It Works

```
Your Task
   │
   ▼
Task Analyzer        ─ detect required modalities, infer capabilities
   │
   ▼
Model Catalog        ─ GET /api/v1/models → live 400+ model list
   │
   ▼
Ranker               ─ filter by modality → apply budget/prefs → rank
   │
   ▼
Execute              ─ POST /api/v1/chat/completions with chosen model
   │
   ▼
Result               ─ output + metadata (model, cost, tokens)
```

## Examples

### Basic usage
```bash
$ ./jobrunner.sh "Write a haiku about Ethereum gas fees"
Gas prices spike high
Validators feast on fees
My wallet weeps dry
```

### See model selection reasoning
```bash
$ ./jobrunner.sh "Write a Solidity smart contract for an ERC-721" --prefer coding --verbose

📋 Task Analysis:
   Input:  text
   Output: text
   🔧 Coding preference detected

🔍 Fetching OpenRouter model catalog...
📦 Found 344 models

🏆 Top 5 matches:
   👉 1. Anthropic: Claude Opus 4
        anthropic/claude-opus-4 | ctx: 200,000 | $15.00/M
        Score: 137.0 (coding boost +25; top provider +5)
     2. Anthropic: Claude Sonnet 4
        anthropic/claude-sonnet-4 | ctx: 200,000 | $3.00/M
        Score: 133.5 (coding boost +25; top provider +5)
   ...

✅ Selected: Anthropic: Claude Opus 4 (anthropic/claude-opus-4)
🚀 Executing with anthropic/claude-opus-4...
```

### Image analysis
```bash
$ ./jobrunner.sh "What's in this image?" --image https://example.com/photo.jpg --verbose

📋 Task Analysis:
   Input:  image, text
   Output: text
```

### Image generation
```bash
$ ./jobrunner.sh "Generate pixel art of a crab" --output-modality image
```

### Video analysis
```bash
$ ./jobrunner.sh "Summarize this video" --video https://example.com/clip.mp4
```

### Audio transcription
```bash
$ ./jobrunner.sh "Transcribe this recording" --audio https://example.com/audio.mp3
```

### Budget control
```bash
# Free models only
$ ./jobrunner.sh "Quick question" --budget free

# Cheapest option
$ ./jobrunner.sh "Translate this paragraph" --budget cheap

# Best capability (largest context, most features)
$ ./jobrunner.sh "Analyze this entire codebase" --budget best --min-context 200000
```

### Dry run — see what model would be picked
```bash
$ ./jobrunner.sh "Complex math proof" --prefer reasoning --budget best --dry-run
x-ai/grok-4.20-multi-agent-beta

📊 xAI: Grok 4.20 Multi-Agent Beta
   Context: 2,000,000 tokens
   Cost: $2.00/M input tokens
   In:  text, image
   Out: text
```

### JSON output (for piping)
```bash
$ ./jobrunner.sh "Explain monads" --json | jq .model
"anthropic/claude-sonnet-4"
```

### Force a specific model
```bash
$ ./jobrunner.sh "Hello" --model anthropic/claude-sonnet-4
```

### Pipe from stdin
```bash
$ echo "Explain this error" | ./jobrunner.sh
```

### Local file analysis
```bash
$ ./jobrunner.sh "Summarize this document" --file report.pdf
```

## CLI Flags

| Flag | Effect |
|---|---|
| `--budget free\|cheap\|best` | Budget mode for model selection |
| `--prefer coding\|reasoning\|fast` | Preference boost |
| `--input-modality X` | Force input modality filter (text/image/video/audio/file) |
| `--output-modality X` | Force output modality filter (text/image/audio) |
| `--min-context N` | Minimum context window size |
| `--max-input-cost N` | Maximum input cost in $/million tokens |
| `--image URL` | Image URL to include (repeatable) |
| `--video URL` | Video URL to include (repeatable) |
| `--audio URL` | Audio URL to include (repeatable) |
| `--file PATH` | File path or URL to include (repeatable) |
| `--dry-run` | Show selected model, don't execute |
| `--verbose, -v` | Show full model selection reasoning (stderr) |
| `--json` | Output result as JSON |
| `--system TEXT` | System prompt to prepend |
| `--model ID` | Force a specific model (skip selection) |

## Python API

```python
from jobrunner import JobRunner

runner = JobRunner(api_key="sk-or-...", verbose=True)

# Find best model without executing
match = runner.find_model(
    task="Generate a pixel art sprite sheet",
    output_modality="image",
    max_input_cost=5.0,
)
print(f"Best: {match.id} (score: {match.score})")

# Find and execute
result = runner.run("Write a haiku about Ethereum gas fees")
print(result.content)
print(f"Model: {result.model} | Cost: ${result.cost:.6f}")

# With media
result = runner.run(
    "Describe this image",
    media_urls={"image": ["https://example.com/photo.jpg"]},
    image=True,
)

# Budget mode
result = runner.run("Quick task", budget="free")
```

## Model Selection Algorithm

1. **Task Analysis** — keyword/heuristic detection on the task string + flags
2. **Hard Filters:**
   - Input modality match (all required modalities must be supported)
   - Output modality match
   - Minimum context window
   - Maximum input cost
   - Free-only filter
3. **Soft Scoring:**
   - Budget mode adjustments (cheap → lower cost wins, best → bigger context wins)
   - Preference boosts (coding/reasoning/fast → relevant model families get +25)
   - Provider reputation (+5 for top providers)
   - Expiration penalty (-10 for expiring models)
4. **Ranking** — sorted by composite score, best first

## Output Behavior

- **Result content** → `stdout` (clean for piping)
- **Verbose/status info** → `stderr`
- **JSON mode** → structured output to `stdout`

This means you can pipe results cleanly:
```bash
./jobrunner.sh "Write a Python script" > output.py
./jobrunner.sh "Explain X" --json | jq .cost
```

## Requirements

- Python 3.8+
- `requests` package
- OpenRouter API key ([get one here](https://openrouter.ai/keys))

## Install

```bash
git clone https://github.com/clawdbotatg/clawd-job-runner.git
cd clawd-job-runner
pip install -r requirements.txt
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env
```

### As an OpenClaw Skill

```bash
mkdir -p ~/.openclaw/skills/openrouter-jobrunner
cp jobrunner.py skill/SKILL.md ~/.openclaw/skills/openrouter-jobrunner/
cp jobrunner.sh ~/.openclaw/skills/openrouter-jobrunner/
```

## License

MIT — see [LICENSE](LICENSE)
