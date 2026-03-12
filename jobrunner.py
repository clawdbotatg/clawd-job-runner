#!/usr/bin/env python3
"""
clawd-job-runner — Give it a job. It finds the best LLM. It runs it.

Usage as CLI:
    python jobrunner.py "Write a bash script that monitors disk usage"
    python jobrunner.py "Describe this image" --image https://example.com/photo.jpg
    python jobrunner.py "Summarize this video" --video https://example.com/clip.mp4
    python jobrunner.py "Translate to French: Hello world" --budget free
    python jobrunner.py "Write a Solidity ERC-20" --prefer coding --dry-run

Usage as module:
    from jobrunner import JobRunner
    runner = JobRunner(api_key="sk-or-...")
    result = runner.run("Write a haiku about Ethereum gas fees")
    print(result.content)
"""

import sys
import os
import json
import argparse
from dataclasses import dataclass, field
from typing import Optional
import requests


OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


@dataclass
class JobResult:
    content: str
    model: str
    cost: float
    tokens_in: int
    tokens_out: int
    reasoning: str = ""
    image_urls: list = field(default_factory=list)


@dataclass
class ModelMatch:
    id: str
    name: str
    score: float
    input_modalities: list
    output_modalities: list
    context_length: int
    input_cost_per_m: float  # $ per million tokens
    completion_cost_per_m: float
    supports_reasoning: bool
    supports_tools: bool
    is_free: bool
    reason: str = ""


