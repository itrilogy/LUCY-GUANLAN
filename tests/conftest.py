"""pytest fixtures — path bootstrap + mini DataHub."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mini_draws.json")


@pytest.fixture(scope="module")
def mini_json(tmp_path_factory):
    """Copy mini draws to temp SSQ path for isolated tests."""
    import shutil
    td = tmp_path_factory.mktemp("ssq")
    dest = td / "ssq_all.json"
    shutil.copy(FIXTURE, dest)
    return str(dest)


@pytest.fixture(scope="module")
def engine(mini_json, tmp_path_factory):
    """Fresh DataHub + models on mini fixture (module-scoped)."""
    # Isolate singleton + DB
    import config
    config.SSQ_FILE = mini_json
    config.DATA_DIR = str(tmp_path_factory.mktemp("data"))
    os.makedirs(config.DATA_DIR, exist_ok=True)
    # Redirect DB next to mini json
    import engine.data_hub as dh_mod
    dh_mod.DB_FILE = os.path.join(config.DATA_DIR, "ssq.db")
    # Also seed DB from JSON
    shutil_src = mini_json
    with open(shutil_src, encoding="utf-8") as f:
        data = json.load(f)
    # write canonical path used by migrate
    ssq_path = os.path.join(config.DATA_DIR, "ssq_all.json")
    with open(ssq_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    config.SSQ_FILE = ssq_path
    dh_mod.DB_FILE = os.path.join(config.DATA_DIR, "ssq.db")

    from engine.data_hub import DataHub
    from engine.market import MarketModel
    from engine.numbers import NumberModel
    from engine.validator import Validator

    DataHub._instance = None
    dh = DataHub().load(path=ssq_path, force=True)
    # ensure sqlite exists
    from scripts.init_db import migrate
    # migrate reads config paths — set JSON_FILE via env of module
    import scripts.init_db as idb
    idb.JSON_FILE = ssq_path
    idb.DB_FILE = dh_mod.DB_FILE
    migrate()
    dh.db_close()
    dh = DataHub().load(path=ssq_path, force=True)

    mm = MarketModel(dh)
    nm = NumberModel(dh)
    v = Validator(dh, mm, nm)
    return {"dh": dh, "mm": mm, "nm": nm, "v": v}
