"""MarketModel soft_extend keeps history labels, extends new rows."""


def test_soft_extend_appends(engine):
    import copy
    dh = engine["dh"]
    mm = engine["mm"]
    n0 = dh.N
    labels0 = mm._regime_labels.copy()

    # fabricate one extra period cloned from last
    last = copy.deepcopy(dh.data[-1])
    last["期号"] = str(int(last["期号"]) + 1)
    last["开奖日期"] = "2099-01-01"
    dh.data.append(last)
    dh.N = len(dh.data)
    # rebuild market arrays only (lightweight path for test)
    dh._build_market_vars()
    dh._build_profiles()
    # blue miss not needed for soft_extend

    ok = mm.soft_extend(dh)
    assert ok is True
    assert len(mm._regime_labels) == n0 + 1
    assert (mm._regime_labels[:n0] == labels0).all()