class JobRunner:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set. Pass api_key= or set the env var.")
        self._models_cache = None

    def fetch_models(self) -> list:
        """Fetch full model catalog from OpenRouter."""
        if self._models_cache is not None:
            return self._models_cache
        resp = requests.get(f"{OPENROUTER_API_BASE}/models", timeout=15)
        resp.raise_for_status()
        self._models_cache = resp.json().get("data", [])
        return self._models_cache

    def _parse_model(self, m: dict) -> ModelMatch:
        arch = m.get("architecture", {})
        pricing = m.get("pricing", {})
        supported = m.get("supported_parameters", [])

        input_mods = arch.get("input_modalities", ["text"])
        output_mods = arch.get("output_modalities", ["text"])

        prompt_price = pricing.get("prompt", "0")
        completion_price = pricing.get("completion", "0")
        try:
            input_cost = float(prompt_price) * 1_000_000
        except (ValueError, TypeError):
            input_cost = 0.0
        try:
            completion_cost = float(completion_price) * 1_000_000
        except (ValueError, TypeError):
            completion_cost = 0.0

        is_free = (prompt_price == "0" or input_cost == 0.0)

        return ModelMatch(
            id=m.get("id", ""),
            name=m.get("name", m.get("id", "")),
            score=0.0,
            input_modalities=input_mods,
            output_modalities=output_mods,
            context_length=m.get("context_length", 0),
            input_cost_per_m=input_cost,
            completion_cost_per_m=completion_cost,
            supports_reasoning="reasoning" in supported or "include_reasoning" in supported,
            supports_tools="tools" in supported,
            is_free=is_free,
        )

    def analyze_task(self, task: str, flags: dict) -> dict:
        """
        Heuristic detection of what the task needs.
        Returns a requirements dict.
        """
        task_lower = task.lower()

        # Input modalities needed
        input_mods = {"text"}
        if flags.get("image"):
            input_mods.add("image")
        elif any(kw in task_lower for kw in ["this image", "the image", "in this photo", "picture of", "analyze image"]):
            input_mods.add("image")

        if flags.get("video"):
            input_mods.add("video")
        elif any(kw in task_lower for kw in ["this video", "the video", "footage", "this clip"]):
            input_mods.add("video")

        if flags.get("audio"):
            input_mods.add("audio")
        elif any(kw in task_lower for kw in ["this audio", "transcribe", "audio file", "this recording"]):
            input_mods.add("audio")

        if flags.get("file"):
            input_mods.add("file")
        elif any(kw in task_lower for kw in ["this pdf", "this document", "the file", "this spreadsheet"]):
            input_mods.add("file")

        # Forced modality overrides
        if flags.get("input_modality"):
            for m in flags["input_modality"]:
                input_mods.add(m)

        # Output modalities needed
        output_mods = {"text"}
        if flags.get("output_modality"):
            for m in flags["output_modality"]:
                output_mods.add(m)
        elif any(kw in task_lower for kw in ["generate image", "create image", "draw ", "make an image", "pixel art", "generate a picture"]):
            output_mods.add("image")

        # Preference boosts
        prefer = set()
        if flags.get("prefer"):
            prefer.update(flags["prefer"])
        if any(kw in task_lower for kw in ["write code", "solidity", "function", "bash script", "python script", "implement", "debug", "refactor"]):
            prefer.add("coding")
        if any(kw in task_lower for kw in ["analyze", "reason", "explain", "why does", "think through", "step by step"]):
            prefer.add("reasoning")

        # Budget
        budget = flags.get("budget", "default")

        return {
            "input_modalities": input_mods,
            "output_modalities": output_mods,
            "prefer": prefer,
            "budget": budget,
            "min_context": flags.get("min_context", 0),
            "max_input_cost": flags.get("max_input_cost"),
        }

    def rank_models(self, models: list, req: dict) -> list[ModelMatch]:
        """Filter and rank models based on requirements."""
        parsed = [self._parse_model(m) for m in models]

        # Hard filters
        filtered = []
        for m in parsed:
            if not m.id:
                continue
            # Modality must match
            if not req["input_modalities"].issubset(set(m.input_modalities)):
                continue
            if not req["output_modalities"].issubset(set(m.output_modalities)):
                continue
            # Min context
            if req.get("min_context") and m.context_length < req["min_context"]:
                continue
            # Max input cost
            if req.get("max_input_cost") is not None and not m.is_free:
                if m.input_cost_per_m > req["max_input_cost"]:
                    continue
            # Free filter
            if req["budget"] == "free" and not m.is_free:
                continue
            filtered.append(m)

        # Score
        for m in filtered:
            score = 0.0

            # Preference boosts
            name_lower = (m.name + " " + m.id).lower()
            if "coding" in req["prefer"]:
                if any(kw in name_lower for kw in ["code", "coder", "codex", "qwen", "deepseek", "starcoder", "wizard"]):
                    score += 10
            if "reasoning" in req["prefer"]:
                if m.supports_reasoning:
                    score += 10
                if any(kw in name_lower for kw in ["think", "reason", "o1", "o3", "r1", "sonnet", "opus", "gpt-4"]):
                    score += 5
            if "fast" in req["prefer"]:
                # Favor large completion token limits — approximate by context size
                score += min(m.context_length / 100_000, 10)

            # Context window bonus (log scale)
            if m.context_length > 0:
                import math
                score += math.log10(m.context_length)

            # Tool support bonus
            if m.supports_tools:
                score += 2

            # Budget-based scoring
            if req["budget"] == "cheap" or req["budget"] == "free":
                # Lower cost = higher score
                if m.is_free:
                    score += 50
                elif m.input_cost_per_m > 0:
                    score += max(0, 20 - m.input_cost_per_m)
            elif req["budget"] == "best":
                # Bigger context + more features = better
                score += min(m.input_cost_per_m, 20)  # More expensive often = better
            else:
                # Default: balance — moderate cost models preferred
                if m.is_free:
                    score += 5
                elif 0 < m.input_cost_per_m <= 3:
                    score += 15
                elif 3 < m.input_cost_per_m <= 10:
                    score += 8
                # else expensive, lower score

            m.score = score

        filtered.sort(key=lambda m: m.score, reverse=True)
        return filtered

    def find_model(
        self,
        task: str,
        input_modalities: Optional[list] = None,
        output_modalities: Optional[list] = None,
        max_input_cost: Optional[float] = None,
        budget: str = "default",
        prefer: Optional[list] = None,
        min_context: int = 0,
        verbose: bool = False,
    ) -> Optional[ModelMatch]:
        """Find the best model without executing."""
        flags = {
            "budget": budget,
            "min_context": min_context,
            "max_input_cost": max_input_cost,
            "prefer": prefer or [],
            "input_modality": input_modalities or [],
            "output_modality": output_modalities or [],
        }
        req = self.analyze_task(task, flags)
        models = self.fetch_models()
        ranked = self.rank_models(models, req)

        if verbose:
            print(f"\n🔍 Task analysis:", file=sys.stderr)
            print(f"   Input modalities: {', '.join(sorted(req['input_modalities']))}", file=sys.stderr)
            print(f"   Output modalities: {', '.join(sorted(req['output_modalities']))}", file=sys.stderr)
            if req["prefer"]:
                print(f"   Preferences: {', '.join(sorted(req['prefer']))}", file=sys.stderr)
            print(f"   Budget: {req['budget']}", file=sys.stderr)
            print(f"\n📋 Catalog: {len(models)} models loaded", file=sys.stderr)
            print(f"   After modality filter: {len(ranked)} models", file=sys.stderr)

        if not ranked:
            return None

        best = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None

        if verbose:
            cost_str = "free" if best.is_free else f"${best.input_cost_per_m:.2f}/M input"
            print(f"\n🏆 Selected: {best.id}", file=sys.stderr)
            print(f"   Modalities: {'+'.join(best.input_modalities)}->{'+'.join(best.output_modalities)}", file=sys.stderr)
            print(f"   Cost: {cost_str} | Context: {best.context_length:,}", file=sys.stderr)
            if best.supports_reasoning:
                print(f"   Reasoning: ✓", file=sys.stderr)
            if runner_up:
                ru_cost = "free" if runner_up.is_free else f"${runner_up.input_cost_per_m:.2f}/M"
                print(f"   Runner-up: {runner_up.id} ({ru_cost}, {runner_up.context_length:,} ctx)", file=sys.stderr)

        return best

    def execute(
        self,
        task: str,
        model: ModelMatch,
        image_url: Optional[str] = None,
        video_url: Optional[str] = None,
        audio_url: Optional[str] = None,
        file_path: Optional[str] = None,
        verbose: bool = False,
    ) -> JobResult:
        """Execute the task with the given model."""
        if verbose:
            print(f"\n⚡ Executing with {model.id}...", file=sys.stderr)

        # Build message content
        content = []

        # Add media if provided
        if image_url and "image" in model.input_modalities:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        if video_url and "video" in model.input_modalities:
            content.append({"type": "video_url", "video_url": {"url": video_url}})
        if audio_url and "audio" in model.input_modalities:
            content.append({"type": "audio_url", "audio_url": {"url": audio_url}})

        # Add text
        content.append({"type": "text", "text": task})

        # If only text content, simplify to string
        message_content = content if len(content) > 1 else task

        payload = {
            "model": model.id,
            "messages": [{"role": "user", "content": message_content}],
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/clawdbotatg/clawd-job-runner",
            "X-Title": "clawd-job-runner",
        }

        resp = requests.post(
            f"{OPENROUTER_API_BASE}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()

        # Parse response
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)

        # Calculate cost
        cost = 0.0
        if not model.is_free:
            cost = (tokens_in * model.input_cost_per_m / 1_000_000) + \
                   (tokens_out * model.completion_cost_per_m / 1_000_000)

        # Parse content — handle text and image outputs
        choices = data.get("choices", [])
        text_content = ""
        image_urls = []

        if choices:
            msg = choices[0].get("message", {})
            raw_content = msg.get("content", "")

            if isinstance(raw_content, str):
                text_content = raw_content
            elif isinstance(raw_content, list):
                for part in raw_content:
                    if part.get("type") == "text":
                        text_content += part.get("text", "")
                    elif part.get("type") == "image_url":
                        image_urls.append(part.get("image_url", {}).get("url", ""))

        return JobResult(
            content=text_content,
            model=data.get("model", model.id),
            cost=cost,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            image_urls=image_urls,
        )

    def run(
        self,
        task: str,
        input_modalities: Optional[list] = None,
        output_modalities: Optional[list] = None,
        max_input_cost: Optional[float] = None,
        budget: str = "default",
        prefer: Optional[list] = None,
        min_context: int = 0,
        image_url: Optional[str] = None,
        video_url: Optional[str] = None,
        audio_url: Optional[str] = None,
        file_path: Optional[str] = None,
        verbose: bool = False,
    ) -> JobResult:
        """Find the best model and execute the task."""
        model = self.find_model(
            task=task,
            input_modalities=input_modalities,
            output_modalities=output_modalities,
            max_input_cost=max_input_cost,
            budget=budget,
            prefer=prefer,
            min_context=min_context,
            verbose=verbose,
        )
        if not model:
            raise RuntimeError("No suitable model found for this task with the given constraints.")

        return self.execute(
            task=task,
            model=model,
            image_url=image_url,
            video_url=video_url,
            audio_url=audio_url,
            file_path=file_path,
            verbose=verbose,
        )


