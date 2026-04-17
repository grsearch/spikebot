"""Dashboard v6 - 完整版"""
import asyncio, json, logging, time, itertools, statistics
import config as cfg_module
from aiohttp import web
from bot import STATE

logger = logging.getLogger(__name__)

# ── CSS ──────────────────────────────────────────────────────
_CSS = """
:root{--bg:#0a0c10;--s1:#111318;--s2:#181c24;--bd:#22283a;
--gr:#00d48a;--rd:#ff3d5a;--bl:#3d8eff;--am:#ffb020;--pu:#a855f7;
--tx:#dde3f0;--mt:#4a5568;--r:10px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:'SF Mono','Fira Code',monospace;font-size:12px}
header{background:var(--s1);border-bottom:1px solid var(--bd);padding:9px 18px;
  display:flex;align-items:center;gap:10px;position:sticky;top:0;z-index:100}
.dot{width:8px;height:8px;border-radius:50%;background:var(--mt);flex-shrink:0}
.dot.on{background:var(--gr);box-shadow:0 0 7px var(--gr);animation:blink 1.8s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
h1{font-size:13px;font-weight:700;letter-spacing:.1em;color:var(--bl)}
.mbadge{padding:2px 10px;border-radius:6px;font-size:10px;font-weight:700;letter-spacing:.06em}
.dry{background:rgba(255,176,32,.15);color:var(--am);border:1px solid rgba(255,176,32,.3)}
.live{background:rgba(0,212,138,.15);color:var(--gr);border:1px solid rgba(0,212,138,.3)}
.hdr{margin-left:auto;display:flex;align-items:center;gap:16px}
.hstat{display:flex;flex-direction:column;align-items:flex-end;gap:1px}
.hstat .lb{font-size:9px;color:var(--mt);text-transform:uppercase;letter-spacing:.06em}
.hstat .vl{font-size:14px;font-weight:700;line-height:1}
.hdiv{width:1px;height:28px;background:var(--bd)}
.htm{font-size:10px;color:var(--mt)}
.tabs{background:var(--s1);border-bottom:1px solid var(--bd);display:flex;padding:0 18px}
.tab{padding:10px 16px;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--mt);cursor:pointer;border-bottom:2px solid transparent;transition:all .15s;user-select:none}
.tab:hover{color:var(--tx)}.tab.active{color:var(--bl);border-bottom-color:var(--bl)}
.panel{display:none;padding:14px 18px;flex-direction:column;gap:12px}
.panel.active{display:flex}
.card{background:var(--s1);border:1px solid var(--bd);border-radius:var(--r);padding:12px 14px}
.ch{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;
  color:var(--mt);margin-bottom:10px;display:flex;align-items:center;gap:8px}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:900px){.g4,.g3{grid-template-columns:repeat(2,1fr)}.g2{grid-template-columns:1fr}}
.sc .lb{font-size:9px;color:var(--mt);text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}
.sc .vl{font-size:22px;font-weight:800;line-height:1.1}
.sc .sb{font-size:9px;color:var(--mt);margin-top:3px}
.gr{color:var(--gr)}.rd{color:var(--rd)}.bl{color:var(--bl)}.am{color:var(--am)}.pu{color:var(--pu)}
.tag{display:inline-block;padding:2px 7px;border-radius:3px;font-size:9px;font-weight:700}
.tag.buy{background:rgba(0,212,138,.12);color:var(--gr)}
.tag.sell{background:rgba(255,61,90,.12);color:var(--rd)}
.tag.tp{background:rgba(0,212,138,.12);color:var(--gr)}
.tag.sl{background:rgba(255,61,90,.12);color:var(--rd)}
.tag.timeout{background:rgba(61,142,255,.12);color:var(--bl)}
table{width:100%;border-collapse:collapse}
th{padding:5px 8px;text-align:left;font-size:9px;color:var(--mt);
  text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--bd)}
td{padding:6px 8px;border-bottom:1px solid #13171f;font-size:11px}
tr:last-child td{border:none}tr:hover td{background:#13171f}
.rb{height:4px;border-radius:2px;background:var(--s2);margin-top:5px;overflow:hidden}
.rf{height:100%;border-radius:2px;transition:width .5s}
.bdg{display:inline-block;padding:2px 8px;border-radius:8px;font-size:9px;font-weight:700}
.bdg.ok{background:rgba(0,212,138,.15);color:var(--gr)}
.bdg.ng{background:rgba(255,61,90,.15);color:var(--rd)}
button{background:transparent;border:1px solid var(--bd);color:var(--tx);padding:6px 14px;
  border-radius:6px;cursor:pointer;font-size:11px;font-family:inherit;transition:all .15s}
button:hover{border-color:var(--bl);color:var(--bl)}
button.danger{border-color:var(--rd);color:var(--rd)}button.danger:hover{background:rgba(255,61,90,.08)}
button.primary{border-color:var(--bl);color:var(--bl)}button.primary:hover{background:rgba(61,142,255,.08)}
button.success{border-color:var(--gr);color:var(--gr)}button.success:hover{background:rgba(0,212,138,.08)}
button:disabled{opacity:.35;cursor:not-allowed}
.cb-box{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:8px;
  background:var(--s2);border:1px solid var(--bd);margin-top:10px}
.cb-box.tripped{background:rgba(255,61,90,.06);border-color:rgba(255,61,90,.4)}
.cb-box.ok{background:rgba(0,212,138,.04);border-color:rgba(0,212,138,.2)}
.cb-icon{font-size:18px}.cb-text{flex:1}
.cb-title{font-size:12px;font-weight:700;margin-bottom:2px}
.cb-sub{font-size:10px;color:var(--mt)}
.fr{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.field{display:flex;flex-direction:column;gap:4px}
.field label{font-size:10px;color:var(--mt);text-transform:uppercase;letter-spacing:.06em}
.field input,.field select,.field textarea{background:var(--s2);border:1px solid var(--bd);
  color:var(--tx);padding:6px 10px;border-radius:6px;font-size:12px;font-family:inherit;
  outline:none;transition:border-color .15s}
.field input:focus,.field select:focus,.field textarea:focus{border-color:var(--bl)}
.field .hint{font-size:9px;color:var(--mt)}
.prog-bar{height:6px;border-radius:3px;background:var(--s2);margin:8px 0;overflow:hidden}
.prog-fill{height:100%;border-radius:3px;background:var(--bl);transition:width .3s}
.rbest{background:rgba(0,212,138,.05)}
.spill{display:inline-flex;align-items:center;gap:6px;background:var(--s2);
  border:1px solid var(--bd);border-radius:6px;padding:4px 10px;font-size:11px;margin:3px}
.logbox{height:130px;overflow-y:auto;padding:8px 10px;font-size:10px;
  line-height:1.8;background:var(--s2);border-radius:6px}
.logbox .e{color:var(--rd)}.logbox .i{color:var(--mt)}
.gain-pos{color:var(--gr);font-weight:700}.gain-neg{color:var(--rd);font-weight:700}
.vbar{display:inline-block;height:6px;border-radius:3px;background:var(--bl);
  vertical-align:middle;margin-left:6px;opacity:.6}
"""

_HTML_HEAD = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Spike Bot</title>
<style>""" + _CSS + """</style>
</head><body>
<header>
  <div class="dot" id="hDot"></div>
  <h1>SPIKE BOT</h1>
  <span class="mbadge dry" id="modeBadge">空跑</span>
  <span id="levBadge" class="mbadge" style="background:rgba(168,85,247,.15);color:var(--pu);border:1px solid rgba(168,85,247,.3)">合约 5x</span>
  <button id="modeBtn" onclick="toggleMode()"
    style="padding:2px 10px;font-size:10px;border-radius:5px;margin-left:4px;border-color:var(--gr);color:var(--gr)">切换实盘</button>
  <span class="htm" id="hTime"></span>
  <div class="hdr">
    <div class="hstat"><span class="lb">监控币种</span><span class="vl am" id="hSymN">0</span></div>
    <div class="hdiv"></div>
    <div class="hstat"><span class="lb">今日收益</span><span class="vl" id="hDay">+0.0000</span></div>
    <div class="hdiv"></div>
    <div class="hstat"><span class="lb">总收益</span><span class="vl" id="hTot">+0.0000</span></div>
  </div>
