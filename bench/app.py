"""Streamlit overview of a benchmark run.

    uv run streamlit run bench/app.py

Reads bench/results.json (produced by bench.py): per model an `overall` score,
per-criterion `scores`, and a concise `note`. Also surfaces each model's
generated wiki from bench/runs/<id>/vault/wiki for spot-checking.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

BENCH = Path(__file__).parent.resolve()


def load_results(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def to_frame(results: dict) -> pd.DataFrame:
    rows = []
    for mid, r in results.items():
        row = {"model": mid, "overall": r.get("overall", 0.0), **r.get("scores", {})}
        rows.append(row)
    frame = pd.DataFrame(rows).set_index("model")
    return frame.sort_values("overall", ascending=False)


st.set_page_config(page_title="autowiki benchmark", layout="wide")
st.title("autowiki benchmark")

results_path = Path(st.sidebar.text_input("results.json", value=str(BENCH / "results.json")))
results = load_results(results_path)

if not results:
    st.info(f"No results at {results_path}. Run `uv run python bench.py` first.")
    st.stop()

frame = to_frame(results)
criteria = [c for c in frame.columns if c != "overall"]

st.subheader("Leaderboard")
st.dataframe(
    frame.style.background_gradient(cmap="Greens", vmin=0, vmax=5),
    use_container_width=True,
)
st.bar_chart(frame["overall"])

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
        wiki_dir = BENCH / "runs" / mid / "vault" / "wiki"
        articles = sorted(wiki_dir.glob("**/*.md")) if wiki_dir.is_dir() else []
        if articles:
            chosen = st.selectbox("generated article", articles, format_func=lambda p: p.name, key=f"sel-{mid}")
            st.markdown(chosen.read_text(encoding="utf-8"))
        else:
            st.caption("no wiki articles found")
