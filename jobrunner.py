#!/usr/bin/env python3
"""
clawd-job-runner — Give it a job. It finds the best LLM. It runs it.

Queries the full OpenRouter model catalog (400+ models), analyzes what your
task needs, picks the optimal model, and executes it.
"""

import argparse
import json
import os
import re
import sys
import base64
import mimetypes
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Tuple

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

__version__ = "1.0.0"

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
MODELS_ENDPOINT = f"{OPENROUTER_API_BASE}/models"
COMPLETIONS_ENDPOINT = f"{OPENROUTER_API_BASE}/chat/completions"

# ─── Keyword heuristics for task analysis ───

IMAGE_INPUT_KEYWORDS = [
    "this image", "this photo", "this picture", "this screenshot",
    "the image", "the photo", "the picture", "the screenshot",
    "attached image", "look at", "what's in this", "describe this",
    "analyze this image", "ocr", "read the text in",
]
VIDEO_INPUT_KEYWORDS = [
    "this video", "this clip", "the video", "the footage",
    "watch this", "analyze this video", "summarize this video",
]
AUDIO_INPUT_KEYWORDS = [
    "this audio", "transcribe", "this recording", "this podcast",
    "listen to", "the audio", "speech to text", "voice memo",
]
IMAGE_OUTPUT_KEYWORDS = [
    "generate image", "create image", "draw", "make an image",
    "pixel art", "illustration", "generate a picture", "create a photo",
    "design a logo", "make a poster", "generate art", "create art",
    "image of", "picture of", "photo of",
]
CODING_KEYWORDS = [
    "write code", "code", "solidity", "script", "function", "program",
    "implement", "debug", "refactor", "api", "python", "javascript",
    "typescript", "rust", "golang", "sql", "html", "css", "react",
    "smart contract", "deploy", "compile", "algorithm", "data structure",
]
REASONING_KEYWORDS = [
    "analyze", "explain", "reason", "think through", "step by step",
    "why", "compare", "evaluate", "assess", "critique", "proof",
    "logic", "mathematical", "theorem", "derive", "deduce",
]


@dataclass
class TaskRequirements:
    """Detected requirements for a task."""
    input_modalities: List[str] = field(default_factory=lambda: ["text"])
    output_modalities: List[str] = field(default_factory=lambda: ["text"])
    prefer_coding: bool = False
    prefer_reasoning: bool = False
    prefer_fast: bool = False
    min_context: Optional[int] = None
    max_input_cost: Optional[float] = None
    budget: Optional[str] = None  # free, cheap, best