</header>
<div class="tabs">
  <div class="tab active" id="t0" onclick="showTab(0)">监控</div>
  <div class="tab" id="t1" onclick="showTab(1)">参数设置</div>
  <div class="tab" id="t2" onclick="showTab(2)">网格搜索</div>
  <div class="tab" id="t3" onclick="showTab(3)">币种管理</div>
</div>
"""

_TAB_MONITOR = """
<div class="panel active" id="p0">
  <div class="g4">
    <div class="card sc"><div class="lb">胜率</div><div class="vl bl" id="wr">0%</div><div class="sb" id="wl">0W/0L</div></div>
    <div class="card sc"><div class="lb">总交易</div><div class="vl am" id="totalT">0</div><div class="sb" id="openC">持仓 0</div></div>
    <div class="card sc"><div class="lb">信号/拦截</div><div class="vl bl" id="sigN">0</div><div class="sb" id="sigB">拦截 0</div></div>
    <div class="card sc"><div class="lb">扫描模式</div><div class="vl" id="scanMHd" style="font-size:14px">—</div><div class="sb" id="scanCHd">0 个币种</div></div>
  </div>
  <div class="card">
    <div class="ch">风控状态 <span class="bdg ok" id="rBdg">✓ 正常</span></div>
    <div class="g3">
      <div><div style="font-size:9px;color:var(--mt);margin-bottom:3px">今日亏损</div>
        <div style="font-size:14px;font-weight:700" id="rLoss">0.00 / — USDT</div>
        <div class="rb"><div class="rf" id="rLossBar" style="background:var(--rd);width:0%"></div></div></div>
      <div><div style="font-size:9px;color:var(--mt);margin-bottom:3px">账户回撤</div>
        <div style="font-size:14px;font-weight:700" id="rDD">0.00%</div>
        <div class="rb"><div class="rf" id="rDDBar" style="background:var(--am);width:0%"></div></div></div>
      <div><div style="font-size:9px;color:var(--mt);margin-bottom:3px">连续亏损</div>
        <div style="font-size:14px;font-weight:700" id="rCons">0 次</div>
        <div class="rb"><div class="rf" id="rConsBar" style="background:var(--pu);width:0%"></div></div></div>
    </div>
    <div class="cb-box ok" id="cbBox">
      <div class="cb-icon" id="cbIcon">✅</div>
      <div class="cb-text">
        <div class="cb-title" id="cbTitle">熔断器正常</div>
        <div class="cb-sub" id="cbSub">所有风控条件未触发，可正常交易</div>
      </div>
      <button class="danger" id="cbBtn" onclick="resetCircuit()" disabled style="flex-shrink:0;opacity:.3">解除熔断</button>
    </div>
  </div>
  <div class="g2">
    <div class="card">
      <div class="ch">当前持仓 <span class="am" id="openCnt">0</span></div>
      <table><thead><tr><th>币种</th><th>方向</th><th>入场</th><th>TP</th><th>SL</th><th>R:R</th><th>持时</th></tr></thead>
      <tbody id="openTb"><tr><td colspan="7" style="text-align:center;color:var(--mt);padding:14px">无持仓</td></tr></tbody></table>
    </div>
    <div class="card">
      <div class="ch">最近成交</div>
      <table><thead><tr><th>币种</th><th>方向</th><th>入场</th><th>出场</th><th>原因</th><th>盈亏</th></tr></thead>
      <tbody id="tradeTb"><tr><td colspan="6" style="text-align:center;color:var(--mt);padding:14px">暂无</td></tr></tbody></table>
    </div>
  </div>
  <div class="card"><div class="ch">错误日志</div>
    <div class="logbox" id="logbox"><div class="i">等待运行...</div></div></div>
  <div class="card" style="border-color:rgba(61,142,255,.2)">
    <div class="ch" style="color:var(--bl)">实时诊断
      <span style="font-weight:400;font-size:10px;color:var(--mt);margin-left:4px">— 为什么没有信号？</span>
    </div>
    <div id="diagBox" style="font-size:11px;line-height:2;color:var(--mt)">等待数据...</div>
  </div>
</div>
"""

_TAB_PARAMS = """
<div class="panel" id="p1">
  <div class="card"><div class="ch">插针检测</div>
    <div class="fr">
      <div class="field"><label>SPIKE_VS_ATR 针/ATR倍数</label>
        <input type="number" id="p_SPIKE_VS_ATR" step="0.5" min="0.5">
        <span class="hint">下影线 ÷ ATR(20) ≥ 此值</span></div>
      <div class="field"><label>MIN_SPIKE_PIPS 最小针长</label>
        <input type="number" id="p_MIN_SPIKE_PIPS" step="0.00001">
        <span class="hint">相对价格比例，0.00005=0.005%</span></div>
      <div class="field"><label>MIN_RECOVERY 最小已回归</label>
        <input type="number" id="p_MIN_RECOVERY" step="0.05" min="0" max="0.9">
        <span class="hint">已回归≥此值才触发（确认反转）</span></div>
      <div class="field"><label>MAX_RECOVERY 最大已回归</label>
        <input type="number" id="p_MAX_RECOVERY" step="0.05" min="0.1" max="1.0">
        <span class="hint">建议0.3~0.5，越小R:R越好但信号越少</span></div>
    </div>
  </div>
  <div class="card"><div class="ch">止盈止损</div>
    <div class="fr">
      <div class="field"><label>TP_RATIO 止盈比</label>
        <input type="number" id="p_TP_RATIO" step="0.05" min="0.3" max="1.5">
        <span class="hint">止盈=针尖+针长×此值</span></div>
      <div class="field"><label>SL_RATIO 止损比（针长）</label>
        <input type="number" id="p_SL_RATIO" step="0.05" min="0.01" max="0.5">
        <span class="hint">止损=针尖−针长×此值（基础）</span></div>
      <div class="field"><label>SL_ATR_MULT 止损ATR倍数</label>
        <input type="number" id="p_SL_ATR_MULT" step="0.1" min="0.1" max="3.0">
        <span class="hint">止损=针尖−ATR×此值，两者取大</span></div>
      <div class="field"><label>MIN_RR 最低风险收益比</label>
        <input type="number" id="p_MIN_RR" step="0.1" min="0.5" max="5.0">
        <span class="hint">TP距离÷SL距离 ≥ 此值才入场</span></div>
      <div class="field"><label>MAX_HOLD_SECONDS 超时平仓</label>
        <input type="number" id="p_MAX_HOLD_SECONDS" step="5" min="5">
        <span class="hint">超过此秒数强制平仓</span></div>
      <div class="field"><label>ORDER_USDT 单笔金额</label>
        <input type="number" id="p_ORDER_USDT" step="5" min="5">
        <span class="hint">每笔下单USDT金额</span></div>
    </div>
  </div>
  <div class="card"><div class="ch">合约设置 <span class="am" style="font-weight:400;font-size:10px;margin-left:4px">仅实盘生效，修改杠杆前请平掉所有仓位</span></div>
    <div class="fr">
      <div class="field"><label>LEVERAGE 杠杆倍数</label>
        <input type="number" id="p_LEVERAGE" step="1" min="1" max="125">
        <span class="hint">3~10 推荐，杠杆越大盈亏放大</span></div>
      <div class="field"><label>MARGIN_TYPE 保证金模式</label>
        <select id="p_MARGIN_TYPE">
          <option value="ISOLATED">ISOLATED 逐仓（推荐）</option>
          <option value="CROSSED">CROSSED 全仓</option>
        </select>
        <span class="hint">逐仓：单笔亏完不影响其他仓位</span></div>
    </div>
  </div>
  <div class="card"><div class="ch">风险控制</div>
    <div class="fr">
      <div class="field"><label>DAILY_LOSS_LIMIT_USDT</label>
        <input type="number" id="p_DAILY_LOSS_LIMIT_USDT" step="1" min="1"></div>
      <div class="field"><label>MAX_DRAWDOWN_PCT %</label>
        <input type="number" id="p_MAX_DRAWDOWN_PCT" step="0.5" min="1" max="50"></div>
      <div class="field"><label>MAX_CONSECUTIVE_LOSSES</label>
        <input type="number" id="p_MAX_CONSECUTIVE_LOSSES" step="1" min="2" max="20"></div>
      <div class="field"><label>MAX_OPEN_ORDERS</label>
        <input type="number" id="p_MAX_OPEN_ORDERS" step="1" min="1" max="10"></div>
    </div>
  </div>
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
    <button class="primary" onclick="applyParams()">应用参数（热更新）</button>
    <button onclick="loadParams()">重新读取</button>
    <span id="paramMsg" style="font-size:11px"></span>
  </div>
  <div class="card" style="background:rgba(255,176,32,.03);border-color:rgba(255,176,32,.15)">
    <div class="ch" style="color:var(--am)">当前生效参数</div>
    <pre id="cfgSnap" style="font-size:10px;color:var(--mt);line-height:1.9;white-space:pre-wrap"></pre>
  </div>
