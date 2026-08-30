"""Streamlit overview of a benchmark run.

    uv run streamlit run bench/app.py

Selects a complete bundle under bench/benchmarks/, shows its stored spec, and
loads its per-model scores, usage, and generated wiki articles.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

BENCH = Path(__file__).parent.resolve()
BENCHMARKS = BENCH / "benchmarks"


def list_benchmarks() -> list[Path]:
    """List complete benchmark bundles, newest first."""
    if not BENCHMARKS.is_dir():
        return []
    return sorted(
        (path for path in BENCHMARKS.iterdir() if (path / "spec.yaml").is_file() and (path / "results.json").is_file()),
        reverse=True,
    )


def load_results(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _green(v) -> str:
    """0-5 score -> green background, without matplotlib (background_gradient needs it)."""
    try:
        x = max(0.0, min(1.0, float(v) / 5))
    except (TypeError, ValueError):
        return ""
    r, g, b = int(235 - 150 * x), int(245 - 70 * x), int(235 - 150 * x)
    return f"background-color: rgb({r},{g},{b})"


def to_frame(results: dict) -> pd.DataFrame:
    rows = []
    for mid, r in results.items():
        u = r.get("usage", {})
        row = {
            "model": mid,
            "overall": r.get("overall", 0.0),
            **r.get("scores", {}),
            "reasoning_tok": u.get("reasoning_tokens", 0),
            "cost_usd": u.get("cost_usd", 0.0),
            "wall_s": u.get("wall_clock_s", 0.0),
        }
        rows.append(row)
    frame = pd.DataFrame(rows).set_index("model")
    return frame.sort_values("overall", ascending=False)


st.set_page_config(page_title="autowiki benchmark", layout="wide")
st.title("autowiki benchmark")

benchmarks = list_benchmarks()
if not benchmarks:
    st.info(f"No complete benchmarks under {BENCHMARKS}. Run `uv run python bench/bench.py` first.")
    st.stop()

with st.sidebar:
    selected_benchmark = st.selectbox("Benchmark", benchmarks, format_func=lambda path: path.name)
    with st.expander("Experiment configuration"):
        st.code((selected_benchmark / "spec.yaml").read_text(encoding="utf-8"), language="yaml")

results = load_results(selected_benchmark / "results.json")
if not results:
    st.info(f"No results in {selected_benchmark}.")
    st.stop()

frame = to_frame(results)
USAGE_COLS = {"reasoning_tok", "cost_usd", "wall_s"}
criteria = [c for c in frame.columns if c != "overall" and c not in USAGE_COLS]

st.subheader("Leaderboard")
# Grade only the 0-5 quality columns; usage columns (tokens/cost/time) are raw counts.
quality_cols = ["overall", *criteria]
st.dataframe(
    frame.style.map(_green, subset=quality_cols),
    width="stretch",
)
c1, c2 = st.columns(2)
c1.caption("quality (overall)")
c1.bar_chart(frame["overall"])
c2.caption("reasoning tokens (preprocessing) — the thinking tax")
c2.bar_chart(frame["reasoning_tok"])

st.subheader("Per-model detail")
for mid in frame.index:
    r = results[mid]
    with st.expander(f"{mid} — overall {r.get('overall', 0):.2f} / 5", expanded=False):
        st.caption(r.get("note", "") or "(no explanation)")
        scores = r.get("scores", {})
        if scores:
            cols = st.columns(len(scores))
            for col, crit in zip(cols, criteria, strict=False):
                col.metric(crit, scores.get(crit, "—"))
        u = r.get("usage", {})
        if u:
            uc = st.columns(4)
            uc[0].metric("reasoning tok", u.get("reasoning_tokens", 0))
            uc[1].metric("completion tok", u.get("completion_tokens", 0))
            uc[2].metric("cost $", f"{u.get('cost_usd', 0):.4f}")
            uc[3].metric("wall s", u.get("wall_clock_s", 0))
        wiki_dir = selected_benchmark / "runs" / mid / "vault" / "wiki"
        articles = sorted(wiki_dir.glob("**/*.md")) if wiki_dir.is_dir() else []
        if articles:
            chosen = st.selectbox("generated article", articles, format_func=lambda p: p.name, key=f"sel-{mid}")
            st.markdown(chosen.read_text(encoding="utf-8"))
        else:
            st.caption("no wiki articles found")
