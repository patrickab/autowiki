"""Benchmark a matrix of models on one sample PDF, judged LLM-as-judge.

Reuses autowiki's own functions end to end. A guard ensures the sample's MinerU
markdown is in the shared cloud cache before the matrix starts (parsing once if
absent), so every model's preprocess_pdf reuses it. Each model gets an isolated
vault so `raw/` and `wiki/` never collide. A rubric judge scores each model's
wiki against the MinerU ground truth.

    uv run python bench/bench.py            # run matrix + judge
    uv run python bench/bench.py --selfcheck  # offline logic check, no network
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import litellm
import tomllib
import yaml

from autowiki import cloud_cache
from autowiki.pipeline import _extract_markdown, client, preprocess_pdf
from autowiki.synto_runner import run_synto

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bench")


@dataclass(frozen=True)
class UsageRecord:
    """Token counts and cost reported for one in-process LLM call."""

    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cost_usd: float


# LiteLLM's callback has no run-local destination, so sequential model runs share
# this list. Each run remembers its starting index and summarizes only newer calls.
# Synto runs in a subprocess and therefore contributes wall-clock time, but no usage.
_usage_records: list[UsageRecord] = []


def _record_usage(kwargs, response_obj, _start_time, _end_time) -> None:
    """Capture best-effort telemetry from a successful LiteLLM call.

    - Keep the unused time arguments required by LiteLLM's callback contract.
    - Ignore missing telemetry rather than failing an otherwise successful run.
    """
    usage = getattr(response_obj, "usage", None)
    if usage is None:
        return

    completion_details = getattr(usage, "completion_tokens_details", None)
    _usage_records.append(
        UsageRecord(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            reasoning_tokens=getattr(completion_details, "reasoning_tokens", 0) or 0,
            cost_usd=kwargs.get("response_cost") or 0.0,
        )
    )


litellm.success_callback = [_record_usage]


def _summarize_usage(start_index: int) -> dict:
    """Sum usage records appended since start_index (this model's preprocessing calls)."""
    records = _usage_records[start_index:]
    return {
        "prompt_tokens": sum(record.prompt_tokens for record in records),
        "completion_tokens": sum(record.completion_tokens for record in records),
        "reasoning_tokens": sum(record.reasoning_tokens for record in records),
        "cost_usd": round(sum(record.cost_usd for record in records), 6),
    }


BENCH = Path(__file__).parent.resolve()
ROOT = BENCH.parent
SPEC = BENCH / "spec.yaml"
BENCHMARKS = BENCH / "benchmarks"


class DocumentType(StrEnum):
    """Document types accepted by ``pdf_kind`` in the benchmark spec."""

    EXERCISE = "exercise"
    PAPER = "paper"
    LECTURE = "lecture"


@dataclass(frozen=True)
class Criterion:
    """One named scoring dimension and its judge guidance."""

    name: str
    description: str


CRITERIA = (
    Criterion(
        name="faithfulness",
        description="Claims are supported by the source without hallucination.",
    ),
    Criterion(
        name="coverage",
        description="Important source concepts and conclusions are retained.",
    ),
    Criterion(
        name="structure",
        description="Content is organized into coherent, focused articles.",
    ),
    Criterion(
        name="didactic_quality",
        description="Concepts are explained in a logical progression that a first-time reader can follow.",
    ),
    Criterion(
        name="linking",
        description="Related concepts are connected with useful wiki links.",
    ),
    Criterion(
        name="conciseness",
        description="Content avoids repetition and unnecessary detail.",
    ),
)


@dataclass(frozen=True)
class BenchmarkConfig:
    base: dict
    sample: Path
    models: list[dict]
    judge_model: str
    document_type: DocumentType
    slug: str
    content_cap: int
    max_tokens: int
    max_articles: int


SYNTO_TEMPLATE = """\
[providers.default]
name = "{provider}"
url = "{url}"
timeout = 600

[models.fast]
provider = "default"
model = "{model}"
ctx = 500000

[models.fast.options]
num_predict = {num_predict}
{reasoning_option}

[models.heavy]
provider = "default"
model = "{model}"
ctx = 500000

[models.heavy.options]
num_predict = {num_predict}
{reasoning_option}

[pipeline]
auto_approve = true
auto_commit = false
auto_maintain = false
max_concepts_per_source = {max_articles}
article_max_tokens = {content_cap}
concept_draft_soft_cap = {content_cap}
inline_source_citations = true
graph_quality_checks = true
"""


def render_synto_toml(model: dict, num_predict: int, content_cap: int, max_articles: int) -> str:
    """Render the Synto configuration for one benchmark model.

    - Use the same provider and model for the fast and heavy roles.
    - Apply the API ceiling, content cap, article ceiling, and optional reasoning effort.

    max_concepts_per_source is a hard ceiling in Synto: it beats the per-type
    built-ins (textbook 25, paper 15), so the spec decides the article count no
    matter what source_type preprocessing stamps on the note.
    """
    effort = model.get("reasoning")
    reasoning_option = f'reasoning = {{ effort = "{effort}" }}' if effort else ""
    return SYNTO_TEMPLATE.format(
        provider=model["provider"],
        url=model["url"],
        model=model["model"],
        num_predict=num_predict,
        reasoning_option=reasoning_option,
        content_cap=content_cap,
        max_articles=max_articles,
    )


def build_model_preprocessing_config(base_config: dict, vault: Path, model: dict, max_output_tokens: int) -> dict:
    """Create a model-specific preprocessing config targeting an isolated vault."""
    config = {**base_config, "preprocessing": {**base_config["preprocessing"]}}
    config["vault_path"] = str(vault)
    config["preprocessing"]["model"] = f"{model['provider']}/{model['model']}"  # llm-baseclient routing
    config["preprocessing"]["max_output_tokens"] = max_output_tokens  # room for mandatory reasoning + content
    # Per-model `reasoning` is authoritative: drop the base default so non-reasoning
    # ("flash") models don't get reasoning_effort, which OpenRouter rejects for them.
    config["preprocessing"].pop("reasoning_effort", None)
    if model.get("reasoning"):
        config["preprocessing"]["reasoning_effort"] = model["reasoning"]  # steer preprocessing thinking
    return config


async def ensure_mineru(sample: Path, stem: str, base: dict) -> str:
    """Provide the source Markdown used as judge ground truth.

    - Return the shared MinerU cache entry when available.
    - Otherwise extract once into ``bench/_warmup`` and publish best-effort.
    """
    cached = cloud_cache.fetch_cached_markdown(stem)
    if cached is not None:
        log.info("[%s] MinerU already in shared cache", stem)
        return cached
    warmup = BENCH / "_warmup"
    warmup.mkdir(parents=True, exist_ok=True)
    return await _extract_markdown(
        sample,
        stem,
        warmup / "tmp",
        base["preprocessing"].get("min_chars", 200),
        warmup,
        base.get("mineru", {}).get("backend", "auto"),
    )


def collect_wiki(vault: Path) -> str:
    files = sorted((vault / "wiki").glob("**/*.md"))
    return "\n\n".join(f"## {f.name}\n{f.read_text(encoding='utf-8')}" for f in files)


def judge(judge_model: str, source: str, wiki: str) -> dict:
    """Score one generated wiki against its source.

    - Ask the judge for criterion scores, an overall score, and a note.
    - Strip an optional Markdown fence and return the parsed JSON object.
    """
    rubric = "\n".join(f"- {criterion.name}: {criterion.description}" for criterion in CRITERIA)
    score_keys = ", ".join(f'"{criterion.name}"' for criterion in CRITERIA)
    system = (
        "You are a strict evaluator. Score a generated wiki against its SOURCE only. "
        "Do not reward fluent content that is unsupported by the source. "
        f"Rate each criterion 1-5:\n{rubric}\n"
        f"Use exactly these score keys: {score_keys}. "
        'Reply with ONLY JSON: {"scores": {crit: int}, "overall": float, "note": str}.'
    )
    user = f"# SOURCE (ground truth)\n{source}\n\n# GENERATED WIKI\n{wiki or '(empty)'}"
    resp = client.api_query(model=judge_model, user_msg=user, system_prompt=system, max_tokens=1024)
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    return json.loads(text)


def preflight(models: list[dict], judge_model: str) -> None:
    """Check every benchmark model and the judge before expensive work.

    - Send one tiny request with each model's configured reasoning effort.
    - Stop immediately on invalid credentials, model names, or options.
    """
    targets = [(model["id"], f"{model['provider']}/{model['model']}", model.get("reasoning")) for model in models]
    targets.append(("judge", judge_model, None))
    for name, model, reasoning in targets:
        kwargs: dict = {"max_tokens": 8}
        if reasoning:
            kwargs["reasoning_effort"] = reasoning
        try:
            resp = client.api_query(model=model, user_msg="hello", **kwargs)
            _ = resp.choices[0].message.content
        except Exception as e:
            raise SystemExit(f"Preflight failed for {name} ({model}); see error above: {e}")
        log.info("[preflight] %s OK", name)


def benchmark_bundle_path(slug: str, commit: str) -> Path:
    """Build the dated, human-readable directory for one benchmark bundle."""
    date = datetime.now().strftime("%y_%m_%d")
    return BENCHMARKS / f"{date}_{slug}_{commit}"


def current_commit() -> str:
    """Return the short commit hash recorded in benchmark bundle names."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Cannot determine benchmark commit: {error}")
    return result.stdout.strip()


def selfcheck() -> None:
    model = {"provider": "openrouter", "url": "https://x", "model": "anthropic/claude-sonnet-5", "reasoning": "high"}
    parsed = tomllib.loads(render_synto_toml(model, 32768, 8192, 8))
    assert parsed["models"]["fast"]["model"] == model["model"], "synto model not stamped"
    assert parsed["providers"]["default"]["name"] == "openrouter", "provider not stamped"
    assert parsed["models"]["fast"]["options"]["reasoning"] == {"effort": "high"}, "synto reasoning not steered"
    assert parsed["models"]["heavy"]["options"]["reasoning"] == {"effort": "high"}, "heavy reasoning not steered"
    # max_tokens is the API ceiling (num_predict); content_cap is the article/draft length.
    assert parsed["models"]["fast"]["options"]["num_predict"] == 32768, "max_tokens not applied to fast"
    assert parsed["models"]["heavy"]["options"]["num_predict"] == 32768, "max_tokens not applied to heavy"
    assert parsed["pipeline"]["article_max_tokens"] == 8192, "content_cap not applied to article cap"
    assert parsed["pipeline"]["concept_draft_soft_cap"] == 8192, "content_cap not applied to draft cap"
    # A hard ceiling: Synto must not lift this to the textbook built-in of 25.
    assert parsed["pipeline"]["max_concepts_per_source"] == 8, "max_articles not applied to article cap"
    no_reasoning = tomllib.loads(render_synto_toml({**model, "reasoning": None}, 16384, 8192, 12))
    assert no_reasoning["pipeline"]["max_concepts_per_source"] == 12, "max_articles not configurable"
    assert "reasoning" not in no_reasoning["models"]["heavy"]["options"], "reasoning should be omittable"
    config = build_model_preprocessing_config({"preprocessing": {"reasoning_effort": "low"}}, Path("/v"), model, 32768)
    assert config["vault_path"] == "/v", "vault_path not isolated"
    assert config["preprocessing"]["model"] == "openrouter/anthropic/claude-sonnet-5", "preproc model wrong"
    assert config["preprocessing"]["reasoning_effort"] == "high", "preproc reasoning not steered"
    assert config["preprocessing"]["max_output_tokens"] == 32768, "budget not applied to preprocessing"
    # A flash model (no `reasoning`) must NOT inherit the base reasoning_effort.
    flash = build_model_preprocessing_config(
        {"preprocessing": {"reasoning_effort": "high"}}, Path("/v"), {**model, "reasoning": None}, 16384
    )
    assert "reasoning_effort" not in flash["preprocessing"], "flash model leaked reasoning_effort"
    assert f"{DocumentType.LECTURE}s" == "lectures", "document type directory wrong"
    criterion_names = [criterion.name for criterion in CRITERIA]
    assert len(criterion_names) == len(set(criterion_names)), "criterion names must be unique"
    assert all(criterion.description for criterion in CRITERIA), "criterion descriptions must not be empty"
    assert benchmark_bundle_path("latex-transport", "abc1234").name.endswith("_latex-transport_abc1234")
    print("selfcheck OK")


def load_benchmark_config() -> BenchmarkConfig:
    """Load the benchmark inputs into one immutable configuration.

    - Read the benchmark spec and base preprocessing configuration.
    - Resolve and validate the sample PDF and model list.
    - Apply token defaults and parse the configured document type.
    """
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    base = yaml.safe_load((ROOT / "config-preprocessing.yaml").read_text(encoding="utf-8"))

    # Full path (absolute or ~-expanded, e.g. a cloud mount); relative falls back to repo root.
    sample = Path(spec["sample_pdf"]).expanduser()
    if not sample.is_absolute():
        sample = ROOT / sample
    if not sample.is_file():
        raise SystemExit(f"Sample PDF not found: {sample}")
    models = spec.get("models") or []
    if not models:
        raise SystemExit("spec.yaml lists no models")
    slug = spec.get("slug", "")
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise SystemExit("spec.yaml slug must contain lowercase letters, numbers, and single hyphens")

    # content_cap: how long articles/drafts should be. max_tokens: API ceiling that
    # must also fit a reasoning model's thinking. Override both in spec.yaml.
    return BenchmarkConfig(
        base=base,
        sample=sample,
        models=models,
        judge_model=spec["judge"]["model"],
        document_type=DocumentType(spec.get("pdf_kind", DocumentType.EXERCISE)),
        slug=slug,
        content_cap=spec.get("content_cap", 8192),
        max_tokens=spec.get("max_tokens", 32768),
        max_articles=spec.get("max_articles", 8),
    )


def prepare_model_run(benchmark_dir: Path, config: BenchmarkConfig, model: dict) -> tuple[Path, Path]:
    """Create the isolated inputs for one model run.

    - Write the model-specific Synto configuration into its vault.
    - Copy the sample because preprocessing consumes its PDF input.
    - Return the disposable PDF copy and isolated vault.
    """
    run_dir = benchmark_dir / "runs" / model["id"]
    vault = run_dir / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "synto.toml").write_text(
        render_synto_toml(model, config.max_tokens, config.content_cap, config.max_articles),
        encoding="utf-8",
    )

    # preprocess_pdf consumes (moves) its PDF, so hand each model its own copy.
    pdf_dir = run_dir / f"{config.document_type}s"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_copy = pdf_dir / config.sample.name
    shutil.copy2(config.sample, pdf_copy)
    return pdf_copy, vault


def run_model(benchmark_dir: Path, config: BenchmarkConfig, model: dict, source: str) -> dict:
    """Run and score one model end to end.

    - Prepare its files, preprocess the PDF, and invoke Synto.
    - Judge the generated wiki and attach usage plus wall-clock telemetry.
    - Convert processing or judging failures into a zero-score result.
    """
    model_id = model["id"]
    pdf_copy, vault = prepare_model_run(benchmark_dir, config, model)
    usage_start = len(_usage_records)
    started_at = time.monotonic()

    try:
        # root_dir=ROOT so preprocess_pdf finds repo prompts/; vault_path is absolute.
        model_preprocessing_config = build_model_preprocessing_config(config.base, vault, model, config.max_tokens)
        asyncio.run(preprocess_pdf(pdf_copy, ROOT, model_preprocessing_config))
        run_synto(vault)

        # Snapshot before the judge call adds its own usage.
        usage = _summarize_usage(usage_start)
        result = judge(config.judge_model, source, collect_wiki(vault))
        result["usage"] = usage
    except Exception:
        log.exception("[%s] failed", model_id)
        result = {"overall": 0.0, "note": "run failed", "usage": _summarize_usage(usage_start)}

    result["usage"]["wall_clock_s"] = round(time.monotonic() - started_at, 1)
    return result


def run_benchmark(benchmark_dir: Path, config: BenchmarkConfig, source: str) -> dict:
    """Run the configured model matrix sequentially.

    - Execute each model in its own run directory.
    - Return results keyed by the model IDs from the spec.
    """
    results = {}
    for model in config.models:
        results[model["id"]] = run_model(benchmark_dir, config, model, source)
    return results


def print_leaderboard(results: dict) -> None:
    """Print a compact best-first result summary.

    - Sort by overall score, descending.
    - Show reasoning tokens, cost, runtime, and the judge note.
    """
    ranked_results = sorted(results.items(), key=lambda item: item[1].get("overall", 0), reverse=True)

    print("\n=== leaderboard ===")
    print(f"{'score':>5}  {'model':<20} {'rtok':>7} {'cost$':>8} {'wall_s':>7}  note")
    for model_id, result in ranked_results:
        usage = result.get("usage", {})
        print(
            f"{result.get('overall', 0):>5.2f}  {model_id:<20} {usage.get('reasoning_tokens', 0):>7} "
            f"{usage.get('cost_usd', 0):>8.4f} {usage.get('wall_clock_s', 0):>7}  {result.get('note', '')}"
        )


def main() -> None:
    """Run the benchmark command-line workflow.

    - Handle the offline self-check, then load and preflight the matrix.
    - Warm the MinerU source, run all models, and save ``results.json``.
    - Print the final leaderboard.
    """
    if "--selfcheck" in sys.argv:
        selfcheck()
        return

    config = load_benchmark_config()
    benchmark_dir = benchmark_bundle_path(config.slug, current_commit())
    if benchmark_dir.exists():
        raise SystemExit(f"Benchmark bundle already exists; change the spec slug: {benchmark_dir}")
    preflight(config.models, config.judge_model)

    # Guard: prime the shared cache (parse once if absent) before the matrix runs.
    source = asyncio.run(ensure_mineru(config.sample, config.sample.stem, config.base))
    benchmark_dir.mkdir(parents=True)
    shutil.copy2(SPEC, benchmark_dir / SPEC.name)
    results = run_benchmark(benchmark_dir, config, source)
    (benchmark_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("Benchmark bundle saved to %s", benchmark_dir)
    print_leaderboard(results)


if __name__ == "__main__":
    main()