</div>
"""

_TAB_GRID = """
<div class="panel" id="p2">
  <div class="card">
    <div class="ch">搜索空间
      <span style="font-weight:400;font-size:10px;color:var(--mt);margin-left:4px">— 对所有监控币种并行回测</span>
    </div>
    <div class="fr">
      <div class="field"><label>SPIKE_VS_ATR 针/ATR倍数</label>
        <input type="text" id="g_atr" value="2.0,2.5,3.0,4.0"><span class="hint">只抓大针，质量优先</span></div>
      <div class="field"><label>MIN_RECOVERY 最小回归%</label>
        <input type="text" id="g_min_rec" value="0.20,0.25,0.30">
        <span class="hint">越低入场越早R:R越好，但噪音多</span></div>
      <div class="field"><label>MAX_RECOVERY 最大回归%</label>
        <input type="text" id="g_max_rec" value="0.35,0.40,0.45">
        <span class="hint">40%时R:R≈1.2，超过45%亏损</span></div>
      <div class="field"><label>TP_RATIO 止盈比</label>
        <input type="text" id="g_tp" value="0.85,1.00,1.15">
        <span class="hint">1.0=到达针根，>1.0更激进</span></div>
      <div class="field"><label>SL_RATIO</label>
        <input type="text" id="g_sl" value="0.08,0.12"></div>
      <div class="field"><label>SL_ATR_MULT</label>
        <input type="text" id="g_sl_atr" value="0.5,1.0"></div>
      <div class="field"><label>MAX_HOLD_SECONDS</label>
        <input type="text" id="g_hold" value="20,30"></div>
    </div>
    <div style="margin-top:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <div class="field" style="flex-direction:row;align-items:center;gap:8px;margin:0">
        <label style="white-space:nowrap;font-size:10px;color:var(--mt)">回测天数</label>
        <input type="number" id="g_days" value="2" min="1" max="7" style="width:60px">
      </div>
      <div class="field" style="flex-direction:row;align-items:center;gap:8px;margin:0">
        <label style="white-space:nowrap;font-size:10px;color:var(--mt)">优化目标</label>
        <select id="g_target">
          <option value="expectancy">期望值 expectancy</option>
          <option value="win_rate">胜率 win_rate</option>
          <option value="total_pnl">总PnL</option>
          <option value="sharpe">Sharpe</option>
        </select>
      </div>
      <button class="primary" id="gridBtn" onclick="startGrid()">开始搜索</button>
      <span id="gCombo" style="font-size:10px;color:var(--mt)"></span>
    </div>
  </div>
  <div class="card" id="gProgCard" style="display:none">
    <div class="ch">进度 <span id="gPct" class="am">0%</span>
      <span id="gStatus" style="font-weight:400;color:var(--mt);font-size:10px;margin-left:8px"></span>
    </div>
    <div class="prog-bar"><div class="prog-fill" id="gBar" style="width:0%"></div></div>
    <div id="gLog" style="margin-top:8px;font-size:10px;color:var(--mt);line-height:1.9"></div>
  </div>
  <div class="card" id="gAggCard" style="display:none">
    <div class="ch">汇总 Top10
      <span style="font-weight:400;font-size:10px;color:var(--mt);margin-left:4px">— 跨所有币种</span>
      <button class="success" style="margin-left:auto;padding:3px 10px;font-size:10px" onclick="applyBest()">应用最优</button>
    </div>
    <div style="overflow-x:auto">
    <table><thead><tr>
      <th>#</th><th>ATR</th><th>MinRec</th><th>MaxRec</th><th>TP</th><th>SL</th><th>SL-ATR</th><th>HOLD</th>
      <th>笔数</th><th>胜率</th><th>R:R</th><th>毛PnL</th><th>净胜率</th><th>净PnL</th><th>覆盖币</th><th></th>
    </tr></thead><tbody id="gAggTb"></tbody></table></div>
  </div>
  <div id="gSymCards"></div>
</div>
"""

_TAB_SYMBOLS = """
<div class="panel" id="p3">
  <div class="card">
    <div class="ch">扫描模式</div>
    <div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px">
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
        <input type="radio" name="sm" value="single" id="sm0"> Single 单币种</label>
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
        <input type="radio" name="sm" value="list" id="sm1"> List 手动列表</label>
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
        <input type="radio" name="sm" value="auto" id="sm2"> Auto 涨幅榜</label>
    </div>
    <div id="opt_single">
      <div class="field" style="max-width:200px">
        <label>交易对</label><input type="text" id="sym_single" placeholder="CTSIUSDT">
      </div>
    </div>
    <div id="opt_list" style="display:none">
      <div class="field">
        <label>交易对列表（每行或逗号分隔）</label>
        <textarea id="sym_list" rows="4" style="resize:vertical">CTSIUSDT
SOLUSDT
SUIUSDT
FETUSDT</textarea>
      </div>
    </div>
    <div id="opt_auto" style="display:none">
      <div style="background:rgba(61,142,255,.06);border:1px solid rgba(61,142,255,.2);
        border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:11px;color:var(--mt);line-height:1.8">
        每 <span class="am" id="rfMin">15</span> 分钟查 Binance 24h 涨幅榜，
        筛选 <span class="bl">涨幅 ≥ +设定值</span>（只要上涨） 且 <span class="bl">成交量 ≥ 设定值</span> 的币。
      </div>
      <div class="fr">
        <div class="field"><label>最小涨幅 %（只筛上涨币）</label>
          <input type="number" id="auto_gain" value="15" min="5" max="200" step="5"></div>
        <div class="field"><label>最低24h成交量 USDT</label>
          <input type="number" id="auto_vol" value="10000000" step="1000000"></div>
        <div class="field"><label>最多监控币数</label>
          <input type="number" id="auto_maxn" value="10" min="1" max="20"></div>
        <div class="field"><label>刷新间隔（分钟）</label>
          <input type="number" id="auto_rf" value="15" min="5" max="60"
            oninput="document.getElementById('rfMin').textContent=this.value"></div>
      </div>
    </div>
    <div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <button class="primary" onclick="applySymbols()">应用</button>
      <button style="border-color:var(--am);color:var(--am)" onclick="forceRescan()">立即重新扫描</button>
      <span id="symMsg" style="font-size:11px"></span>
    </div>
  </div>
  <div class="card">
    <div class="ch">当前活跃币种
      <span style="margin-left:auto;font-size:10px;color:var(--mt)">
        下次刷新: <span class="am" id="nextRf">—</span></span>
    </div>
    <div id="symPills" style="min-height:32px;margin-bottom:8px"></div>
    <div style="font-size:10px;color:var(--mt)">模式: <span class="am" id="modeLabel">—</span></div>
  </div>
  <div class="card" id="gainerCard" style="display:none">
    <div class="ch">涨幅榜明细（最近一次扫描）</div>
    <table><thead><tr><th>#</th><th>币种</th><th>24h涨幅</th><th>振幅</th><th>成交量</th></tr></thead>
    <tbody id="gainerTb"></tbody></table>
  </div>
</div>
"""

_JS = r"""
<script>
function showTab(n){
  for(var i=0;i<4;i++){
    document.getElementById('t'+i).classList.toggle('active',i===n);
    document.getElementById('p'+i).classList.toggle('active',i===n);
  }
}
var _D={};
var es=new EventSource('/stream');
es.onmessage=function(e){ _D=JSON.parse(e.data); renderAll(_D); };
function fmt(v,n){ n=n||4; return (v>=0?'+':'')+v.toFixed(n); }
function fmtP(v){ return v.toFixed(6); }
function clamp(v,lo,hi){ return Math.min(Math.max(v,lo),hi); }

function renderAll(d){
  renderHeader(d); renderMonitor(d);
  renderGrid(d); renderSymTab(d);
  if(d.live_config) syncParams(d.live_config);
}