def main():
    parser = argparse.ArgumentParser(
        description="clawd-job-runner: Give it a job. It finds the best LLM. It runs it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "Write a bash script that monitors disk usage"
  %(prog)s "Describe what's in this image" --image https://example.com/photo.jpg
  %(prog)s "Summarize this video" --video https://example.com/clip.mp4
  %(prog)s "Translate to French: Hello world" --budget free
  %(prog)s "Write a Solidity ERC-20" --prefer coding --budget cheap
  %(prog)s "Analyze this codebase" --prefer reasoning --min-context 100000
  %(prog)s "Explain quantum computing" --dry-run --verbose
        """,
    )

    parser.add_argument("task", help="The task to run")

    # Media inputs
    parser.add_argument("--image", metavar="URL", help="Image URL to pass to the model")
    parser.add_argument("--video", metavar="URL", help="Video URL to pass to the model")
    parser.add_argument("--audio", metavar="URL", help="Audio URL to pass to the model")
    parser.add_argument("--file", metavar="PATH", help="File path to pass to the model")

    # Budget
    parser.add_argument(
        "--budget",
        choices=["free", "cheap", "best", "default"],
        default="default",
        help="Budget mode: free (only free), cheap (lowest cost), best (most capable), default (balanced)",
    )

    # Preferences
    parser.add_argument(
        "--prefer",
        action="append",
        choices=["coding", "reasoning", "fast"],
        metavar="PREF",
        help="Boost certain model types (coding, reasoning, fast). Can repeat.",
    )

    # Modality overrides
    parser.add_argument(
        "--input-modality",
        action="append",
        metavar="MOD",
        help="Force input modality filter (text/image/video/audio/file). Can repeat.",
    )
    parser.add_argument(
        "--output-modality",
        action="append",
        metavar="MOD",
        help="Force output modality (text/image/audio). Can repeat.",
    )

    # Context / cost
    parser.add_argument("--min-context", type=int, default=0, metavar="N", help="Minimum context window size")
    parser.add_argument("--max-input-cost", type=float, metavar="N", help="Max $/M input tokens (e.g. 1.0)")

    # Output modes
    parser.add_argument("--dry-run", action="store_true", help="Show selected model but don't execute")
    parser.add_argument("--verbose", action="store_true", help="Show full model selection reasoning")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output result as JSON")

    # API key
    parser.add_argument("--api-key", metavar="KEY", help="OpenRouter API key (or set OPENROUTER_API_KEY)")

    args = parser.parse_args()

    # Resolve API key
    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("Error: OPENROUTER_API_KEY not set. Use --api-key or set the env var.", file=sys.stderr)
        sys.exit(1)

    try:
        runner = JobRunner(api_key=api_key)

        flags = {
            "budget": args.budget,
            "prefer": args.prefer or [],
            "min_context": args.min_context,
            "max_input_cost": args.max_input_cost,
            "input_modality": args.input_modality or [],
            "output_modality": args.output_modality or [],
            "image": args.image,
            "video": args.video,
            "audio": args.audio,
            "file": args.file,
        }

        # Find model
        model = runner.find_model(
            task=args.task,
            input_modalities=args.input_modality,
            output_modalities=args.output_modality,
            max_input_cost=args.max_input_cost,
            budget=args.budget,
            prefer=args.prefer,
            min_context=args.min_context,
            verbose=args.verbose or args.dry_run,
        )

        if not model:
            print("❌ No suitable model found for this task with the given constraints.", file=sys.stderr)
            sys.exit(1)

        if args.dry_run:
            if args.json_output:
                result = {
                    "dry_run": True,
                    "model": model.id,
                    "name": model.name,
                    "input_modalities": model.input_modalities,
                    "output_modalities": model.output_modalities,
                    "context_length": model.context_length,
                    "input_cost_per_m": model.input_cost_per_m,
                    "is_free": model.is_free,
                    "supports_reasoning": model.supports_reasoning,
                }
                print(json.dumps(result, indent=2))
            else:
                cost_str = "free" if model.is_free else f"${model.input_cost_per_m:.2f}/M input"
                print(f"\n🏆 Would use: {model.id}")
                print(f"   Name: {model.name}")
                print(f"   Cost: {cost_str} | Context: {model.context_length:,}")
                print(f"   Modalities: {'+'.join(model.input_modalities)} → {'+'.join(model.output_modalities)}")
            sys.exit(0)

        # Execute
        result = runner.execute(
            task=args.task,
            model=model,
            image_url=args.image,
            video_url=args.video,
            audio_url=args.audio,
            file_path=args.file,
            verbose=args.verbose,
        )

        if args.json_output:
            output = {
                "content": result.content,
                "image_urls": result.image_urls,
                "model": result.model,
                "cost": result.cost,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
            }
            print(json.dumps(output, indent=2))
        else:
            # Print result to stdout (clean for piping)
            if result.content:
                print(result.content)
            for url in result.image_urls:
                print(f"🖼️  Image: {url}")

            # Metadata to stderr
            cost_str = f"${result.cost:.6f}" if result.cost > 0 else "free"
            print(f"\n💰 Cost: {cost_str} | Tokens: {result.tokens_in:,} in / {result.tokens_out:,} out | Model: {result.model}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
