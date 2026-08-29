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
import json
import logging
from pathlib import Path
import shutil
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

# Preprocessing + judge run litellm in-process, so a success callback captures their
# token usage (incl. reasoning tokens) and cost. Synto runs as a subprocess with its
# own non-litellm client, so its tokens are NOT captured here -- only wall-clock is.
_usage: list[dict] = []


def _usage_cb(kwargs, response_obj, start_time, end_time) -> None:
    try:
        u = response_obj.usage
        details = getattr(u, "completion_tokens_details", None)
        _usage.append({
            "model": kwargs.get("model"),
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "reasoning_tokens": getattr(details, "reasoning_tokens", None) or 0,
            "cost_usd": kwargs.get("response_cost") or 0.0,
        })
    except Exception:
        pass  # ponytail: usage is best-effort telemetry; never fail a run over it


litellm.success_callback = [_usage_cb]


def _drain_usage(start_idx: int) -> dict:
    """Sum usage records appended since start_idx (this model's preprocessing calls)."""
    rows = _usage[start_idx:]
    return {
        "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "completion_tokens": sum(r["completion_tokens"] for r in rows),
        "reasoning_tokens": sum(r["reasoning_tokens"] for r in rows),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
    }

BENCH = Path(__file__).parent.resolve()
ROOT = BENCH.parent
# ponytail: absolute rubric scoring is O(n) judge calls. Upgrade path for a
# tie-breaking ranking is pairwise round-robin (O(n^2), needs position-bias
# randomisation) -- not built until the matrix is large enough to need it.
CRITERIA = ["faithfulness", "coverage", "structure", "linking", "conciseness"]
KIND_DIR = {"exercise": "exercises", "paper": "papers", "lecture": "lectures"}

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
{fast_reasoning}
[models.heavy]
provider = "default"
model = "{model}"
ctx = 500000
{heavy_options}
[pipeline]
auto_approve = true
auto_commit = false
auto_maintain = false
max_concepts_per_source = 8
article_max_tokens = {content_cap}
concept_draft_soft_cap = {content_cap}
inline_source_citations = true
graph_quality_checks = true
"""

# ponytail: template assumes one provider serving both fast+heavy. If a model
# needs a split provider or per-provider API-key fields, extend the schema here.


def render_synto_toml(m: dict, num_predict: int, content_cap: int) -> str:
    # num_predict = API ceiling (content + reasoning headroom); content_cap = how long
    # articles/drafts should be. OpenRouter's `reasoning` knob is merged into the payload.
    effort = m.get("reasoning")
    line = f'reasoning = {{ effort = "{effort}" }}\n' if effort else ""
    # heavy always needs an options table so mandatory-reasoning models get room for content.
    heavy = f"\n[models.heavy.options]\nnum_predict = {num_predict}\n{line}"
    return SYNTO_TEMPLATE.format(
        provider=m["provider"],
        url=m["url"],
        model=m["model"],
        num_predict=num_predict,
        content_cap=content_cap,
        fast_reasoning=line,
        heavy_options=heavy,
    )


def build_preproc_config(base: dict, vault: Path, m: dict, max_output_tokens: int) -> dict:
    cfg = {**base, "preprocessing": {**base["preprocessing"]}}
    cfg["vault_path"] = str(vault)
    cfg["preprocessing"]["model"] = f"{m['provider']}/{m['model']}"  # llm-baseclient routing
    cfg["preprocessing"]["max_output_tokens"] = max_output_tokens  # room for mandatory reasoning + content
    # Per-model `reasoning` is authoritative: drop the base default so non-reasoning
    # ("flash") models don't get reasoning_effort, which OpenRouter rejects for them.
    cfg["preprocessing"].pop("reasoning_effort", None)
    if m.get("reasoning"):
        cfg["preprocessing"]["reasoning_effort"] = m["reasoning"]  # steer preprocessing thinking
    return cfg


async def ensure_mineru(sample: Path, stem: str, base: dict) -> str:
    """Guard: make sure the sample's MinerU markdown is in the shared cache before
    the matrix runs, parsing once if absent. Reuses the pipeline's own extract+
    publish step (no new MinerU wrapper) and returns the raw md as judge truth.
    ponytail: cloud_cache is best-effort; if the share is unmounted, publish is a
    no-op and each model falls back to parsing locally (pipeline's documented mode)."""
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
    system = (
        "You are a strict evaluator. Score a generated wiki against its SOURCE only. "
        "Do not reward fluent content that is unsupported by the source. "
        f"Rate each criterion 1-5: {', '.join(CRITERIA)}. "
        'Reply with ONLY JSON: {"scores": {crit: int}, "overall": float, "note": str}.'
    )
    user = f"# SOURCE (ground truth)\n{source}\n\n# GENERATED WIKI\n{wiki or '(empty)'}"
    resp = client.api_query(model=judge_model, user_msg=user, system_prompt=system, max_tokens=1024)
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    return json.loads(text)


def preflight(models: list[dict], judge_model: str) -> None:
    """Fail fast: one 'hello' per model (+judge) so bad slugs, missing auth, or
    unsupported reasoning error out in seconds instead of mid-run. Uses the same
    client + reasoning as the real preprocessing call. ponytail: llm-baseclient
    returns an Exception instead of raising, so we poke .choices to detect it; the
    real cause is printed by its own logger just above the SystemExit."""
    targets = [(m["id"], f"{m['provider']}/{m['model']}", m.get("reasoning")) for m in models]
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


def selfcheck() -> None:
    m = {"provider": "openrouter", "url": "https://x", "model": "anthropic/claude-sonnet-5", "reasoning": "high"}
    parsed = tomllib.loads(render_synto_toml(m, 32768, 8192))
    assert parsed["models"]["fast"]["model"] == m["model"], "synto model not stamped"
    assert parsed["providers"]["default"]["name"] == "openrouter", "provider not stamped"
    assert parsed["models"]["fast"]["options"]["reasoning"] == {"effort": "high"}, "synto reasoning not steered"
    assert parsed["models"]["heavy"]["options"]["reasoning"] == {"effort": "high"}, "heavy reasoning not steered"
    # max_tokens is the API ceiling (num_predict); content_cap is the article/draft length.
    assert parsed["models"]["fast"]["options"]["num_predict"] == 32768, "max_tokens not applied to fast"
    assert parsed["models"]["heavy"]["options"]["num_predict"] == 32768, "max_tokens not applied to heavy"
    assert parsed["pipeline"]["article_max_tokens"] == 8192, "content_cap not applied to article cap"
    assert parsed["pipeline"]["concept_draft_soft_cap"] == 8192, "content_cap not applied to draft cap"
    no_reasoning = tomllib.loads(render_synto_toml({**m, "reasoning": None}, 16384, 8192))
    assert "reasoning" not in no_reasoning["models"]["heavy"]["options"], "reasoning should be omittable"
    cfg = build_preproc_config({"preprocessing": {"reasoning_effort": "low"}}, Path("/v"), m, 32768)
    assert cfg["vault_path"] == "/v", "vault_path not isolated"
    assert cfg["preprocessing"]["model"] == "openrouter/anthropic/claude-sonnet-5", "preproc model wrong"
    assert cfg["preprocessing"]["reasoning_effort"] == "high", "preproc reasoning not steered"
    assert cfg["preprocessing"]["max_output_tokens"] == 32768, "budget not applied to preprocessing"
    # A flash model (no `reasoning`) must NOT inherit the base reasoning_effort.
    flash = build_preproc_config({"preprocessing": {"reasoning_effort": "high"}}, Path("/v"), {**m, "reasoning": None}, 16384)
    assert "reasoning_effort" not in flash["preprocessing"], "flash model leaked reasoning_effort"
    print("selfcheck OK")


def main() -> None:
    if "--selfcheck" in sys.argv:
        selfcheck()
        return

    spec = yaml.safe_load((BENCH / "spec.yaml").read_text(encoding="utf-8"))
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
    stem = sample.stem
    kind_dir = KIND_DIR[spec.get("pdf_kind", "exercise")]
    # content_cap: how long articles/drafts should be. max_tokens: API ceiling that
    # must also fit a reasoning model's thinking. Override both in spec.yaml.
    content_cap = spec.get("content_cap", 8192)
    max_tokens = spec.get("max_tokens", 32768)

    preflight(models, spec["judge"]["model"])  # cheap auth/slug/reasoning check before expensive work

    # Guard: prime the shared cache (parse once if absent) before the matrix runs.
    source = asyncio.run(ensure_mineru(sample, stem, base))

    results = {}
    for m in models:
        mid = m["id"]
        run = BENCH / "runs" / mid
        vault = run / "vault"
        vault.mkdir(parents=True, exist_ok=True)
        (vault / "synto.toml").write_text(render_synto_toml(m, max_tokens, content_cap), encoding="utf-8")
        # preprocess_pdf consumes (moves) its PDF, so hand each model its own copy.
        pdf_dir = run / kind_dir
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_copy = pdf_dir / sample.name
        shutil.copy2(sample, pdf_copy)
        usage_start = len(_usage)
        t0 = time.monotonic()
        try:
            # root_dir=ROOT so preprocess_pdf finds repo prompts/; vault_path is absolute.
            asyncio.run(preprocess_pdf(pdf_copy, ROOT, build_preproc_config(base, vault, m, max_tokens)))
            run_synto(vault)
            usage = _drain_usage(usage_start)  # snapshot before the judge call adds its own
            results[mid] = {**judge(spec["judge"]["model"], source, collect_wiki(vault)), "usage": usage}
        except Exception:
            log.exception("[%s] failed", mid)
            results[mid] = {"overall": 0.0, "note": "run failed", "usage": _drain_usage(usage_start)}
        results[mid]["usage"]["wall_clock_s"] = round(time.monotonic() - t0, 1)

    (BENCH / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n=== leaderboard ===")
    print(f"{'score':>5}  {'model':<20} {'rtok':>7} {'cost$':>8} {'wall_s':>7}  note")
    for mid, r in sorted(results.items(), key=lambda kv: kv[1].get("overall", 0), reverse=True):
        u = r.get("usage", {})
        print(
            f"{r.get('overall', 0):>5.2f}  {mid:<20} {u.get('reasoning_tokens', 0):>7} "
            f"{u.get('cost_usd', 0):>8.4f} {u.get('wall_clock_s', 0):>7}  {r.get('note', '')}"
        )


if __name__ == "__main__":
    main()
