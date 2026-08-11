"""
双色球预测分析工具 · 全局配置
"""
import json
import os

# ── 路径 ──
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
SSQ_FILE = os.path.join(DATA_DIR, "ssq_all.json")
PREDICT_FILE = os.path.join(DATA_DIR, "predict_result.json")
FEATURES_FILE = os.path.join(DATA_DIR, "features.npz")
ENGINE_STATE_FILE = os.path.join(DATA_DIR, "engine_state.json")
SCORING_DEFAULTS_FILE = os.path.join(DATA_DIR, "eval", "scoring_defaults.json")

# ── 数据源 ──
SSQ_URL = "https://datachart.500.com/ssq/history/newinc/history.php"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
FETCH_LIMIT = 5000
FETCH_TIMEOUT = 60
FETCH_RETRIES = 3

# ── 分析参数 ──
N_RED = 33
N_BLUE = 16
N_DRAW = 6
POOL_LOW = 2e8
POOL_HIGH = 10e8
BIRTHDAY_EFFECT = 1.16

# ── 市场 Regime ──
REGIME_N_CLUSTERS = 5
REGIME_PCA_COMPONENTS = 2
POOL_STATE_NAMES = ["枯竭", "低位", "正常", "高位", "超高"]

# ── Markov ──
TRANSITION_N_STATES = 12

# ── 号码采样 ──
N_CANDIDATES = 10000
TOP_N = 10
SAMPLE_WEIGHTED = os.environ.get("SSQ_SAMPLE_WEIGHTED", "0") in ("1", "true", "yes")
SAMPLE_BLUE_MODE = os.environ.get("SSQ_SAMPLE_BLUE_MODE", "uniform")  # uniform | empirical
FEATURES_CACHE_ENABLED = os.environ.get("SSQ_FEATURES_CACHE", "1") not in ("0", "false", "no")

# ── 双向验证 ──
VALIDATOR_HISTORY_WINDOW = 200
CONSISTENCY_CURRENT_WEIGHT = 0.7
CONSISTENCY_ENTROPY_WEIGHT = 0.3
BACKWARD_LUT_MAX_PRIZE = 200
BACKWARD_TOP_K = 20
EVOLVE_BACKWARD_TOP_K = 30


def prize_clamp(est_prize, max_prize=None):
    mp = BACKWARD_LUT_MAX_PRIZE if max_prize is None else max_prize
    return int(round(max(0, min(mp, est_prize))))


# ── 反馈回路系数 ──
FEEDBACK_POOL_TO_BET_R = 0.678
FEEDBACK_BET_TO_PRIZE_R = 0.574
FEEDBACK_PRIZE_TO_POOL_R = -0.341

# ── 遗传进化 ──
EVOLVE_POP_SIZE = 200
EVOLVE_GENERATIONS = 30
EVOLVE_TEST_RATIO = 0.2
EVOLVE_LUT_MAX_PRIZE = BACKWARD_LUT_MAX_PRIZE
EVOLVE_TOP_ELITES = 15
EVOLVE_MUTATE_RATE = 0.3
EVOLVE_CROSSOVER_RATE = 0.7

# ── 评分默认（PR-15/16：evolution 默认 off；cutover 可覆盖）──
SCORING_MODE = "legacy"
SCORING_EXPERIMENTAL_GATE = True
EVOLUTION_MODE = "off"
FORWARD_COST_ALPHA = 0.05
RANK_WEIGHTS = {
    "anti_crowd": 0.40,
    "structure": 0.40,
    "market_fit": 0.20,
}
BACKWARD_MODE = "prize"
BACKWARD_DIST_WEIGHTS = {
    "w_p": 1.0,
    "w_pool": 0.5,
    "w_bet": 0.5,
    "w_r": 0.25,
}


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def apply_runtime_overrides():
    """
    优先级：环境变量 > data/eval/scoring_defaults.json (cutover) > engine_state α > 源码默认
    """
    global SCORING_MODE, SCORING_EXPERIMENTAL_GATE, EVOLUTION_MODE
    global FORWARD_COST_ALPHA, BACKWARD_MODE

    # cutover / scoring_defaults
    sd = _load_json(SCORING_DEFAULTS_FILE)
    if sd:
        if "SCORING_MODE" in sd:
            SCORING_MODE = sd["SCORING_MODE"]
        if "SCORING_EXPERIMENTAL_GATE" in sd:
            SCORING_EXPERIMENTAL_GATE = bool(sd["SCORING_EXPERIMENTAL_GATE"])
        if "EVOLUTION_MODE" in sd:
            EVOLUTION_MODE = sd["EVOLUTION_MODE"]
        if "BACKWARD_MODE" in sd:
            BACKWARD_MODE = sd["BACKWARD_MODE"]
        if "FORWARD_COST_ALPHA" in sd:
            FORWARD_COST_ALPHA = float(sd["FORWARD_COST_ALPHA"])

    # engine_state alpha
    st = _load_json(ENGINE_STATE_FILE)
    if "forward_cost_alpha" in st:
        FORWARD_COST_ALPHA = float(st["forward_cost_alpha"])

    # env 最高优先
    if os.environ.get("SSQ_SCORING_MODE"):
        SCORING_MODE = os.environ["SSQ_SCORING_MODE"]
    if os.environ.get("SSQ_EVOLUTION_MODE"):
        EVOLUTION_MODE = os.environ["SSQ_EVOLUTION_MODE"]
    if os.environ.get("SSQ_FORWARD_COST_ALPHA"):
        FORWARD_COST_ALPHA = float(os.environ["SSQ_FORWARD_COST_ALPHA"])
    if os.environ.get("SSQ_BACKWARD_MODE"):
        BACKWARD_MODE = os.environ["SSQ_BACKWARD_MODE"]
    if os.environ.get("SSQ_ALLOW_EXPERIMENTAL_SCORING") in ("1", "true", "yes"):
        SCORING_EXPERIMENTAL_GATE = False
    if os.environ.get("SSQ_FORCE_EXPERIMENTAL_GATE") in ("1", "true", "yes"):
        SCORING_EXPERIMENTAL_GATE = True


apply_runtime_overrides()

# ── 引擎重训 ──
FULL_REFIT_DAYS = 7

# ── Web ──
HOST = "0.0.0.0"
PORT = 8080
DEBUG = False

# ── 更新调度 ──
DRAW_WEEKDAYS = [1, 3, 6]
UPDATE_HOUR = 22
UPDATE_MINUTE = 0
STARTUP_FETCH = "auto"
STALE_DAYS = 2
