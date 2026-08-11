"""Cutover helpers + features cache smoke."""


def test_features_fingerprint():
    from engine.features_cache import data_fingerprint
    fp = data_fingerprint()
    assert isinstance(fp, str) and len(fp) >= 8


def test_rank_order_helper():
    from scripts.migrate_predictions_rank_v2 import rank_order
    assert rank_order(1) == 1
    assert rank_order("A") == 101
    assert rank_order("3") == 3


def test_resolve_evolution_default_off():
    import config as cfg
    # source default is off unless cutover/env overrides
    assert cfg.EVOLUTION_MODE in ("off", "legacy_consistency", "market_hyper", "compound")
