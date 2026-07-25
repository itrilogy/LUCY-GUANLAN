#!/usr/bin/env python3
"""
双色球预测分析工具 —— Web 服务入口

Flask + APScheduler 每日 00:00 自动更新
"""

import json, os, sys
from datetime import datetime

# 确保项目根目录在Python路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler

from config import HOST, PORT, DEBUG, PREDICT_FILE, UPDATE_HOUR, UPDATE_MINUTE
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


# ── 初始化引擎 ──────────────────────────────────────────────

def init_engine():
    """初始化所有引擎模块"""
    dh = DataHub().load()
    mm = MarketModel(dh)
    nm = NumberModel(dh)
    v = Validator(dh, mm, nm)
    p = Predictor(dh, mm, nm, v)
    return dh, mm, nm, v, p


# ── 全局单例 ────────────────────────────────────────────────

dh, mm, nm, v, p = init_engine()
last_run = None


def run_update():
    """执行预测更新"""
    global last_run
    print(f"[{datetime.now()}] 开始预测更新...")
    try:
        report = p.run(n_candidates=2000)
        p.save(report)
        last_run = datetime.now()
        print(f"[{datetime.now()}] 更新完成: {report['current_issue']}")
        return True
    except Exception as e:
        print(f"[{datetime.now()}] 更新失败: {e}")
        import traceback
        traceback.print_exc()
        return False


# ── 定时器 ──────────────────────────────────────────────────

scheduler = BackgroundScheduler()
scheduler.add_job(
    run_update,
    'cron',
    hour=UPDATE_HOUR,
    minute=UPDATE_MINUTE,
    id='daily_predict_update',
)
scheduler.start()

# 启动时立即跑一次
run_update()


# ── Flask ────────────────────────────────────────────────────

app = Flask(__name__, 
    template_folder='web/templates',
    static_folder='web/static',
    static_url_path='/static')


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
    """API: 执行预测，?evolve=true 启用全量进化"""
    evolve = request.args.get('evolve', 'false').lower() == 'true'
    report = p.run(n_candidates=2000, evolve=evolve)
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
    """API: 手动触发更新"""
    ok = run_update()
    return jsonify({'success': ok, 'time': str(datetime.now())})


@app.route('/api/predict/save', methods=['POST'])
def api_save_predictions():
    """保存预测结果（含批次流水号）"""
    import json as _json
    data = request.get_json(force=True)
    target = data.get('target_issue', dh.latest_issue)
    predictions = data.get('predictions', [])
    compounds = data.get('compound_plans', [])
    
    # 创建批次
    total = len(predictions) + len(compounds)
    dh.db_query("INSERT INTO predict_batch (target_issue,total_entries) VALUES (?,?)", (target, total))
    batch_id = dh.db_query_one("SELECT MAX(batch_id) FROM predict_batch")[0]
    
    inserted = 0
    # 保存单注
    for p in predictions:
        dh.db_query("INSERT INTO predictions (batch_id,target_issue,entry_type,rank,reds,blue,consistency,cost,est_prize1) VALUES (?,?,?,?,?,?,?,?,?)",
            (batch_id, target, 'single', p['rank'], _json.dumps(p['reds']), p['blue'], p['consistency'], p['cost'], p.get('est_prize1', 0)))
        inserted += 1
    # 保存复式
    rank_map = {0:'A',1:'B',2:'C',3:'D'}
    for i, c in enumerate(compounds):
        dh.db_query("INSERT INTO predictions (batch_id,target_issue,entry_type,rank,reds,blue,reds_count,blues_count,consistency,cost,total_cost,total_combos) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, target, 'compound', rank_map.get(i, chr(65+i)), _json.dumps(c['reds']), _json.dumps(c['blues']),
             len(c['reds']), len(c['blues']), c['consistency'], c.get('avg_match_rate', 0), c['total_cost'], c['total_combos']))
        inserted += 1
    
    return jsonify({'saved': inserted, 'batch_id': batch_id, 'target': target})


@app.route('/api/predict/comparison')
def api_comparison():
    """获取历史预测对照数据"""
    rows = dh.db_query("""
        SELECT p.id,p.batch_id,p.saved_at,p.target_issue,p.rank,p.reds,p.blue,p.consistency,p.hit_red,p.hit_blue,
               d.red1,d.red2,d.red3,d.red4,d.red5,d.red6,d.blue as actual_blue
        FROM predictions p LEFT JOIN draws d ON p.target_issue = d.issue
        ORDER BY p.target_issue DESC, p.rank
    """)
    results = []
    for r in rows:
        results.append({
            'id': r[0], 'batch_id': r[1], 'saved_at': r[2], 'target_issue': r[3],
            'rank': r[4], 'reds': r[5], 'blue': r[6], 'consistency': r[7],
            'hit_red': r[8], 'hit_blue': r[9],
            'actual_reds': [r[10],r[11],r[12],r[13],r[14],r[15]] if r[10] else None,
            'actual_blue': r[16],
        })
    return jsonify(results)


@app.route('/api/status')
def api_status():
    """API: 系统状态"""
    report = p.load_saved()
    return jsonify({
        'data_version': dh.latest_issue,
        'last_update': str(last_run) if last_run else None,
        'predict_ready': report is not None,
        'total_draws': dh.N,
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
