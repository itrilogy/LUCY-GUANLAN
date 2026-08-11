#!/usr/bin/env python3
"""
双色球预测分析工具 —— Web 服务入口

Flask + APScheduler：开奖日 22:00 自动爬取并预测
"""

import json, os, sys, threading
from datetime import datetime, date, timedelta

# 确保项目根目录在Python路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler

from config import (
    HOST, PORT, DEBUG, PREDICT_FILE,
    UPDATE_HOUR, UPDATE_MINUTE, DRAW_WEEKDAYS, STARTUP_FETCH, STALE_DAYS,
    FULL_REFIT_DAYS, ENGINE_STATE_FILE,
)
from engine.data_hub import DataHub
from engine.market import MarketModel
from engine.numbers import NumberModel
from engine.validator import Validator
from engine.predictor import Predictor

# NumPy JSON 兼容
import numpy as np

class NumpyEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        if isinstance(o, (np.bool_,)): return bool(o)
        if isinstance(o, np.ndarray): return o.tolist()
        return super().default(o)


# ── 引擎状态（须在 init_engine 之前定义）──────────────────

def _load_engine_state():
    try:
        with open(ENGINE_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_engine_state(**kwargs):
    st = _load_engine_state()
    st.update(kwargs)
    st["updated_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        with open(ENGINE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[{datetime.now()}] engine_state 写入失败: {e}")


def _need_full_refit():
    """超过 FULL_REFIT_DAYS 或无 last_full_refit → full"""
    st = _load_engine_state()
    last = st.get("last_full_refit")
    if not last:
        return True
    try:
        t0 = datetime.fromisoformat(last)
        return (datetime.now() - t0).days >= FULL_REFIT_DAYS
    except Exception:
        return True


# ── 初始化引擎 ──────────────────────────────────────────────

def init_engine():
    """初始化所有引擎模块（启动 full fit，记录 engine_state）"""
    dh = DataHub().load()
    mm = MarketModel(dh)
    nm = NumberModel(dh)
    v = Validator(dh, mm, nm)
    p = Predictor(dh, mm, nm, v)
    try:
        _save_engine_state(
            last_full_refit=datetime.now().isoformat(timespec="seconds"),
            latest_issue=dh.latest_issue,
            N=dh.N,
            mode="full",
            boot=True,
        )
    except Exception:
        pass
    return dh, mm, nm, v, p


def reinit_engine(mode="auto"):
    """
    数据变更后重建模型。
    mode:
      - full: 全量 GMM/KMeans + NumberModel
      - soft: 进程内扩展标签（需已有 mm）；失败则 full
      - auto: 距上次 full 超过 FULL_REFIT_DAYS → full，否则 soft
    CLI 应始终 full；本函数给 app 长驻进程使用。
    """
    global dh, mm, nm, v, p
    if mode == "auto":
        mode = "full" if _need_full_refit() else "soft"

    n_before = getattr(mm, "N", 0) if mm is not None else 0
    dh = DataHub().reload()

    used = mode
    if mode == "soft" and mm is not None and n_before > 0:
        ok = mm.soft_extend(dh)
        if ok:
            nm = NumberModel(dh)  # 频率表/成本序列重建（O(N) 可接受）
            if v is not None:
                v.invalidate_backward_lut()
            v = Validator(dh, mm, nm)
            p = Predictor(dh, mm, nm, v)
            _save_engine_state(
                last_soft_extend=datetime.now().isoformat(timespec="seconds"),
                latest_issue=dh.latest_issue,
                N=dh.N,
                mode="soft",
            )
            print(f"[{datetime.now()}] soft reinit OK → {dh.latest_issue} N={dh.N}")
            return dh, mm, nm, v, p
        used = "full"
        print(f"[{datetime.now()}] soft reinit 失败，回退 full")

    mm = MarketModel(dh)
    nm = NumberModel(dh)
    v = Validator(dh, mm, nm)
    p = Predictor(dh, mm, nm, v)
    _save_engine_state(
        last_full_refit=datetime.now().isoformat(timespec="seconds"),
        latest_issue=dh.latest_issue,
        N=dh.N,
        mode="full",
    )
    print(f"[{datetime.now()}] full reinit OK → {dh.latest_issue} N={dh.N} ({used})")
    return dh, mm, nm, v, p


# ── 全局单例 ────────────────────────────────────────────────

dh, mm, nm, v, p = init_engine()
last_run = None
last_data_update = None
_update_lock = threading.Lock()


def _latest_draw_date(hub=None):
    hub = hub or dh
    try:
        return datetime.strptime(hub.dates[-1], "%Y-%m-%d").date()
    except Exception:
        return None


def should_fetch_now(hub=None, now=None):
    """
    判断是否需要从远端拉数据。

    - 本地最新开奖距今 >= STALE_DAYS
    - 或今天是开奖日、已过 UPDATE_HOUR，且本地还没有今天的开奖
    """
    hub = hub or dh
    now = now or datetime.now()
    latest = _latest_draw_date(hub)
    if latest is None:
        return True
    today = now.date()
    gap = (today - latest).days
    if gap >= STALE_DAYS:
        return True
    if (
        today.weekday() in DRAW_WEEKDAYS
        and now.hour >= UPDATE_HOUR
        and latest < today
    ):
        return True
    return False


def run_update(fetch_data=True):
    """
    执行完整更新: 爬取最新开奖 → 重建引擎 → 重跑预测。
    fetch_data=False 时仅重跑预测（不访问外网）。
    """
    global last_run, last_data_update
    if not _update_lock.acquire(blocking=False):
        print(f"[{datetime.now()}] 更新已在进行，跳过")
        return {"success": False, "error": "update_in_progress"}
    try:
        print(f"[{datetime.now()}] 开始更新...")
        data_stats = None
        if fetch_data:
            print(f"[{datetime.now()}] 爬取 500.com 最新数据...")
            data_stats = dh.update_from_remote(
                progress_callback=lambda m: print(f"  {m}")
            )
            if data_stats.get("success"):
                added = data_stats.get("added", 0)
                updated = data_stats.get("updated", 0)
                print(
                    f"[{datetime.now()}] 数据合并: +{added} 新增, "
                    f"{updated} 更新, 最新 {data_stats.get('after_issue')} "
                    f"(共 {data_stats.get('after_n')} 期)"
                )
                if added or updated:
                    reinit_engine(mode="auto")  # 进程内 soft；到期 full
                last_data_update = datetime.now()
            else:
                print(
                    f"[{datetime.now()}] 数据爬取失败: "
                    f"{data_stats.get('error')}，使用本地数据继续预测"
                )

        report = p.run(n_candidates=2000)
        p.save(report)
        last_run = datetime.now()
        print(
            f"[{datetime.now()}] 更新完成: 数据期={dh.latest_issue}, "
            f"预测目标={report.get('current_issue')}"
        )
        return {
            "success": True,
            "latest_issue": dh.latest_issue,
            "total_draws": dh.N,
            "predict_issue": report.get("current_issue"),
            "data_stats": data_stats,
        }
    except Exception as e:
        print(f"[{datetime.now()}] 更新失败: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        _update_lock.release()


def _scheduled_draw_update():
    """开奖日定时任务：强制爬取 + 预测"""
    print(f"[{datetime.now()}] 开奖日定时更新触发")
    run_update(fetch_data=True)


def _startup_update():
    """
    启动策略:
    - STARTUP_FETCH=True  → 后台完整更新
    - STARTUP_FETCH=False → 仅在无预测文件时本地预测
    - STARTUP_FETCH=auto  → 数据可能过期则后台爬取，否则确保有预测结果
    """
    need_fetch = False
    if STARTUP_FETCH is True or str(STARTUP_FETCH).lower() == "true":
        need_fetch = True
    elif STARTUP_FETCH is False or str(STARTUP_FETCH).lower() == "false":
        need_fetch = False
    else:
        need_fetch = should_fetch_now()

    if need_fetch:
        print(f"[{datetime.now()}] 启动: 数据可能过期，后台爬取更新...")
        threading.Thread(
            target=lambda: run_update(fetch_data=True),
            daemon=True,
            name="startup-update",
        ).start()
    else:
        report = p.load_saved()
        if report is None:
            print(f"[{datetime.now()}] 启动: 无缓存预测，本地快速预测...")
            run_update(fetch_data=False)
        else:
            print(
                f"[{datetime.now()}] 启动: 本地数据新鲜 "
                f"({dh.latest_issue} / {dh.dates[-1]})，跳过爬取"
            )


# ── 定时器：开奖日 22:00 ────────────────────────────────────

scheduler = BackgroundScheduler()
scheduler.add_job(
    _scheduled_draw_update,
    "cron",
    day_of_week=",".join(str(d) for d in DRAW_WEEKDAYS),
    hour=UPDATE_HOUR,
    minute=UPDATE_MINUTE,
    id="draw_day_update",
    replace_existing=True,
)
scheduler.start()

_startup_update()


# ── Flask ────────────────────────────────────────────────────

app = Flask(__name__, 
    template_folder='web/templates',
    static_folder='web/static',
    static_url_path='/static')

# 开发时模板/静态资源不缓存，避免对照页样式不刷新
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0


@app.after_request
def _no_cache_html(resp):
    if resp.content_type and 'text/html' in resp.content_type:
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


@app.route('/')
def index():
    """主页面"""
    report = p.load_saved()
    if report is None:
        report = p.run(n_candidates=2000)
        p.save(report)
    
    return render_template('index.html', 
                         report=report,
                         last_run=last_run.strftime('%Y-%m-%d %H:%M') if last_run else '首次运行')


@app.route('/api/predict')
def api_predict():
    """API: 最新预测"""
    report = p.load_saved()
    if report is None:
        report = p.run(n_candidates=2000)
        p.save(report)
    return jsonify(report)


@app.route('/api/predict/run')
def api_predict_run():
    """API: 执行预测。?evolve=true 启用研究用自洽进化；?mode=legacy|multi|dual"""
    evolve = request.args.get('evolve', 'false').lower() == 'true'
    mode = request.args.get('mode', None)
    report = p.run(n_candidates=2000, evolve=evolve, scoring_mode=mode)
    p.save(report)
    return jsonify(report)


@app.route('/api/predict/progress')
def api_progress():
    """API: 轮询当前进度"""
    from config import ROOT
    prog_file = os.path.join(ROOT, 'data', 'progress.json')
    try:
        with open(prog_file) as f:
            return jsonify(json.load(f))
    except:
        return jsonify({'running': False, 'stage': 'idle', 'progress': 0, 'message': '就绪'})


@app.route('/api/predict/history')
def api_history():
    """API: 历史趋势数据"""
    from collections import Counter
    N = dh.N
    
    # 红蓝球频率
    red_counter = Counter()
    blue_counter = Counter()
    for t in range(N):
        for j in range(1,7):
            red_counter[dh.data[t][f"红球{j}"]] += 1
        blue_counter[dh.data[t]["蓝球"]] += 1
    red_freq = [{'num': n, 'count': c} for n, c in sorted(red_counter.items())]
    blue_freq = [{'num': n, 'count': c} for n, c in sorted(blue_counter.items())]
    
    # 三区出现次数 (每期)
    zone_counts = []
    for t in range(0, N, 10):  # 每10期采样
        reds = [dh.data[t][f"红球{j}"] for j in range(1,7)]
        z1 = sum(1 for r in reds if 1 <= r <= 11)
        z2 = sum(1 for r in reds if 12 <= r <= 22)
        z3 = sum(1 for r in reds if 23 <= r <= 33)
        zone_counts.append({
            'issue': dh.issues[t],
            'z1': z1, 'z2': z2, 'z3': z3,
        })
    
    # 奖池曲线
    pool_curve = [{'issue': dh.issues[t], 'pool': float(dh.pool[t]/1e8)}
                  for t in range(0, N, 20)]
    
    # Regime分布 + 样本期号
    regime_counts = Counter()
    regime_samples = {k: [] for k in range(5)}
    for t in range(N):
        k = int(mm._regime_labels[t])
        regime_counts[k] += 1
        if len(regime_samples[k]) < 3:
            regime_samples[k].append({
                'issue': dh.issues[t],
                'reds': sorted([dh.data[t][f"红球{j}"] for j in range(1,7)]),
                'blue': dh.data[t]["蓝球"],
            })
    
    regime_dist = [{
        'regime': int(k),
        'count': int(v),
        'pct': round(v/N*100, 1),
        'samples': regime_samples.get(k, []),
    } for k, v in regime_counts.items()]
    
    # 全量分区序列 (用于分区趋势图)
    zone_series = []
    for t in range(N):
        reds = [dh.data[t][f"红球{j}"] for j in range(1,7)]
        zone_series.append({
            'z1': sum(1 for r in reds if 1<=r<=11),
            'z2': sum(1 for r in reds if 12<=r<=22),
            'z3': sum(1 for r in reds if 23<=r<=33),
        })
    
    # 奖池全量序列 (所有期)
    pool_dense = [{'issue': dh.issues[t], 'pool': float(dh.pool[t]/1e8)}
                  for t in range(N)]
    
    # ── 后端渲染 SVG 图表 ──────────────────────────────────
    def _bar_svg(freq, color, svgW):
        mn = min(r['count'] for r in freq)
        mc = max(r['count'] for r in freq)
        base = max(0, mn - 1)
        top = min(1000, mc + 1)
        rng = max(1, top - base)
        bars = ''
        n = len(freq)
        barW = max(3, svgW / (n + 1) - 1)
        for i, r in enumerate(freq):
            x = 22 + i * (barW + 1)
            hgt = max(2, (r['count'] - base) / rng * 82)
            y = 96 - hgt
            bars += f'<rect x="{x:.1f}" y="{y:.1f}" width="{barW:.1f}" height="{hgt:.1f}" fill="{color}" rx="1"/>'
            bars += f'<text x="{x + barW / 2:.1f}" y="{y - 2}" text-anchor="middle" font-size="6" fill="{color}" font-weight="700">{r["count"]}</text>'
        y_axis = f'<text x="0" y="14" font-size="9" fill="#e0e6f0">{top}</text>'
        y_axis += f'<text x="0" y="50" font-size="9" fill="#e0e6f0">{round((top + base) / 2)}</text>'
        y_axis += f'<text x="0" y="96" font-size="9" fill="#e0e6f0">{base}</text>'
        svg = f'<svg viewBox="0 0 {svgW} 100" style="width:100%;height:110px">{y_axis}{bars}</svg>'
        return svg, base, top
    
    red_svg, rb, rt = _bar_svg(red_freq, '#e74c3c', 600)
    blue_svg, bb, bt = _bar_svg(blue_freq, '#3498db', 280)
    
    # 奖池折线图 SVG (Y轴从0到max+1)
    mp = max(p['pool'] for p in pool_dense)
    rng2 = max(1, mp + 1)  # 范围 = max+1 - 0
    pts = ' '.join(f"{62 + i / (len(pool_dense) - 1) * 1025:.1f},{3 + (mp - p['pool']) / rng2 * 85:.1f}" for i, p in enumerate(pool_dense))
    pool_svg = f'''<svg viewBox="0 0 1100 100" style="width:100%;height:120px">
      <line x1="60" y1="5" x2="60" y2="95" stroke="#1e2d50" stroke-width="0.5"/>
      <text x="55" y="16" font-size="11" fill="#e0e6f0" text-anchor="end">{mp+1:.0f}</text>
      <text x="55" y="28" font-size="11" fill="#5a6a8a" text-anchor="end">{((mp+1)*0.8):.0f}</text>
      <text x="55" y="40" font-size="11" fill="#5a6a8a" text-anchor="end">{((mp+1)*0.6):.0f}</text>
      <text x="55" y="52" font-size="11" fill="#5a6a8a" text-anchor="end">{((mp+1)*0.4):.0f}</text>
      <text x="55" y="64" font-size="11" fill="#5a6a8a" text-anchor="end">{((mp+1)*0.2):.0f}</text>
      <text x="55" y="92" font-size="11" fill="#e0e6f0" text-anchor="end">0</text>
      <polyline points="{pts}" fill="none" stroke="#f1c40f" stroke-width="1.5"/>
    </svg>'''
    
    return jsonify({
        'red_freq': red_freq,
        'blue_freq': blue_freq,
        'zone_counts': zone_counts,
        'pool_curve': pool_curve,
        'regime_dist': regime_dist,
        'zone_series': zone_series,
        'pool_dense': pool_dense,
        'red_chart_svg': red_svg,
        'blue_chart_svg': blue_svg,
        'pool_chart_svg': pool_svg,
    })


@app.route('/api/periods')
def api_periods():
    """API: 分页查询每期号码 (SQLite)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    per_page = min(200, max(10, per_page))
    offset = (page - 1) * per_page
    
    rows = dh.db_query(
        "SELECT issue,red1,red2,red3,red4,red5,red6,blue FROM draws ORDER BY issue DESC LIMIT ? OFFSET ?",
        (per_page, offset)
    )
    total = dh.db_query_one("SELECT COUNT(*) FROM draws")[0]
    
    periods = [{'issue': r[0], 'reds': [r[1],r[2],r[3],r[4],r[5],r[6]], 'blue': r[7]} for r in rows]
    return jsonify({'periods': periods, 'total': total, 'page': page, 'per_page': per_page})


@app.route('/api/update')
def api_update():
    """API: 手动触发完整更新（爬取+预测）。?predict_only=1 仅重跑预测"""
    predict_only = request.args.get('predict_only', '0') in ('1', 'true', 'yes')
    result = run_update(fetch_data=not predict_only)
    result['time'] = str(datetime.now())
    return jsonify(result)


@app.route('/api/predict/save', methods=['POST'])
def api_save_predictions():
    """保存预测结果（含批次流水号）"""
    import json as _json
    data = request.get_json(force=True)
    target = data.get('target_issue', dh.next_issue)
    predictions = data.get('predictions', [])
    compounds = data.get('compound_plans', [])
    
    # 创建批次
    total = len(predictions) + len(compounds)
    dh.db_query("INSERT INTO predict_batch (target_issue,total_entries) VALUES (?,?)", (target, total))
    batch_id = dh.db_query_one("SELECT MAX(batch_id) FROM predict_batch")[0]
    
    def _rank_order(label):
        s = str(label)
        if s.isdigit():
            return int(s)
        if len(s) == 1 and s.isalpha():
            return 100 + (ord(s.upper()) - 64)  # A=101 ...
        return 0

    inserted = 0
    # 保存单注（rank 统一 TEXT + rank_order）
    for p in predictions:
        rlabel = str(p['rank'])
        dh.db_query(
            "INSERT INTO predictions (batch_id,target_issue,entry_type,rank,rank_order,reds,blue,consistency,cost,est_prize1) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (batch_id, target, 'single', rlabel, _rank_order(rlabel),
             _json.dumps(p['reds']), p['blue'], p['consistency'], p['cost'], p.get('est_prize1', 0)),
        )
        inserted += 1
    # 保存复式
    rank_map = {0: 'A', 1: 'B', 2: 'C', 3: 'D'}
    for i, c in enumerate(compounds):
        rlabel = rank_map.get(i, chr(65 + i))
        dh.db_query(
            "INSERT INTO predictions (batch_id,target_issue,entry_type,rank,rank_order,reds,blue,"
            "reds_count,blues_count,consistency,cost,total_cost,total_combos) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, target, 'compound', rlabel, _rank_order(rlabel),
             _json.dumps(c['reds']), _json.dumps(c['blues']),
             len(c['reds']), len(c['blues']), c['consistency'], c.get('avg_match_rate', 0),
             c['total_cost'], c['total_combos']),
        )
        inserted += 1

    return jsonify({'saved': inserted, 'batch_id': batch_id, 'target': target})


@app.route('/api/predict/comparison')
def api_comparison():
    """
    获取历史预测对照数据。

    已开奖（draws 有该期）：计算命中红/蓝集合，供前端点亮。
    未开奖：drawn=false，不计算命中。
    """
    import json as _json

    # 回填命中：默认全量重算已开奖历史（保证历史预测无需再点保存即可点亮）
    force_bf = request.args.get("backfill", "1") not in ("0", "false", "no")
    try:
        dh.backfill_prediction_hits(force=force_bf)
    except Exception:
        try:
            dh.backfill_prediction_hits(force=False)
        except Exception:
            pass

    rows = dh.db_query("""
        SELECT p.id,p.batch_id,p.saved_at,p.target_issue,p.rank,p.entry_type,p.reds,p.blue,
               p.consistency,p.hit_red,p.hit_blue,p.reds_count,p.blues_count,
               d.red1,d.red2,d.red3,d.red4,d.red5,d.red6,d.blue as actual_blue
        FROM predictions p LEFT JOIN draws d ON p.target_issue = d.issue
        ORDER BY p.target_issue DESC, p.rank_order, p.rank
    """)
    results = []
    for r in rows:
        # parse predicted reds
        pred_reds_raw = r[6]
        try:
            pred_reds = _json.loads(pred_reds_raw) if isinstance(pred_reds_raw, str) else list(pred_reds_raw or [])
        except Exception:
            pred_reds = []
        pred_reds = [int(x) for x in pred_reds if x is not None]

        # parse predicted blue(s)
        pred_blue_raw = r[7]
        pred_blues = []
        if pred_blue_raw is not None:
            if isinstance(pred_blue_raw, str) and pred_blue_raw.strip().startswith("["):
                try:
                    pred_blues = [int(x) for x in _json.loads(pred_blue_raw)]
                except Exception:
                    pred_blues = []
            else:
                try:
                    pred_blues = [int(pred_blue_raw)]
                except (TypeError, ValueError):
                    pred_blues = []

        has_draw = r[13] is not None  # red1
        actual_reds = None
        actual_blue = None
        hit_red_nums = []
        hit_blue_nums = []
        hit_red = r[9]
        hit_blue = r[10]

        if has_draw:
            actual_reds = [int(r[13]), int(r[14]), int(r[15]), int(r[16]), int(r[17]), int(r[18])]
            actual_blue = int(r[19]) if r[19] is not None else None
            actual_set = set(actual_reds)
            hit_red_nums = sorted(set(pred_reds) & actual_set)
            if actual_blue is not None:
                hit_blue_nums = sorted(b for b in pred_blues if b == actual_blue)
            # 即时计算（避免 DB 未回填时前端无数据）
            if hit_red is None:
                hit_red = len(hit_red_nums)
            if hit_blue is None:
                hit_blue = 1 if hit_blue_nums else 0

        results.append({
            'id': r[0],
            'batch_id': r[1],
            'saved_at': r[2],
            'target_issue': r[3],
            'rank': r[4],
            'entry_type': r[5] or 'single',
            'reds': pred_reds,
            'reds_raw': pred_reds_raw,
            'blue': pred_blue_raw,
            'blues': pred_blues,
            'consistency': r[8],
            'hit_red': hit_red,
            'hit_blue': hit_blue,
            'reds_count': r[11],
            'blues_count': r[12],
            'drawn': bool(has_draw),
            'actual_reds': actual_reds,
            'actual_blue': actual_blue,
            'hit_red_nums': hit_red_nums,
            'hit_blue_nums': hit_blue_nums,
        })
    return jsonify(results)


@app.route('/api/status')
def api_status():
    """API: 系统状态"""
    import config as cfg
    report = p.load_saved()
    return jsonify({
        'data_version': dh.latest_issue,
        'latest_date': dh.dates[-1] if dh.dates else None,
        'next_issue': dh.next_issue,
        'last_update': str(last_run) if last_run else None,
        'last_data_update': str(last_data_update) if last_data_update else None,
        'predict_ready': report is not None,
        'total_draws': dh.N,
        'should_fetch': should_fetch_now(),
        'draw_weekdays': DRAW_WEEKDAYS,
        'update_cron': f"{UPDATE_HOUR:02d}:{UPDATE_MINUTE:02d} weekdays={DRAW_WEEKDAYS}",
        'scoring_mode': cfg.SCORING_MODE,
        'scoring_experimental_gate': cfg.SCORING_EXPERIMENTAL_GATE,
        'evolution_mode': cfg.EVOLUTION_MODE,
        'backward_mode': cfg.BACKWARD_MODE,
        'disclaimer': '一致性≠中奖概率；市场可分析、号码近随机',
    })


@app.route('/api/predict/backtrack')
def api_backtrack():
    """API: 反向回溯 (T_bwd) — 从当前态倒推前期市场状态"""
    steps = request.args.get('steps', 5, type=int)
    steps = min(10, max(1, steps))
    
    current_t = dh.latest_t
    current_regime = mm.get_regime(current_t)
    regime_names = ['崩溃态','蓄水态','大奖态','增长态','成熟态']
    
    # 获取每个Regime的历史均值和范围
    regime_stats = {}
    for k in range(5):
        mask = mm._regime_labels == k
        if mask.sum() > 0:
            regime_stats[k] = {
                'name': regime_names[k],
                'avg_pool': float(np.mean(dh.pool[mask]) / 1e8),
                'avg_bet': float(np.mean(dh.bet[mask]) / 1e8),
                'avg_prize1': float(np.mean(dh.p1c[mask])),
                'count': int(mask.sum()),
            }
    
    # 从当前Regime反向推演
    chain = [{'step': 0, 'regime': int(current_regime), 'name': regime_names[current_regime],
              'pool': float(dh.pool[current_t]/1e8), 'bet': float(dh.bet[current_t]/1e8),
              'prize1': int(dh.p1c[current_t]), 'stat': regime_stats.get(current_regime, {})}]
    
    current_k = current_regime
    for s in range(1, steps + 1):
        bwd_dist = mm.backward_markov(current_k, steps=1)
        top_k = int(np.argmax(bwd_dist))
        chain.append({'step': s, 'regime': int(top_k), 'name': regime_names[top_k],
                      'prob': float(bwd_dist[top_k]),
                      'pool_range': [float(np.percentile(dh.pool[mm._regime_labels==top_k], 25)/1e8),
                                     float(np.percentile(dh.pool[mm._regime_labels==top_k], 75)/1e8)],
                      'prize1_range': [float(np.percentile(dh.p1c[mm._regime_labels==top_k], 25)),
                                       float(np.percentile(dh.p1c[mm._regime_labels==top_k], 75))],
                      'stat': regime_stats.get(top_k, {})})
        current_k = top_k
    
    return jsonify({'current_issue': dh.issues[current_t], 'chain': chain})


if __name__ == '__main__':
    print(f"启动服务: http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=DEBUG)