function renderHeader(d){
  document.getElementById('hDot').className='dot'+(d.running?' on':'');
  document.getElementById('hTime').textContent=d.last_tick?new Date(d.last_tick*1000).toLocaleTimeString('zh'):'';
  var dry=d.dry_run;
  var mb=document.getElementById('modeBadge');
  mb.textContent=dry?'空跑 DRY-RUN':'实盘 LIVE';
  mb.className='mbadge '+(dry?'dry':'live');
  var btn=document.getElementById('modeBtn');
  if(btn){ btn.textContent=dry?'切换实盘':'切换空跑';
    btn.style.borderColor=dry?'var(--gr)':'var(--am)';
    btn.style.color=dry?'var(--gr)':'var(--am)'; }
  var lb=document.getElementById('levBadge');
  if(lb&&d.live_config){
    var lev=d.live_config.LEVERAGE||5;
    var mt=(d.live_config.MARGIN_TYPE||'ISOLATED').toUpperCase();
    lb.textContent='合约 '+lev+'x '+(mt==='CROSSED'?'全仓':'逐仓');
  }
  document.getElementById('hSymN').textContent=(d.symbols_active||[]).length;
  var dp=d.risk?d.risk.daily_pnl||0:0;
  var tp=d.stats?d.stats.total_pnl||0:0;
  var dpEl=document.getElementById('hDay'); dpEl.textContent=fmt(dp); dpEl.className='vl '+(dp>=0?'gr':'rd');
  var tpEl=document.getElementById('hTot'); tpEl.textContent=fmt(tp); tpEl.className='vl '+(tp>=0?'gr':'rd');
}

function renderMonitor(d){
  var DL=d.live_config&&d.live_config.DAILY_LOSS_LIMIT_USDT||10;
  var MD=d.live_config&&d.live_config.MAX_DRAWDOWN_PCT||5;
  var MC=d.live_config&&d.live_config.MAX_CONSECUTIVE_LOSSES||5;
  document.getElementById('wr').textContent=(d.stats&&d.stats.win_rate||0)+'%';
  document.getElementById('wl').textContent=(d.stats&&d.stats.win||0)+'W/'+(d.stats&&d.stats.loss||0)+'L';
  document.getElementById('totalT').textContent=d.stats&&d.stats.total_trades||0;
  document.getElementById('openC').textContent='持仓 '+(d.stats&&d.stats.open_count||0);
  document.getElementById('sigN').textContent=d.signals_found||0;
  document.getElementById('sigB').textContent='拦截 '+(d.signals_blocked||0);
  document.getElementById('scanMHd').textContent=(d.scan_mode||'—').toUpperCase();
  document.getElementById('scanCHd').textContent=(d.symbols_active||[]).length+' 个币种';
  if(d.risk){
    var rk=d.risk;
    var bdg=document.getElementById('rBdg');
    bdg.textContent=rk.can_trade?'✓ 正常':'✗ 熔断'; bdg.className='bdg '+(rk.can_trade?'ok':'ng');
    var la=Math.abs(Math.min(rk.daily_pnl||0,0));
    document.getElementById('rLoss').textContent=la.toFixed(2)+' / '+DL+' USDT';
    document.getElementById('rLossBar').style.width=clamp(la/DL*100,0,100)+'%';
    document.getElementById('rDD').textContent=(rk.drawdown_pct||0).toFixed(2)+'%';
    document.getElementById('rDDBar').style.width=clamp((rk.drawdown_pct||0)/MD*100,0,100)+'%';
    document.getElementById('rCons').textContent=(rk.consecutive_losses||0)+' 次';
    document.getElementById('rConsBar').style.width=clamp((rk.consecutive_losses||0)/MC*100,0,100)+'%';
    var tripped=rk.circuit_broken;
    var cb=document.getElementById('cbBox'); cb.className='cb-box '+(tripped?'tripped':'ok');
    document.getElementById('cbIcon').textContent=tripped?'🔴':'✅';
    document.getElementById('cbTitle').textContent=tripped?'熔断已触发！':'熔断器正常';
    document.getElementById('cbSub').textContent=tripped?'原因: '+rk.circuit_reason:'所有风控条件未触发';
    var btn=document.getElementById('cbBtn'); btn.disabled=!tripped; btn.style.opacity=tripped?'1':'0.3';
  }
  document.getElementById('openCnt').textContent=d.stats&&d.stats.open_count||0;
  var ob=document.getElementById('openTb');
  ob.innerHTML=!d.open_positions||!d.open_positions.length
    ?'<tr><td colspan="7" style="text-align:center;color:var(--mt);padding:14px">无持仓</td></tr>'
    :d.open_positions.map(function(p){
      return '<tr><td class="am">'+p.symbol+'</td><td><span class="tag '+p.direction.toLowerCase()+'">'+p.direction+'</span></td>'
        +'<td>'+fmtP(p.entry_price)+'</td><td class="gr">'+fmtP(p.take_profit)+'</td>'
        +'<td class="rd">'+fmtP(p.stop_loss)+'</td><td class="bl">'+(p.rr_ratio||'—')+'</td>'
        +'<td>'+p.age_seconds.toFixed(0)+'s</td></tr>';
    }).join('');
  var tb=document.getElementById('tradeTb');
  tb.innerHTML=!d.recent_trades||!d.recent_trades.length
    ?'<tr><td colspan="6" style="text-align:center;color:var(--mt);padding:14px">暂无</td></tr>'
    :[...d.recent_trades].reverse().map(function(t){
      var pc=t.pnl_usdt>=0?'var(--gr)':'var(--rd)';
      return '<tr><td class="am">'+t.symbol+'</td><td><span class="tag '+t.direction.toLowerCase()+'">'+t.direction+'</span></td>'
        +'<td>'+fmtP(t.entry_price)+'</td><td>'+fmtP(t.close_price)+'</td>'
        +'<td><span class="tag '+t.close_reason.toLowerCase()+'">'+t.close_reason+'</span></td>'
        +'<td style="color:'+pc+';font-weight:700">'+fmt(t.pnl_usdt)+'</td></tr>';
    }).join('');
  if(d.errors&&d.errors.length)
    document.getElementById('logbox').innerHTML=d.errors.map(function(e){return '<div class="e">✗ '+e+'</div>';}).join('');
  if(d.diag){
    var dg=d.diag; var a=dg.atr||0;
    var lw=dg.lower_wick||0; var uw=dg.upper_wick||0;
    var rb=dg.ratio_body||0; var ra=dg.ratio_atr||0; var rv=dg.recovery||0;
    var sr=dg.cfg_spike_ratio||2.5; var sa=dg.cfg_spike_atr||1.5;
    var mr=dg.cfg_min_rec||0.2; var xr=dg.cfg_max_rec||0.7;
    var pb=rb>=sr; var pa=ra>=sa; var pr=(rv>=mr&&rv<=xr);
    function ck(v){return v?'<span class="gr">✓</span>':'<span class="rd">✗</span>';}
    var lines=[
      '📡 <span style="color:var(--tx)">'+dg.symbol+'</span>  open='+((dg.last_open||0).toFixed(6))+'  high='+((dg.last_high||0).toFixed(6))+'  low='+((dg.last_low||0).toFixed(6))+'  close='+((dg.last_close||0).toFixed(6)),
      '📏 下影线='+lw.toFixed(6)+'  上影线='+uw.toFixed(6)+'  ATR='+a.toFixed(6),
      '🔍 针/实体='+rb.toFixed(2)+'(需≥'+sr+') '+ck(pb)+'  针/ATR='+ra.toFixed(2)+'(需≥'+sa+') '+ck(pa)+'  回归='+rv.toFixed(2)+'(需'+mr+'~'+xr+') '+ck(pr),
      d.signals_found>0?'✅ <span class="gr">已发现'+d.signals_found+'个信号</span>'+(d.dry_run?' (空跑模拟)':'')
        :'⏳ <span class="am">暂无信号</span>'
    ];
    document.getElementById('diagBox').innerHTML=lines.join('<br>');
  }
}

