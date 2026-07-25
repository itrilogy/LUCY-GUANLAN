"""
双色球预测分析工具 · 全局配置
"""
import os

# ── 路径 ──
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
SSQ_FILE = os.path.join(DATA_DIR, "ssq_all.json")
PREDICT_FILE = os.path.join(DATA_DIR, "predict_result.json")
FEATURES_FILE = os.path.join(DATA_DIR, "features.npz")

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
POOL_LOW = 2e8       # <2亿=蓄水
POOL_HIGH = 10e8     # >10亿=放水
BIRTHDAY_EFFECT = 1.16  # 生日号效应量

# ── 市场 Regime ──
REGIME_N_CLUSTERS = 5
REGIME_PCA_COMPONENTS = 2
POOL_STATE_NAMES = ["枯竭","低位","正常","高位","超高"]

# ── Markov 转移核 ──
TRANSITION_N_STATES = 12

# ── 号码采样 ──
N_CANDIDATES = 10000
TOP_N = 10

# ── 双向验证 ──
VALIDATOR_HISTORY_WINDOW = 200
CONSISTENCY_CURRENT_WEIGHT = 0.7
CONSISTENCY_ENTROPY_WEIGHT = 0.3

# ── 反馈回路系数 (来自历史回归, 固化) ──
FEEDBACK_POOL_TO_BET_R = 0.678
FEEDBACK_BET_TO_PRIZE_R = 0.574
FEEDBACK_PRIZE_TO_POOL_R = -0.341

# ── 遗传进化参数 ──
EVOLVE_POP_SIZE = 200           # 种群
EVOLVE_GENERATIONS = 30         # 代数
EVOLVE_TEST_RATIO = 0.2         # 训练期占比 (后20%=696期)
EVOLVE_LUT_MAX_PRIZE = 200      # 预计算backward LUT范围
EVOLVE_TOP_ELITES = 15          # 每代保留精英数
EVOLVE_MUTATE_RATE = 0.3        # 变异率
EVOLVE_CROSSOVER_RATE = 0.7     # 杂交率

# ── Web 服务 ──
HOST = "0.0.0.0"
PORT = 8080
DEBUG = False

# ── 更新调度 ──
UPDATE_HOUR = 0
UPDATE_MINUTE = 0
