"""Unit tests for ``score_cell_local`` (local-fallback v1 stub).

Coverage:
- Determinism: same ``(strategy, symbol, timeframe)`` → same metrics
  (hash-derived). Same input → same scorecard shape and values.
- Stub markers on output: ``local_fallback: true`` + ``v1_stub: true`` on
  every emitted card (the v1 README's headline warning — downstream
  consumers MUST distinguish v1 placeholders from real PnL).
- Optional ``output_path``: writes the scorecard as JSON to disk; parent
  dirs are created. ``output_path=None`` → no disk write; return-only.
- Q4 v1 binding: ``seed`` passed through unchanged; ``cell_id`` matches
  what ``seed.cell_id()`` would compute.
- No external network / clock-dependent fields (except ``started_at`` /
  ``finished_at`` ISO timestamps — same value within v1's stub).
"""

from __future__ import annotations

import hashlib
import json

from offload.scoring import score_cell_local
from offload.seed import cell_id as _derive_cell_id


def _args(strategy: str = "q1_mw_formation", symbol: str = "GBPUSD", tf: str = "M5"):
    return {
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": tf,
        "seed": _derive_cell_id(strategy, symbol, tf),  # Q4 v1 binding
    }


def test_score_cell_local_is_deterministic_across_calls() -> None:
    """Same inputs → same metric values across calls (no randomness)."""
    a = score_cell_local(**_args())
    b = score_cell_local(**_args())
    assert a["metrics"] == b["metrics"]
    assert a["cell_id"] == b["cell_id"]


def test_score_cell_local_distinguishes_triples() -> None:
    """Different triples → different cell_id, different metrics."""
    m5 = score_cell_local(**_args(tf="M5"))
    m15 = score_cell_local(**_args(tf="M15"))
    other = score_cell_local(**_args(symbol="EURUSD"))
    assert len({m5["cell_id"], m15["cell_id"], other["cell_id"]}) == 3
    assert m5["metrics"] != m15["metrics"]
    assert m5["metrics"] != other["metrics"]


def test_score_card_local_fallback_flag_is_true() -> None:
    """Every emitted card carries ``local_fallback: true`` (Q7 observability)."""
    card = score_cell_local(**_args())
    assert card["local_fallback"] is True


def test_score_card_v1_stub_flag_is_true() -> None:
    """Every emitted card carries ``v1_stub: true`` (the README shout relies on this)."""
    card = score_cell_local(**_args())
    assert card["v1_stub"] is True


def test_score_card_schema_keys(tmp_path) -> None:
    """Card has the 8 expected top-level keys (q3 schema invariant)."""
    card = score_cell_local(**_args())
    expected_top = {
        "cell_id", "seed", "strategy", "symbol", "timeframe",
        "metrics", "started_at", "finished_at",
        "local_fallback", "v1_stub",
    }
    assert set(card.keys()) == expected_top


def test_metrics_keys_and_ranges() -> None:
    """Metrics dict has the 5 documented keys; values are reasonable."""
    card = score_cell_local(**_args())
    metrics = card["metrics"]
    assert set(metrics.keys()) == {
        "n_trades", "net_pips", "win_rate", "sharpe", "max_dd_pips",
    }
    assert isinstance(metrics["n_trades"], int)
    assert 50 <= metrics["n_trades"] < 100  # 50..99 range per stub design
    assert isinstance(metrics["net_pips"], (int, float))
    assert 0.40 <= metrics["win_rate"] <= 0.60
    assert isinstance(metrics["sharpe"], (int, float))
    assert metrics["max_dd_pips"] <= 0  # always non-positive (drawdown)


def test_score_cell_local_writes_scorecard_when_output_path_given(tmp_path) -> None:
    """``output_path`` argument triggers a disk write of the scorecard as JSON."""
    score_path = tmp_path / "scorecard.json"
    card = score_cell_local(**_args(), output_path=score_path)
    assert score_path.is_file()
    on_disk = json.loads(score_path.read_text())
    assert on_disk == card  # bytes-on-disk == return value
    assert on_disk["v1_stub"] is True


def test_score_cell_local_creates_parent_dirs(tmp_path) -> None:
    """output_path with missing parent dirs → helper creates them."""
    score_path = tmp_path / "deep" / "nested" / "scorecard.json"
    assert not score_path.parent.exists()
    score_cell_local(**_args(), output_path=score_path)
    assert score_path.is_file()


def test_score_cell_local_no_disk_write_when_output_path_none() -> None:
    """``output_path=None`` returns the card but does not touch disk."""
    import os

    before = set(os.listdir())
    card = score_cell_local(**_args())
    after = set(os.listdir())
    assert before == after, "no files should be created on disk"
    assert isinstance(card, dict)
    assert card["cell_id"] == _derive_cell_id("q1_mw_formation", "GBPUSD", "M5")


def test_score_card_seed_matches_cell_id_q4_binding() -> None:
    """Q4 v1: ``seed`` passed in equals the computed ``cell_id`` (single source)."""
    cid = _derive_cell_id("q1_mw_formation", "GBPUSD", "M5")
    card = score_cell_local(strategy="q1_mw_formation", symbol="GBPUSD",
                            timeframe="M5", seed=cid)
    assert card["seed"] == cid
    assert card["cell_id"] == cid


def test_score_card_is_purely_deterministic_from_cell_id_hash() -> None:
    """Verify the metrics values are derived from a sha256 of the cell_id."""
    cid = _derive_cell_id("q1_mw_formation", "GBPUSD", "M5")
    digest = hashlib.sha256(cid.encode("utf-8")).digest()
    card = score_cell_local(**_args())
    # The same formula in scoring.score_cell_local — verify against the spec.
    assert card["metrics"]["n_trades"] == 50 + (digest[0] % 50)
    assert card["metrics"]["net_pips"] == round((digest[1] - digest[2]) * 0.5, 2)
    assert card["metrics"]["win_rate"] == round(0.40 + (digest[3] / 255) * 0.20, 4)
    assert card["metrics"]["sharpe"] == round((digest[4] - 128) / 50.0, 3)
    assert card["metrics"]["max_dd_pips"] == round(-(digest[5] / 255) * 30, 1)