// ── 参数 ──────────────────────────────────────────────────
var _pEditing=false,_pTimer=null;
function _lockP(){_pEditing=true;clearTimeout(_pTimer);_pTimer=setTimeout(function(){_pEditing=false;},10000);}
(function(){
  var ids=['p_LEVERAGE','p_SPIKE_VS_ATR','p_MIN_SPIKE_PIPS','p_MIN_RECOVERY','p_MAX_RECOVERY',
    'p_TP_RATIO','p_SL_RATIO','p_SL_ATR_MULT','p_MIN_RR','p_MAX_HOLD_SECONDS','p_ORDER_USDT',
    'p_DAILY_LOSS_LIMIT_USDT','p_MAX_DRAWDOWN_PCT','p_MAX_CONSECUTIVE_LOSSES','p_MAX_OPEN_ORDERS'];
  ids.forEach(function(id){var el=document.getElementById(id);if(el)el.addEventListener('focus',_lockP);});
})();
function syncParams(cfg){
  if(_pEditing)return;
  var keys=['LEVERAGE','SPIKE_VS_ATR','MIN_SPIKE_PIPS','MIN_RECOVERY','MAX_RECOVERY',
    'TP_RATIO','SL_RATIO','SL_ATR_MULT','MIN_RR','MAX_HOLD_SECONDS','ORDER_USDT',
    'DAILY_LOSS_LIMIT_USDT','MAX_DRAWDOWN_PCT','MAX_CONSECUTIVE_LOSSES','MAX_OPEN_ORDERS'];
  keys.forEach(function(k){var el=document.getElementById('p_'+k);if(el&&document.activeElement!==el)el.value=cfg[k]!=null?cfg[k]:'';});
  // MARGIN_TYPE select
  var mt=document.getElementById('p_MARGIN_TYPE');
  if(mt&&document.activeElement!==mt&&cfg.MARGIN_TYPE) mt.value=cfg.MARGIN_TYPE;
  document.getElementById('cfgSnap').textContent=JSON.stringify(cfg,null,2);
}
function loadParams(){if(_D.live_config)syncParams(_D.live_config);}
function applyParams(){
  var keys=['LEVERAGE','SPIKE_VS_ATR','MIN_SPIKE_PIPS','MIN_RECOVERY','MAX_RECOVERY',
    'TP_RATIO','SL_RATIO','SL_ATR_MULT','MIN_RR','MAX_HOLD_SECONDS','ORDER_USDT',
    'DAILY_LOSS_LIMIT_USDT','MAX_DRAWDOWN_PCT','MAX_CONSECUTIVE_LOSSES','MAX_OPEN_ORDERS'];
  var u={};
  keys.forEach(function(k){var el=document.getElementById('p_'+k);if(el&&el.value!=='')u[k]=parseFloat(el.value);});
  // MARGIN_TYPE is string
  var mt=document.getElementById('p_MARGIN_TYPE');
  if(mt&&mt.value) u.MARGIN_TYPE=mt.value;
  post('/api/set_params',u).then(function(d){
    var msg=document.getElementById('paramMsg');
    msg.textContent=d.ok?'✓ 已应用: '+d.changed.join(', '):'✗ '+(d.error||'');
    msg.style.color=d.ok?'var(--gr)':'var(--rd)';
    setTimeout(function(){msg.textContent='';},4000);
  });
}

// ── 网格搜索 ─────────────────────────────────────────────
function calcCombos(){
  var n=1;
  ['g_atr','g_min_rec','g_max_rec','g_tp','g_sl','g_sl_atr','g_hold'].forEach(function(id){
    n*=document.getElementById(id).value.split(',').filter(function(x){return x.trim();}).length||1;
  });
  document.getElementById('gCombo').textContent='共 '+n+' 种组合';
}
(function(){
  ['g_atr','g_min_rec','g_max_rec','g_tp','g_sl','g_sl_atr','g_hold'].forEach(function(id){
    var el=document.getElementById(id);if(el)el.addEventListener('input',calcCombos);
  });
  calcCombos();
})();
function startGrid(){
  var p={
    spike_atr:  document.getElementById('g_atr').value.split(',').map(Number).filter(Boolean),
    min_rec:    document.getElementById('g_min_rec').value.split(',').map(Number).filter(Boolean),
    max_rec:    document.getElementById('g_max_rec').value.split(',').map(Number).filter(Boolean),
    tp:         document.getElementById('g_tp').value.split(',').map(Number).filter(Boolean),
    sl:         document.getElementById('g_sl').value.split(',').map(Number).filter(Boolean),
    sl_atr:     document.getElementById('g_sl_atr').value.split(',').map(Number).filter(Boolean),
    hold:       document.getElementById('g_hold').value.split(',').map(Number).filter(Boolean),
    days:       parseInt(document.getElementById('g_days').value)||2,
    target:     document.getElementById('g_target').value,
  };
  document.getElementById('gProgCard').style.display='block';
  document.getElementById('gridBtn').disabled=true;
  post('/api/grid_search',p).then(function(d){if(!d.ok)alert('失败: '+(d.error||''));});
}
function renderGrid(d){
  var active=d.grid_running||d.grid_progress>0;
  if(!active&&!d.grid_results&&!d.grid_sym_results)return;
  if(active||d.grid_progress>0){
    document.getElementById('gProgCard').style.display='block';
    var pct=d.grid_total>0?Math.round(d.grid_progress/d.grid_total*100):0;
    document.getElementById('gPct').textContent=pct+'%';
    document.getElementById('gBar').style.width=pct+'%';
    document.getElementById('gStatus').textContent=d.grid_running?(d.grid_progress+'/'+d.grid_total):'✓ 完成';
    if(!d.grid_running)document.getElementById('gridBtn').disabled=false;
  }
  if(d.grid_log&&d.grid_log.length)
    document.getElementById('gLog').innerHTML=d.grid_log.map(function(l){return '<div>→ '+l+'</div>';}).join('');
  if(d.grid_results&&d.grid_results.length){
    document.getElementById('gAggCard').style.display='block';
    document.getElementById('gAggTb').innerHTML=d.grid_results.slice(0,10).map(function(r,i){
      var b=i===0;
      return '<tr class="'+(b?'rbest':'')+'"><td class="'+(b?'gr':'')+'">'+(i+1)+'</td>'
        +'<td>'+r.p.SPIKE_VS_ATR+'</td>'
        +'<td>'+r.p.MIN_RECOVERY+'</td><td>'+r.p.MAX_RECOVERY+'</td>'
        +'<td>'+r.p.TP_RATIO+'</td><td>'+r.p.SL_RATIO+'</td><td>'+r.p.SL_ATR_MULT+'</td>'
        +'<td>'+r.p.MAX_HOLD_SECONDS+'</td>'
        +'<td>'+r.m.n+'</td>'
        +'<td class="'+(r.m.win_rate>=55?'gr':'rd')+'">'+r.m.win_rate+'%</td>'
        +'<td class="bl">'+(r.m.avg_rr||'—')+'</td>'
        +'<td class="'+(r.m.total_pnl>0?'gr':'rd')+'">'+r.m.total_pnl.toFixed(4)+'</td>'
        +'<td class="'+((r.m.net_win_rate||0)>=50?'gr':'rd')+'">'+(r.m.net_win_rate!=null?r.m.net_win_rate+'%':'—')+'</td>'
        +'<td class="'+((r.m.net_total_pnl||0)>0?'gr':'rd')+'" style="font-weight:700">'+(r.m.net_total_pnl!=null?r.m.net_total_pnl.toFixed(4):'—')+'</td>'
        +'<td class="am">'+(r.m.symbols_covered||'—')+'</td>'
        +'<td><button style="padding:2px 8px;font-size:9px" onclick="applyRow('+i+')">应用</button></td></tr>';
    }).join('');
  }
  if(d.grid_sym_results&&Object.keys(d.grid_sym_results).length){
    var html='';
    Object.keys(d.grid_sym_results).forEach(function(sym){
      var results=d.grid_sym_results[sym];
      if(!results||!results.length)return;
      var rows=results.slice(0,5).map(function(r,i){
        return '<tr class="'+(i===0?'rbest':'')+'"><td class="'+(i===0?'gr':'')+'">'+(i+1)+'</td>'
          +'<td>'+r.p.SPIKE_VS_ATR+'</td>'
          +'<td>'+r.p.MIN_RECOVERY+'</td><td>'+r.p.MAX_RECOVERY+'</td>'
          +'<td>'+r.p.TP_RATIO+'</td><td>'+r.p.SL_RATIO+'</td><td>'+r.p.SL_ATR_MULT+'</td>'
          +'<td>'+r.p.MAX_HOLD_SECONDS+'</td>'
          +'<td>'+r.m.n+'</td>'
          +'<td class="'+(r.m.win_rate>=55?'gr':'rd')+'">'+r.m.win_rate+'%</td>'
          +'<td class="'+(r.m.total_pnl>0?'gr':'rd')+'">'+r.m.total_pnl.toFixed(4)+'</td>'
          +'<td class="'+((r.m.net_total_pnl||0)>0?'gr':'rd')+'" style="font-weight:700">'+(r.m.net_total_pnl!=null?r.m.net_total_pnl.toFixed(4):'—')+'</td>'
          +'<td><button style="padding:2px 8px;font-size:9px" data-sym="'+sym+'" data-idx="'+i+'" onclick="applySymRowBtn(this)">应用</button></td></tr>';
      }).join('');
      html+='<div class="card" style="margin-top:0"><div class="ch"><span class="am">'+sym+'</span>'
        +'<span style="font-weight:400;color:var(--mt);font-size:10px;margin-left:6px">Top 5</span></div>'
        +'<div style="overflow-x:auto"><table><thead><tr>'
        +'<th>#</th><th>ATR</th><th>MinRec</th><th>MaxRec</th><th>TP</th><th>SL</th><th>SL-ATR</th><th>HOLD</th>'
        +'<th>N</th><th>胜率</th><th>毛PnL</th><th>净PnL</th><th></th>'
        +'</tr></thead><tbody>'+rows+'</tbody></table></div></div>';
    });
    document.getElementById('gSymCards').innerHTML=html;
  }
}
function applyBest(){if(_D.grid_best)applyGridP(_D.grid_best);}
function applyRow(i){if(_D.grid_results&&_D.grid_results[i])applyGridP(_D.grid_results[i].p);}
function applySymRowBtn(btn){
  var sym=btn.getAttribute('data-sym'); var i=parseInt(btn.getAttribute('data-idx'));
  if(_D.grid_sym_results&&_D.grid_sym_results[sym]&&_D.grid_sym_results[sym][i])
    applyGridP(_D.grid_sym_results[sym][i].p);
}
function applyGridP(p){
  if(!confirm('应用这组参数？'))return;
  post('/api/set_params',p).then(function(d){alert(d.ok?'✓ 已应用: '+d.changed.join(', '):'✗ '+(d.error||''));});
}

