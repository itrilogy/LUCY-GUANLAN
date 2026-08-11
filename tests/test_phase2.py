"""Phase 2: Behavior / forward / conditional backward / multi ranker."""


def test_behavior_crowd(engine):
    from engine.behavior import BehaviorModel
    nm = engine["nm"]
    b = BehaviorModel(engine["dh"], nm)
    reds = [1, 2, 3, 4, 5, 6]
    assert b.crowd_raw(reds) == nm._raw_cost_score(reds)
    assert b.anti_crowd_raw(reds) == -b.crowd_raw(reds)


def test_market_p1c(engine):
    mm = engine["mm"]
    v = mm.predict_p1c_from_market(3e8)
    assert v >= 0


def test_structure_ll(engine):
    nm = engine["nm"]
    ll = nm.structure_ll_raw([1, 5, 12, 18, 25, 33])
    assert isinstance(ll, float)


def test_g_cost_p1c(engine):
    nm = engine["nm"]
    g = nm.g_cost_p1c([2, 4, 15, 23, 25, 27])
    assert isinstance(g, float)


def test_backward_conditional(engine):
    v = engine["v"]
    back = v.backward_conditional(10.0)
    assert back is not None
    assert back["n_samples"] > 0
    assert "regime_dist" in back
    # prize-only weights ≈ backward
    back2 = v.backward_conditional(
        10.0, weights={"w_p": 1.0, "w_pool": 0.0, "w_bet": 0.0, "w_r": 0.0}
    )
    assert back2 is not None


def test_multi_ranker(engine):
    from engine.behavior import BehaviorModel
    from engine.ranker import MultiRanker

    dh, mm, nm, v = engine["dh"], engine["mm"], engine["nm"], engine["v"]
    b = BehaviorModel(dh, nm)
    ranker = MultiRanker(dh, mm, nm, b, v)
    cands = nm.sample_candidates(40, "平衡")
    validated = v.batch_validate(cands)
    ranked = ranker.rank(validated)
    assert len(ranked) == len(validated)
    assert "scores" in ranked[0]
    assert "final" in ranked[0]
    finals = [r["final"] for r in ranked]
    assert finals == sorted(finals, reverse=True)


def test_scoring_gate_blocks_multi(monkeypatch):
    import os
    from engine.predictor import resolve_scoring_mode

    monkeypatch.delenv("SSQ_ALLOW_EXPERIMENTAL_SCORING", raising=False)
    mode, note = resolve_scoring_mode("multi")
    assert mode == "legacy"
    assert note == "experimental_gate_blocked"

    monkeypatch.setenv("SSQ_ALLOW_EXPERIMENTAL_SCORING", "1")
    mode2, note2 = resolve_scoring_mode("multi")
    assert mode2 == "multi"
    assert note2 is None
