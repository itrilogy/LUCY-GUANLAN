"""Greenfield smoke tests."""


def test_import_config():
    import config
    assert config.N_RED == 33
    assert config.BACKWARD_TOP_K == 20


def test_prize_clamp():
    from config import prize_clamp
    assert prize_clamp(-1) == 0
    assert prize_clamp(3.6) == 4
    assert prize_clamp(999) == 200