// ── 币种管理 ─────────────────────────────────────────────
var _sEditing=false,_sTimer=null;
function _lockS(){_sEditing=true;clearTimeout(_sTimer);_sTimer=setTimeout(function(){_sEditing=false;},8000);}
(function(){
  document.querySelectorAll('input[name="sm"]').forEach(function(r){
    r.addEventListener('mousedown',_lockS);
    r.addEventListener('change',function(){
      _lockS();
      ['single','list','auto'].forEach(function(m){
        document.getElementById('opt_'+m).style.display=r.value===m?'block':'none';
      });
    });
  });
  ['sym_single','sym_list','auto_gain','auto_vol','auto_maxn','auto_rf'].forEach(function(id){
    var el=document.getElementById(id);if(el)el.addEventListener('focus',_lockS);
  });
})();
function renderSymTab(d){
  var mode=d.scan_mode||'single';
  document.getElementById('modeLabel').textContent=mode;
  if(!_sEditing){
    var rb=document.querySelector('input[name="sm"][value="'+mode+'"]');
    if(rb&&!rb.checked){rb.checked=true;
      ['single','list','auto'].forEach(function(m){document.getElementById('opt_'+m).style.display=m===mode?'block':'none';});}
  }
  if(!_sEditing&&d.live_config&&d.live_config.SYMBOL){
    var el=document.getElementById('sym_single');if(el&&document.activeElement!==el)el.value=d.live_config.SYMBOL;
  }
  var syms=d.symbols_active||[],prices=d.prices||{};
  document.getElementById('symPills').innerHTML=syms.length===0
    ?'<span style="color:var(--mt);font-size:11px">无活跃币种</span>'
    :syms.map(function(s){var px=prices[s]||0;
      return '<span class="spill"><span style="width:6px;height:6px;border-radius:50%;background:var(--gr)"></span>'
        +'<span class="am">'+s+'</span>'+(px?'<span style="color:var(--mt)">'+px.toFixed(px<0.01?6:4)+'</span>':'')+'</span>';
    }).join('');
  if(d.next_refresh_in!==undefined){
    var sec=Math.round(d.next_refresh_in);
    document.getElementById('nextRf').textContent=(mode==='auto'?(Math.floor(sec/60)+':'+(sec%60<10?'0':'')+(sec%60)):'—');
  }
  var gc=document.getElementById('gainerCard');
  if(mode==='auto'&&d.gainer_detail&&d.gainer_detail.length){
    gc.style.display='block';
    var maxV=Math.max.apply(null,d.gainer_detail.map(function(g){return g.vol_usdt;}));
    document.getElementById('gainerTb').innerHTML=d.gainer_detail.map(function(g,i){
      var bw=Math.round(g.vol_usdt/maxV*80);
      var gcls=g.gain_pct>=0?'gain-pos':'gain-neg';
      return '<tr><td style="color:var(--mt)">'+(i+1)+'</td><td class="am">'+g.symbol+'</td>'
        +'<td class="'+gcls+'">'+(g.gain_pct>=0?'+':'')+g.gain_pct.toFixed(2)+'%</td>'
        +'<td style="color:var(--mt)">'+g.amp_pct.toFixed(2)+'%</td>'
        +'<td>'+(g.vol_usdt/1e6).toFixed(1)+'M<span class="vbar" style="width:'+bw+'px"></span></td></tr>';
    }).join('');
  } else {gc.style.display='none';}
  if(!_sEditing&&d.live_config){
    var cfg=d.live_config;
    var map={'auto_gain':'AUTO_MIN_GAIN_PCT','auto_vol':'AUTO_MIN_VOLUME_USDT','auto_maxn':'AUTO_MAX_SYMBOLS'};
    Object.keys(map).forEach(function(id){var el=document.getElementById(id);if(el&&document.activeElement!==el&&cfg[map[id]]!=null)el.value=cfg[map[id]];});
    var rm=document.getElementById('auto_rf');
    if(rm&&document.activeElement!==rm&&cfg.AUTO_REFRESH_SEC!=null){rm.value=Math.round(cfg.AUTO_REFRESH_SEC/60);document.getElementById('rfMin').textContent=rm.value;}
  }
}
function applySymbols(){
  var mode=document.querySelector('input[name="sm"]:checked');mode=mode?mode.value:'single';
  var u={SCAN_MODE:mode};
  if(mode==='single')u.SYMBOL=document.getElementById('sym_single').value.trim().toUpperCase();
  else if(mode==='list')u.SYMBOL_LIST=document.getElementById('sym_list').value.split(/[\n,]+/).map(function(s){return s.trim().toUpperCase();}).filter(Boolean);
  else{u.AUTO_MIN_GAIN_PCT=parseFloat(document.getElementById('auto_gain').value)||15;
    u.AUTO_MIN_VOLUME_USDT=parseFloat(document.getElementById('auto_vol').value)||10000000;
    u.AUTO_MAX_SYMBOLS=parseInt(document.getElementById('auto_maxn').value)||10;
    u.AUTO_REFRESH_SEC=parseInt(document.getElementById('auto_rf').value||15)*60;}
  post('/api/set_params',u).then(function(d){
    var msg=document.getElementById('symMsg');msg.textContent=d.ok?'✓ 已应用':'✗ '+(d.error||'');
    msg.style.color=d.ok?'var(--gr)':'var(--rd)';setTimeout(function(){msg.textContent='';},3000);
  });
}
function forceRescan(){post('/api/force_rescan',{}).then(function(){
  var msg=document.getElementById('symMsg');msg.textContent='✓ 重新扫描中...';msg.style.color='var(--am)';
  setTimeout(function(){msg.textContent='';},4000);});}
