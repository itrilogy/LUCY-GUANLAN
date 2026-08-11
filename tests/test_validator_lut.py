"""Validator prize LUT + single-pass batch_validate."""


def test_lut_matches_backward(engine):
    v = engine["v"]
    v.ensure_backward_lut()
    for k in (0, 1, 5, 10, 20, 50, 100):
        live = v.backward(k, top_k=20)
        cached = v._backward_lut[k]
        if live is None:
            assert cached is None
            continue
        assert live["n_samples"] == cached["n_samples"]
        assert live["most_likely_regime"] == cached["most_likely_regime"]
        assert live["regime_dist"] == cached["regime_dist"]


def test_invalidate_lut(engine):
    v = engine["v"]
    v.ensure_backward_lut()
    assert v._backward_lut is not None
    v.invalidate_backward_lut()
    assert v._backward_lut is None


def test_batch_validate_single_pass_shape(engine):
    nm, v = engine["nm"], engine["v"]
    cands = nm.sample_candidates(30, "平衡")
    out = v.batch_validate(cands)
    assert len(out) == len(cands)
    assert all("consistency" in r and "raw_consistency" in r for r in out)
    # sorted desc
    scores = [r["consistency"] for r in out]
    assert scores == sorted(scores, reverse=True)


def test_score_from_backward_no_tbd(engine):
    v = engine["v"]
    regime = engine["mm"].get_regime()
    back = v.backward(8)
    if back is None:
        return
    s = v._score_from_backward(back, regime)
    assert 0.0 <= s <= 1.0