@dataclass
class ModelMatch:
    """A ranked model match."""
    id: str
    name: str
    score: float
    context_length: int
    input_modalities: List[str]
    output_modalities: List[str]
    prompt_cost: float  # per token (not per million)
    completion_cost: float
    max_completion_tokens: Optional[int] = None
    supported_parameters: List[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class JobResult:
    """Result from executing a job."""
    content: str
    model: str
    cost: float
    tokens_in: int
    tokens_out: int
    reasoning: Optional[str] = None
    image_urls: List[str] = field(default_factory=list)


def _log(msg: str, verbose: bool = True):
    """Print to stderr for verbose output."""
    if verbose:
        print(msg, file=sys.stderr)


def _matches_any(text: str, keywords: List[str]) -> bool:
    """Check if text contains any of the keywords (case-insensitive)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


class JobRunner:
    """Main job runner class — finds the best model and executes tasks."""

    def __init__(self, api_key: Optional[str] = None, verbose: bool = False):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.verbose = verbose
        self._models_cache: Optional[List[Dict]] = None

    def fetch_models(self) -> List[Dict[str, Any]]:
        """Fetch the full model catalog from OpenRouter."""
        if self._models_cache is not None:
            return self._models_cache

        _log("🔍 Fetching OpenRouter model catalog...", self.verbose)
        try:
            resp = requests.get(MODELS_ENDPOINT, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            self._models_cache = data.get("data", [])
            _log(f"📦 Found {len(self._models_cache)} models", self.verbose)
            return self._models_cache
        except requests.RequestException as e:
            _log(f"❌ Failed to fetch models: {e}", True)
            return []

    def analyze_task(self, task: str, flags: Optional[Dict[str, Any]] = None) -> TaskRequirements:
        """Analyze a task string to detect required modalities and capabilities."""
        flags = flags or {}
        reqs = TaskRequirements()

        # Input modalities
        input_mods = set(["text"])
        if flags.get("image") or _matches_any(task, IMAGE_INPUT_KEYWORDS):
            input_mods.add("image")
        if flags.get("video") or _matches_any(task, VIDEO_INPUT_KEYWORDS):
            input_mods.add("video")
        if flags.get("audio") or _matches_any(task, AUDIO_INPUT_KEYWORDS):
            input_mods.add("audio")
        if flags.get("file"):
            input_mods.add("file")
        # Explicit overrides
        if flags.get("input_modality"):
            input_mods.add(flags["input_modality"])
        reqs.input_modalities = sorted(input_mods)

        # Output modalities
        output_mods = set(["text"])
        if _matches_any(task, IMAGE_OUTPUT_KEYWORDS):
            output_mods.add("image")
        if flags.get("output_modality"):
            output_mods.add(flags["output_modality"])
        reqs.output_modalities = sorted(output_mods)

        # Preferences
        prefer = flags.get("prefer", "")
        reqs.prefer_coding = prefer == "coding" or _matches_any(task, CODING_KEYWORDS)
        reqs.prefer_reasoning = prefer == "reasoning" or _matches_any(task, REASONING_KEYWORDS)
        reqs.prefer_fast = prefer == "fast"

        # Constraints
        reqs.min_context = flags.get("min_context")
        reqs.max_input_cost = flags.get("max_input_cost")
        reqs.budget = flags.get("budget")

        return reqs

    def rank_models(self, models: List[Dict], reqs: TaskRequirements) -> List[ModelMatch]:
        """Filter and rank models based on requirements."""
        candidates = []

        for m in models:
            arch = m.get("architecture", {})
            model_input = arch.get("input_modalities", ["text"])
            model_output = arch.get("output_modalities", ["text"])
            pricing = m.get("pricing", {})
            top = m.get("top_provider", {})

            # Parse costs (stored as string per-token in API)
            try:
                prompt_cost = float(pricing.get("prompt", "0"))
            except (ValueError, TypeError):
                prompt_cost = 0.0
            try:
                completion_cost = float(pricing.get("completion", "0"))
            except (ValueError, TypeError):
                completion_cost = 0.0

            context_length = m.get("context_length", 0) or 0
            max_completion = top.get("max_completion_tokens")

            # ─── Hard filters ───

            # Input modality match: all required input modalities must be supported
            required_input = set(reqs.input_modalities)
            if not required_input.issubset(set(model_input)):
                continue

            # Output modality match
            required_output = set(reqs.output_modalities)
            if not required_output.issubset(set(model_output)):
                continue

            # Min context window
            if reqs.min_context and context_length < reqs.min_context:
                continue

            # Max input cost (per million tokens)
            cost_per_million = prompt_cost * 1_000_000
            if reqs.max_input_cost is not None and cost_per_million > reqs.max_input_cost:
                continue

            # Free only
            if reqs.budget == "free" and prompt_cost > 0:
                continue

            # Skip openrouter/auto — we ARE the router
            if m.get("id", "") == "openrouter/auto":
                continue

            # ─── Scoring ───
            score = 100.0
            reasons = []

            # Budget-based scoring
            if reqs.budget == "cheap":
                # Lower cost = higher score
                if cost_per_million > 0:
                    score -= cost_per_million * 2
                    reasons.append(f"cost: ${cost_per_million:.2f}/M")
                else:
                    score += 50
                    reasons.append("free model +50")
            elif reqs.budget == "best":
                # Larger context + features = higher score
                score += min(context_length / 10000, 50)
                reasons.append(f"ctx: {context_length:,}")
                if max_completion:
                    score += min(max_completion / 5000, 20)
            else:
                # Default: balance quality and cost
                # Quality signal: higher cost usually = better model, but diminishing returns
                # We want the sweet spot: capable but not extravagant
                # Default mode should NOT pick $2/M models for routine tasks
                if cost_per_million == 0:
                    score += 5   # Free: fine but not preferred
                elif cost_per_million <= 0.5:
                    score += 22  # Sweet spot: cheap but solid (Qwen, Gemini Flash, etc.)
                elif cost_per_million <= 1.5:
                    score += 18  # Mid: Haiku, Flash, etc.
                elif cost_per_million <= 3.0:
                    score += 10  # Upper mid: Sonnet range
                elif cost_per_million <= 10.0:
                    score += 4   # Expensive: only if task warrants it
                else:
                    score -= 5   # >$10/M: actively penalize for default mode
                # Context bonus (moderate)
                score += min(context_length / 100000, 10)
                reasons.append(f"${cost_per_million:.2f}/M")

            # Preference boosts
            model_id = m.get("id", "").lower()
            model_name = m.get("name", "").lower()
            supported_params = m.get("supported_parameters", [])

            if reqs.prefer_coding:
                coding_models = ["claude", "gpt", "codestral", "deepseek-coder",
                                 "qwen-coder", "codex", "starcoder", "devstral"]
                if any(cm in model_id for cm in coding_models):
                    score += 25
                    reasons.append("coding boost +25")

            if reqs.prefer_reasoning:
                if "include_reasoning" in supported_params or "reasoning" in supported_params:
                    score += 20
                    reasons.append("reasoning support +20")
                reasoning_models = ["o1", "o3", "o4", "deepseek-r1", "qwq", "grok"]
                if any(rm in model_id for rm in reasoning_models):
                    score += 15
                    reasons.append("reasoning model +15")

            if reqs.prefer_fast:
                fast_models = ["flash", "mini", "haiku", "instant", "nano", "lite"]
                if any(fm in model_id for fm in fast_models):
                    score += 20
                    reasons.append("fast model +20")

            # Penalize deprecated / expiring models
            if m.get("expiration_date"):
                score -= 10
                reasons.append("expiring -10")

            # Slight boost for well-known providers
            top_providers = ["anthropic/", "openai/", "google/", "meta-llama/", "x-ai/", "deepseek/"]
            if any(model_id.startswith(tp) for tp in top_providers):
                score += 5
                reasons.append("top provider +5")

            candidates.append(ModelMatch(
                id=m["id"],
                name=m.get("name", m["id"]),
                score=score,
                context_length=context_length,
                input_modalities=model_input,
                output_modalities=model_output,
                prompt_cost=prompt_cost,
                completion_cost=completion_cost,
                max_completion_tokens=max_completion,
                supported_parameters=supported_params,
                reason="; ".join(reasons) if reasons else "baseline",
            ))

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def execute(self, task: str, model_id: str, media_urls: Optional[Dict[str, List[str]]] = None,
                system_prompt: Optional[str] = None) -> JobResult:
        """Execute a task against a specific model via OpenRouter."""
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set")

        _log(f"🚀 Executing with {model_id}...", self.verbose)

        # Build message content
        content: Any = []

        # Add text
        content.append({"type": "text", "text": task})

        # Add media
        media_urls = media_urls or {}
        for url in media_urls.get("image", []):
            content.append({"type": "image_url", "image_url": {"url": url}})
        for url in media_urls.get("video", []):
            content.append({"type": "video_url", "video_url": {"url": url}})
        for url in media_urls.get("audio", []):
            content.append({"type": "audio_url", "audio_url": {"url": url}})
        for url in media_urls.get("file", []):
            content.append({"type": "file_url", "file_url": {"url": url}})

        # If only text, simplify
        if len(content) == 1 and content[0]["type"] == "text":
            content = task

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content})

        payload = {
            "model": model_id,
            "messages": messages,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/clawdbotatg/clawd-job-runner",
            "X-Title": "clawd-job-runner",
        }

        try:
            resp = requests.post(COMPLETIONS_ENDPOINT, json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise RuntimeError(f"API request failed: {e}")

        # Parse response
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        result_content = message.get("content", "")
        reasoning = message.get("reasoning", None)

        # Handle image output — check for inline images in content
        image_urls = []
        if isinstance(result_content, list):
            # Multi-part response (text + images)
            text_parts = []
            for part in result_content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        image_urls.append(part.get("image_url", {}).get("url", ""))
                else:
                    text_parts.append(str(part))
            result_content = "\n".join(text_parts)
        elif isinstance(result_content, str):
            # Check for image URLs in text (some models return markdown images)
            img_pattern = r'!\[.*?\]\((https?://[^\)]+)\)'
            found = re.findall(img_pattern, result_content)
            image_urls.extend(found)

        # Token usage
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)

        # Cost calculation
        cost = 0.0
        if "total_cost" in usage:
            cost = float(usage["total_cost"])
        else:
            # Estimate from token counts
            models = self.fetch_models()
            for m in models:
                if m["id"] == model_id:
                    pricing = m.get("pricing", {})
                    pc = float(pricing.get("prompt", "0"))
                    cc = float(pricing.get("completion", "0"))
                    cost = (tokens_in * pc) + (tokens_out * cc)
                    break

        return JobResult(
            content=result_content,
            model=model_id,
            cost=cost,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            reasoning=reasoning,
            image_urls=image_urls,
        )

    def find_model(self, task: str, **kwargs) -> Optional[ModelMatch]:
        """Find the best model for a task without executing it."""
        flags = {}
        for key in ["image", "video", "audio", "file", "input_modality",
                     "output_modality", "prefer", "min_context", "max_input_cost", "budget"]:
            if key in kwargs:
                flags[key] = kwargs[key]

        reqs = self.analyze_task(task, flags)

        if self.verbose:
            _log(f"\n📋 Task Analysis:", True)
            _log(f"   Input:  {', '.join(reqs.input_modalities)}", True)
            _log(f"   Output: {', '.join(reqs.output_modalities)}", True)
            if reqs.prefer_coding:
                _log(f"   🔧 Coding preference detected", True)
            if reqs.prefer_reasoning:
                _log(f"   🧠 Reasoning preference detected", True)
            if reqs.prefer_fast:
                _log(f"   ⚡ Speed preference detected", True)
            if reqs.budget:
                _log(f"   💰 Budget: {reqs.budget}", True)
            if reqs.min_context:
                _log(f"   📏 Min context: {reqs.min_context:,}", True)
            if reqs.max_input_cost is not None:
                _log(f"   💲 Max input cost: ${reqs.max_input_cost}/M", True)

        models = self.fetch_models()
        ranked = self.rank_models(models, reqs)

        if not ranked:
            _log("❌ No models matched requirements", True)
            return None

        if self.verbose:
            _log(f"\n🏆 Top 5 matches:", True)
            for i, m in enumerate(ranked[:5]):
                cost_m = m.prompt_cost * 1_000_000
                marker = "👉" if i == 0 else "  "
                _log(f"   {marker} {i+1}. {m.name}", True)
                _log(f"        {m.id} | ctx: {m.context_length:,} | ${cost_m:.2f}/M", True)
                _log(f"        Score: {m.score:.1f} ({m.reason})", True)

        winner = ranked[0]
        _log(f"\n✅ Selected: {winner.name} ({winner.id})", self.verbose)
        return winner

    def run(self, task: str, media_urls: Optional[Dict[str, List[str]]] = None,
            system_prompt: Optional[str] = None, **kwargs) -> JobResult:
        """Find the best model and execute the task."""
        match = self.find_model(task, **kwargs)
        if not match:
            raise RuntimeError("No suitable model found for this task")

        return self.execute(task, match.id, media_urls=media_urls, system_prompt=system_prompt)


# ─── CLI ───

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobrunner",
        description="🦞 clawd-job-runner — Give it a job. It finds the best LLM. It runs it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "Write a haiku about Ethereum gas fees"
  %(prog)s "Describe this image" --image https://example.com/photo.jpg
  %(prog)s "Generate pixel art of a lobster" --output-modality image
  %(prog)s "Write a Solidity contract" --prefer coding --budget cheap
  %(prog)s "Analyze this codebase" --min-context 200000 --prefer reasoning
  %(prog)s "Transcribe this" --audio https://example.com/audio.mp3
  %(prog)s "What's in this video?" --video https://example.com/clip.mp4
  %(prog)s "Summarize this PDF" --file report.pdf
  %(prog)s "Quick translation" --prefer fast --dry-run
  %(prog)s "Complex math proof" --prefer reasoning --budget best --json
        """
    )

    parser.add_argument("task", nargs="?", help="Task description (or pipe via stdin)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    # Budget & preferences
    parser.add_argument("--budget", choices=["free", "cheap", "best"],
                        help="Budget mode: free (free models only), cheap (lowest cost), best (max capability)")
    parser.add_argument("--prefer", choices=["coding", "reasoning", "fast"],
                        help="Preference boost for model selection")

    # Modality overrides
    parser.add_argument("--input-modality", dest="input_modality",
                        choices=["text", "image", "video", "audio", "file"],
                        help="Force input modality filter")
    parser.add_argument("--output-modality", dest="output_modality",
                        choices=["text", "image", "audio"],
                        help="Force output modality filter")

    # Constraints
    parser.add_argument("--min-context", dest="min_context", type=int,
                        help="Minimum context window size")
    parser.add_argument("--max-input-cost", dest="max_input_cost", type=float,
                        help="Maximum input cost in $/million tokens")

    # Media inputs
    parser.add_argument("--image", action="append", default=[],
                        help="Image URL to include (can repeat)")
    parser.add_argument("--video", action="append", default=[],
                        help="Video URL to include (can repeat)")
    parser.add_argument("--audio", action="append", default=[],
                        help="Audio URL to include (can repeat)")
    parser.add_argument("--file", action="append", default=[], dest="files",
                        help="File path or URL to include (can repeat)")

    # Output modes
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Show selected model without executing")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show model selection reasoning on stderr")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output result as JSON")

    # Advanced
    parser.add_argument("--system", type=str, default=None,
                        help="System prompt to prepend")
    parser.add_argument("--model", type=str, default=None,
                        help="Force a specific model (skip selection)")

    return parser


