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

import tomllib
import yaml

from autowiki import cloud_cache
from autowiki.pipeline import _extract_markdown, client, preprocess_pdf
from autowiki.synto_runner import run_synto

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bench")

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
num_predict = 8192

[models.heavy]
provider = "default"
model = "{model}"
ctx = 500000

[pipeline]
auto_approve = true
auto_commit = false
auto_maintain = false
max_concepts_per_source = 8
article_max_tokens = 16384
concept_draft_soft_cap = 16384
inline_source_citations = true
graph_quality_checks = true
"""

# ponytail: template assumes one provider serving both fast+heavy. If a model
# needs a split provider or per-provider API-key fields, extend the schema here.


def render_synto_toml(m: dict) -> str:
    return SYNTO_TEMPLATE.format(provider=m["provider"], url=m["url"], model=m["model"])


def build_preproc_config(base: dict, vault: Path, m: dict) -> dict:
    cfg = {**base, "preprocessing": {**base["preprocessing"]}}
    cfg["vault_path"] = str(vault)
    cfg["preprocessing"]["model"] = f"{m['provider']}/{m['model']}"  # llm-baseclient routing
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
        sample, stem, warmup / "tmp",
        base["preprocessing"].get("min_chars", 200),
        warmup, base.get("mineru", {}).get("backend", "auto"),
    )


def collect_wiki(vault: Path) -> str:
    files = sorted((vault / "wiki").glob("**/*.md"))
    return "\n\n".join(f"## {f.name}\n{f.read_text(encoding='utf-8')}" for f in files)


def judge(judge_model: str, source: str, wiki: str) -> dict:
    system = (
        "You are a strict evaluator. Score a generated wiki against its SOURCE only. "
        "Do not reward fluent content that is unsupported by the source. "
        f"Rate each criterion 1-5: {', '.join(CRITERIA)}. "
        "Reply with ONLY JSON: {\"scores\": {crit: int}, \"overall\": float, \"note\": str}."
    )
    user = f"# SOURCE (ground truth)\n{source}\n\n# GENERATED WIKI\n{wiki or '(empty)'}"
    resp = client.api_query(model=judge_model, user_msg=user, system_prompt=system, max_tokens=1024)
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    return json.loads(text)


def selfcheck() -> None:
    m = {"provider": "openrouter", "url": "https://x", "model": "anthropic/claude-3.5-sonnet"}
    parsed = tomllib.loads(render_synto_toml(m))
    assert parsed["models"]["fast"]["model"] == m["model"], "synto model not stamped"
    assert parsed["providers"]["default"]["name"] == "openrouter", "provider not stamped"
    cfg = build_preproc_config({"preprocessing": {"reasoning_effort": "high"}}, Path("/v"), m)
    assert cfg["vault_path"] == "/v", "vault_path not isolated"
    assert cfg["preprocessing"]["model"] == "openrouter/anthropic/claude-3.5-sonnet", "preproc model wrong"
    assert cfg["preprocessing"]["reasoning_effort"] == "high", "base knobs not preserved"
    print("selfcheck OK")


def main() -> None:
    if "--selfcheck" in sys.argv:
        selfcheck()
        return

    spec = yaml.safe_load((BENCH / "spec.yaml").read_text(encoding="utf-8"))
    base = yaml.safe_load((ROOT / "config-preprocessing.yaml").read_text(encoding="utf-8"))
    sample = ROOT / spec["sample_pdf"]
    if not sample.is_file():
        raise SystemExit(f"Sample PDF not found: {sample}")
    models = spec.get("models") or []
    if not models:
        raise SystemExit("spec.yaml lists no models")
    stem = sample.stem
    kind_dir = KIND_DIR[spec.get("pdf_kind", "exercise")]

    # Guard: prime the shared cache (parse once if absent) before the matrix runs.
    source = asyncio.run(ensure_mineru(sample, stem, base))

    results = {}
    for m in models:
        mid = m["id"]
        run = BENCH / "runs" / mid
        vault = run / "vault"
        vault.mkdir(parents=True, exist_ok=True)
        (vault / "synto.toml").write_text(render_synto_toml(m), encoding="utf-8")
        # preprocess_pdf consumes (moves) its PDF, so hand each model its own copy.
        pdf_dir = run / kind_dir
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_copy = pdf_dir / sample.name
        shutil.copy2(sample, pdf_copy)
        try:
            # root_dir=ROOT so preprocess_pdf finds repo prompts/; vault_path is absolute.
            asyncio.run(preprocess_pdf(pdf_copy, ROOT, build_preproc_config(base, vault, m)))
            run_synto(vault)
            results[mid] = judge(spec["judge"]["model"], source, collect_wiki(vault))
        except Exception:
            log.exception("[%s] failed", mid)
            results[mid] = {"overall": 0.0, "note": "run failed"}

    (BENCH / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n=== leaderboard ===")
    for mid, r in sorted(results.items(), key=lambda kv: kv[1].get("overall", 0), reverse=True):
        print(f"{r.get('overall', 0):>5.2f}  {mid:<20} {r.get('note', '')}")


if __name__ == "__main__":
    main()