function toggleMode(){post('/api/set_mode',{dry_run:!_D.dry_run}).then(function(d){if(!d.ok)alert('切换失败');});}
function resetCircuit(){post('/api/reset_circuit',{}).then(function(d){console.log(d);});}
function post(url,body){
  return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json();}).catch(function(e){return {ok:false,error:String(e)};});
}
</script>
"""

def build_html():
    return (_HTML_HEAD + _TAB_MONITOR + _TAB_PARAMS + _TAB_GRID
            + _TAB_SYMBOLS + _JS + "</body></html>")

HTML = build_html()


async def handle_index(req): return web.Response(text=HTML, content_type="text/html")

async def handle_stream(req):
    resp = web.StreamResponse()
    resp.headers.update({"Content-Type":"text/event-stream","Cache-Control":"no-cache","Connection":"keep-alive"})
    await resp.prepare(req)
    try:
        while True:
            pm=STATE.get("positions"); rm=STATE.get("risk")
            scanner=None
            try:
                from bot import _bot_instance
                if _bot_instance: scanner=getattr(_bot_instance,'scanner',None)
            except Exception: pass
            stats={"total_trades":0,"win":0,"loss":0,"win_rate":0,"total_pnl":0,"open_count":0}
            open_pos,recent_trades=[],[]
            if pm:
                stats=pm.stats
                for p in pm.open_positions:
                    open_pos.append({"id":p.id,"symbol":p.symbol,"direction":p.direction,
                        "entry_price":p.entry_price,"take_profit":p.take_profit,"stop_loss":p.stop_loss,
                        "age_seconds":round(p.age_seconds,1),"signal_score":p.signal_score,
                        "rr_ratio":getattr(p,'rr_ratio',0)})
                for t in pm.get_recent_trades(15):
                    recent_trades.append({"id":t.id,"symbol":t.symbol,"direction":t.direction,
                        "entry_price":t.entry_price,"close_price":t.close_price,
                        "close_reason":t.close_reason,"pnl_usdt":t.pnl_usdt})
            nri,gd=0,[]
            if scanner:
                interval=getattr(cfg_module,"AUTO_REFRESH_SEC",900)
                nri=max(0,interval-(time.time()-scanner._last_refresh))
                gd=scanner.last_scan_detail
            payload={
                "running":STATE.get("running",False),"dry_run":STATE.get("dry_run",False),
                "scan_mode":STATE.get("scan_mode","single"),
                "symbols_active":STATE.get("symbols_active",[]),
                "prices":STATE.get("prices",{}),
                "last_tick":STATE.get("last_tick",0),
                "signals_found":STATE.get("signals_found",0),
                "signals_blocked":STATE.get("signals_blocked",0),
                "stats":stats,"open_positions":open_pos,"recent_trades":recent_trades,
                "risk":rm.status_dict if rm else None,
                "live_config":STATE.get("live_config",{}),
                "errors":STATE.get("errors",[])[-12:],
                "diag":STATE.get("diag",{}),
                "grid_running":STATE.get("grid_running",False),
                "grid_progress":STATE.get("grid_progress",0),
                "grid_total":STATE.get("grid_total",0),
                "grid_results":STATE.get("grid_results",[])[:10],
                "grid_best":STATE.get("grid_best"),
                "grid_sym_results":STATE.get("grid_sym_results",{}),
                "grid_log":STATE.get("grid_log",[])[-8:],
                "next_refresh_in":round(nri),"gainer_detail":gd,
            }
            await resp.write(("data: "+json.dumps(payload)+"\n\n").encode())
            await asyncio.sleep(1)
    except (ConnectionResetError,asyncio.CancelledError): pass
    return resp

async def handle_set_params(req):
    try:
        updates=await req.json()
        try:
            from bot import _bot_instance
            if _bot_instance:
                changed=_bot_instance.apply_live_config(updates)
                return web.json_response({"ok":True,"changed":changed})
        except Exception: pass
        for k,v in updates.items():
            if hasattr(cfg_module,k): setattr(cfg_module,k,v)
        return web.json_response({"ok":True,"changed":list(updates.keys())})
    except Exception as e: return web.json_response({"ok":False,"error":str(e)})

async def handle_reset_circuit(req):
    rm=STATE.get("risk")
    if rm: rm.manual_reset(); return web.json_response({"ok":True})
    return web.json_response({"ok":False,"error":"not init"})

async def handle_force_rescan(req):
    try:
        from bot import _bot_instance
        if _bot_instance and hasattr(_bot_instance,'scanner'):
            syms=await _bot_instance.scanner.force_refresh()
            # 立即更新 STATE，dashboard 下次推流就会刷新
            STATE["symbols_active"] = syms
            return web.json_response({"ok":True,"symbols":syms})
    except Exception as e: return web.json_response({"ok":False,"error":str(e)})
    return web.json_response({"ok":False,"error":"scanner not ready"})

async def handle_set_mode(req):
    try:
        body=await req.json(); dry=bool(body.get("dry_run",False))
        cfg_module.DRY_RUN=dry; STATE["dry_run"]=dry
        from core.exchange import BinanceREST
        if dry:
            _oid=[9000]
            async def _fm(self_ex,symbol,side,quantity,reduce_only=False):
                _oid[0]+=1
                try:
                    from bot import STATE as S
                    price=S.get("prices",{}).get(symbol,0)
                    if not price:
                        t=await self_ex._request("GET","/fapi/v1/ticker/bookTicker",{"symbol":symbol})
                        price=float(t.get("askPrice",0) or t.get("bidPrice",0))
                    fill=price*(1.0002 if side=="BUY" else 0.9998)
                except Exception: fill=0.0
                return {"orderId":_oid[0],"executedQty":str(quantity),"avgPrice":str(fill),"status":"FILLED"}
            async def _fb(self_ex,asset="USDT"): return 1000.0
            async def _fl(self_ex, symbol, leverage=None): return {"leverage":leverage or 5, "symbol":symbol}
            async def _fmt(self_ex, symbol, margin_type="ISOLATED"): return {}
            async def _fens(self_ex, symbol): pass
            BinanceREST.place_market_order=_fm
            BinanceREST.get_asset_balance=_fb
            BinanceREST.set_leverage=_fl
            BinanceREST.set_margin_type=_fmt
            BinanceREST.ensure_symbol_setup=_fens
        else:
            import importlib,core.exchange as em; importlib.reload(em)
            BinanceREST.place_market_order=em.BinanceREST.place_market_order
            BinanceREST.place_limit_order =em.BinanceREST.place_limit_order
            BinanceREST.get_asset_balance =em.BinanceREST.get_asset_balance
            BinanceREST.set_leverage      =em.BinanceREST.set_leverage
            BinanceREST.set_margin_type   =em.BinanceREST.set_margin_type
            BinanceREST.ensure_symbol_setup=em.BinanceREST.ensure_symbol_setup
        logger.info(f"模式切换: {'DRY-RUN' if dry else 'LIVE'}")
        return web.json_response({"ok":True,"dry_run":dry})
    except Exception as e: return web.json_response({"ok":False,"error":str(e)})

async def handle_grid_search(req):
    if STATE.get("grid_running"): return web.json_response({"ok":False,"error":"已有搜索在运行"})
    try:
        body=await req.json(); asyncio.create_task(_run_grid_search(body))
        return web.json_response({"ok":True})
    except Exception as e: return web.json_response({"ok":False,"error":str(e)})

async def _run_grid_search(params:dict):
    from core.exchange import BinanceREST
    STATE.update({"grid_running":True,"grid_progress":0,"grid_total":0,
                  "grid_results":[],"grid_best":None,"grid_sym_results":{},"grid_log":[]})
    def log(msg):
        STATE["grid_log"].append(msg); STATE["grid_log"]=STATE["grid_log"][-30:]
        logger.info("[Grid] "+msg)
    try:
        symbols=list(STATE.get("symbols_active",[])) or [cfg_module.SYMBOL]
        days=params.get("days",2); target=params.get("target","expectancy")
        log("回测币种: "+str(symbols))
        grid={
            "SPIKE_VS_ATR":   params.get("spike_atr",  [cfg_module.SPIKE_VS_ATR]),
            "MIN_RECOVERY":   params.get("min_rec",     [getattr(cfg_module,"MIN_RECOVERY",0.20)]),
            "MAX_RECOVERY":   params.get("max_rec",     [getattr(cfg_module,"MAX_RECOVERY",0.70)]),
            "TP_RATIO":       params.get("tp",          [cfg_module.TP_RATIO]),
            "SL_RATIO":       params.get("sl",          [cfg_module.SL_RATIO]),
            "SL_ATR_MULT":    params.get("sl_atr",      [getattr(cfg_module,"SL_ATR_MULT",0.5)]),
            "MAX_HOLD_SECONDS":params.get("hold",       [cfg_module.MAX_HOLD_SECONDS]),
        }
        keys=list(grid.keys())
        combos=list(itertools.product(*[grid[k] for k in keys]))
        STATE["grid_total"]=len(symbols)*len(combos)
        log(str(len(combos))+" 种参数 × "+str(len(symbols))+" 个币 = "+str(STATE["grid_total"])+" 次评估")
        ex=BinanceREST(cfg_module.API_KEY,cfg_module.API_SECRET,cfg_module.BASE_URL)
        combo_trades={i:[] for i in range(len(combos))}
        combo_net_trades={i:[] for i in range(len(combos))}
        sym_results_all={}
        ATR_P=20; MP=getattr(cfg_module,"MIN_SPIKE_PIPS",0.00005)
        for si,symbol in enumerate(symbols):
            log("["+str(si+1)+"/"+str(len(symbols))+"] 拉取 "+symbol+" "+str(days)+"天K线...")
            klines,end_time=[],None
            while len(klines)<days*86400:
                try:
                    chunk=await ex.get_klines(symbol,"1s",1000)
                    if not chunk: break
                    klines=chunk+klines; end_time=chunk[0]["open_time"]-1
                    await asyncio.sleep(0.10)
                except Exception as e: log("  拉取失败: "+str(e)); break
            N=len(klines)
            if N<100: log("  数据不足，跳过"); STATE["grid_progress"]+=len(combos); continue
            log("  "+str(N)+" 根K线，预计算...")
            opens=[k["open"] for k in klines]; highs=[k["high"] for k in klines]
            lows=[k["low"] for k in klines];   closes=[k["close"] for k in klines]
            vols=[k["volume"] for k in klines]
            ranges=[highs[i]-lows[i] for i in range(N)]
            atr=[0.0]*N
            for i in range(ATR_P,N): atr[i]=sum(ranges[i-ATR_P:i])/ATR_P
            lw=[min(opens[i],closes[i])-lows[i]  for i in range(N)]
            uw=[highs[i]-max(opens[i],closes[i]) for i in range(N)]
            bodies=[max(abs(closes[i]-opens[i]),ranges[i]*0.01) for i in range(N)]
            log("  开始 "+str(len(combos))+" 种参数评估...")
            await asyncio.sleep(0)
            sym_combo=[]
            for idx,combo in enumerate(combos):
                SATR,MIN_REC,MAX_REC,TP_R,SL_R,SL_ATR_M,HOLD=combo
                trades=[]; net_trades=[]; MIN_RR=getattr(cfg_module,"MIN_RR",1.5)
                for i in range(ATR_P+1,N):
                    a=atr[i];
                    if a==0: continue
                    mn=closes[i]*MP if MP<0.01 else MP
                    spike_drop=opens[i]-lows[i]
                    if spike_drop > a*SATR:
                        rec=(closes[i]-lows[i])/spike_drop
                        if MIN_REC<=rec<=MAX_REC:
                            tip=lows[i]; entry=closes[i]; root=opens[i]
                            tp=(entry+(root-entry)*TP_R if root>entry else entry+a*TP_R*0.3)
                            sl=min(tip-spike_drop*SL_R, tip-a*SL_ATR_M)
                            if tp>entry and sl<tip:
                                td=tp-entry; sd=entry-sl
                                if sd>0 and td/sd>=MIN_RR:
                                    future=klines[i+1:i+1+int(HOLD)]
                                    pnl=_sim_fast("BUY",entry,tp,sl,future)
                                    fee_rate=getattr(cfg_module,"FEE_RATE",0.001)
                                    net=pnl - entry*fee_rate*2
                                    trades.append(pnl); net_trades.append(net)
                                    combo_trades[idx].append(pnl)
                                    combo_net_trades[idx].append(net)
                    spike_rise=highs[i]-opens[i]
                    if spike_rise > a*SATR:
                        rec=(highs[i]-closes[i])/spike_rise
                        if MIN_REC<=rec<=MAX_REC:
                            tip=highs[i]; entry=closes[i]; root=opens[i]
                            tp=(entry-(entry-root)*TP_R if root<entry else entry-a*TP_R*0.3)
                            sl=max(tip+spike_rise*SL_R, tip+a*SL_ATR_M)
                            if tp<entry and sl>tip:
                                td=entry-tp; sd=sl-entry
                                if sd>0 and td/sd>=MIN_RR:
                                    future=klines[i+1:i+1+int(HOLD)]
                                    pnl=_sim_fast("SELL",entry,tp,sl,future)
                                    fee_rate=getattr(cfg_module,"FEE_RATE",0.001)
                                    net=pnl - entry*fee_rate*2
                                    trades.append(pnl); net_trades.append(net)
                                    combo_trades[idx].append(pnl)
                                    combo_net_trades[idx].append(net)
                STATE["grid_progress"]+=1
                if idx%5==0: await asyncio.sleep(0)
                if len(trades)>=3:
                    m=_calc_metrics(trades, net_trades)
                    sym_combo.append({"score":m.get(target,0),"p":dict(zip(keys,combo)),"m":m})
            sym_combo.sort(key=lambda x:x["score"],reverse=True)
            sym_results_all[symbol]=sym_combo[:10]
            STATE["grid_sym_results"]=dict(sym_results_all)
            log("  完成，有效组合 "+str(len(sym_combo))+" 个")
        await ex.close()
        log("汇总中...")
        agg=[]
        for idx,combo in enumerate(combos):
            t=combo_trades[idx]
            nt=combo_net_trades[idx]
            if len(t)<3: continue
            m=_calc_metrics(t, nt)
            m["symbols_covered"]=sum(1 for sr in sym_results_all.values()
                if any(all(r["p"].get(k)==v for k,v in zip(keys,combo)) for r in sr))
            agg.append({"score":m.get(target,0),"p":dict(zip(keys,combo)),"m":m})
        agg.sort(key=lambda x:x["score"],reverse=True)
        STATE["grid_results"]=agg[:10]; STATE["grid_best"]=agg[0]["p"] if agg else None
        log("完成！有效组合 "+str(len(agg))+" 个")
    except Exception as e:
        logger.error("Grid error: "+str(e),exc_info=True); log("错误: "+str(e))
    finally: STATE["grid_running"]=False

def _sim_fast(direction,entry,tp,sl,future):
    # 返回价差（不含手续费）
    for k in future:
        hi,lo=k["high"],k["low"]
        if direction=="BUY":
            if lo<=sl: return sl-entry
            if hi>=tp: return tp-entry
        else:
            if hi>=sl: return entry-sl
            if lo<=tp: return entry-tp
    ep=future[-1]["close"] if future else entry
    return (ep-entry) if direction=="BUY" else (entry-ep)


def _sim_fast_with_fee(direction, entry, tp, sl, future, fee_rate):
    # 返回净PnL比例（扣除开+平两笔手续费）
    gross = _sim_fast(direction, entry, tp, sl, future)
    # 双边手续费按入场价近似计算
    fee = entry * fee_rate * 2
    return gross - fee

def _calc_metrics(trades, net_trades=None):
    n=len(trades); wins=sum(1 for p in trades if p>0)
    wr=wins/n*100; total=sum(trades)
    aw=sum(p for p in trades if p>0)/max(wins,1)
    al=abs(sum(p for p in trades if p<0))/max(n-wins,1)
    ex=(wins/n)*aw-((n-wins)/n)*al
    std=statistics.stdev(trades) if n>1 else 1e-9
    sh=(total/n)/std if std>0 else 0
    avg_rr=round(aw/al,2) if al>0 else 0
    result = {"n":n,"win_rate":round(wr,1),"total_pnl":round(total,5),
            "expectancy":round(ex,6),"sharpe":round(sh,3),"avg_rr":avg_rr}
    # 如果提供了扣除手续费后的交易，额外计算净利润指标
    if net_trades is not None:
        nwins = sum(1 for p in net_trades if p > 0)
        nwr   = nwins / n * 100
        ntotal= sum(net_trades)
        nex   = ntotal / n
        result["net_win_rate"] = round(nwr, 1)
        result["net_total_pnl"] = round(ntotal, 5)
        result["net_expectancy"] = round(nex, 6)
    return result

async def run_web():
    app=web.Application()
    app.router.add_get("/",handle_index)
    app.router.add_get("/stream",handle_stream)
    app.router.add_post("/api/set_params",handle_set_params)
    app.router.add_post("/api/reset_circuit",handle_reset_circuit)
    app.router.add_post("/api/force_rescan",handle_force_rescan)
    app.router.add_post("/api/set_mode",handle_set_mode)
    app.router.add_post("/api/grid_search",handle_grid_search)
    runner=web.AppRunner(app); await runner.setup()
    site=web.TCPSite(runner,cfg_module.WEB_HOST,cfg_module.WEB_PORT)
    await site.start()
    logger.info(f"Dashboard: http://0.0.0.0:{cfg_module.WEB_PORT}")
    return runner