def _file_to_data_url(path: str) -> str:
    """Convert a local file path to a data URL."""
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        mime = "application/octet-stream"
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{data}"


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Get task from args or stdin
    task = args.task
    if not task:
        if not sys.stdin.isatty():
            task = sys.stdin.read().strip()
        else:
            parser.print_help(sys.stderr)
            sys.exit(1)

    if not task:
        print("Error: No task provided", file=sys.stderr)
        sys.exit(1)

    # Build flags
    flags = {}
    if args.image:
        flags["image"] = True
    if args.video:
        flags["video"] = True
    if args.audio:
        flags["audio"] = True
    if args.files:
        flags["file"] = True
    if args.input_modality:
        flags["input_modality"] = args.input_modality
    if args.output_modality:
        flags["output_modality"] = args.output_modality
    if args.prefer:
        flags["prefer"] = args.prefer
    if args.min_context:
        flags["min_context"] = args.min_context
    if args.max_input_cost is not None:
        flags["max_input_cost"] = args.max_input_cost
    if args.budget:
        flags["budget"] = args.budget

    # Build media URLs
    media_urls: Dict[str, List[str]] = {}
    if args.image:
        media_urls["image"] = args.image
    if args.video:
        media_urls["video"] = args.video
    if args.audio:
        media_urls["audio"] = args.audio
    if args.files:
        file_urls = []
        for f in args.files:
            if f.startswith("http://") or f.startswith("https://") or f.startswith("data:"):
                file_urls.append(f)
            elif os.path.exists(f):
                file_urls.append(_file_to_data_url(f))
            else:
                print(f"Warning: File not found: {f}", file=sys.stderr)
                file_urls.append(f)
        media_urls["file"] = file_urls

    runner = JobRunner(verbose=args.verbose or args.dry_run)

    try:
        if args.model:
            # Forced model — skip selection
            if args.dry_run:
                _log(f"✅ Using forced model: {args.model}", True)
                if args.json_output:
                    print(json.dumps({"model": args.model, "dry_run": True}, indent=2))
                sys.exit(0)
            result = runner.execute(task, args.model, media_urls=media_urls,
                                    system_prompt=args.system)
        elif args.dry_run:
            match = runner.find_model(task, **flags)
            if not match:
                sys.exit(1)
            if args.json_output:
                print(json.dumps({
                    "model": match.id,
                    "name": match.name,
                    "score": match.score,
                    "context_length": match.context_length,
                    "input_modalities": match.input_modalities,
                    "output_modalities": match.output_modalities,
                    "prompt_cost_per_million": match.prompt_cost * 1_000_000,
                    "completion_cost_per_million": match.completion_cost * 1_000_000,
                    "reason": match.reason,
                    "dry_run": True,
                }, indent=2))
            else:
                cost_m = match.prompt_cost * 1_000_000
                print(f"{match.id}")
                _log(f"\n📊 {match.name}", True)
                _log(f"   Context: {match.context_length:,} tokens", True)
                _log(f"   Cost: ${cost_m:.2f}/M input tokens", True)
                _log(f"   In:  {', '.join(match.input_modalities)}", True)
                _log(f"   Out: {', '.join(match.output_modalities)}", True)
            sys.exit(0)
        else:
            result = runner.run(task, media_urls=media_urls,
                                system_prompt=args.system, **flags)

        # Output result
        if args.json_output:
            output = {
                "content": result.content,
                "model": result.model,
                "cost": result.cost,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
            }
            if result.reasoning:
                output["reasoning"] = result.reasoning
            if result.image_urls:
                output["image_urls"] = result.image_urls
            print(json.dumps(output, indent=2))
        else:
            # Clean output to stdout
            print(result.content)
            if result.image_urls:
                for url in result.image_urls:
                    print(f"\n🖼️  {url}")
            # Metadata to stderr
            _log(f"\n📊 Model: {result.model}", True)
            _log(f"   Tokens: {result.tokens_in:,} in / {result.tokens_out:,} out", True)
            if result.cost > 0:
                _log(f"   Cost: ${result.cost:.6f}", True)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
