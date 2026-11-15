/**
 * QQNexus 主进程
 * SnowLuma + AstrBot 一体化启动器
 *
 * 所有服务只监听 127.0.0.1；运行期不访问 GitHub / PyPI / npm。
 */
const { app, BrowserWindow, Tray, Menu, shell, ipcMain, dialog } = require('electron');
const { spawn, execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');
const https = require('https');
const http = require('http');
const crypto = require('crypto');

/* ============================== 路径 ============================== */
const PACKAGED = app.isPackaged;
const INSTALL = PACKAGED ? path.dirname(process.execPath) : __dirname;   // .../QQNexus/app 或 .../QQNexus/ui
const ROOT = PACKAGED ? path.join(INSTALL, '..') : path.join(__dirname, '..'); // .../QQNexus
const DATA = path.join(ROOT, 'astrbot', 'root', 'data');
const LOGS = path.join(ROOT, 'logs');
const AB_ROOT = path.join(ROOT, 'astrbot', 'root');
function pickIcon() {
  for (const p of [
    path.join(process.resourcesPath || INSTALL, 'app.ico'),
    path.join(INSTALL, 'icon.png'),
    path.join(process.resourcesPath || INSTALL, 'icon.png'),
  ]) if (fs.existsSync(p)) return p;
  return path.join(INSTALL, 'icon.png');
}
const ICON = pickIcon();

const AB_PORT = 6185;
const PORT_WS = 6199;
const CLIENT_NAME = 'qqnexus-astrbot';
const PORT_HTTP = 3000;
const PORT_VNC = 6081;
const WEBUI_PRIORITY = [5099, 8080, 8081];

let sl = null, ab = null, win = null, tray = null, wantRun = true;
let discovered = { webui: null, ws: null, live: [] };
const logBuf = [];

/* ============================== 日志与事件 ============================== */
const events = [];
let eventSeq = 0;
const MAX_EVENTS = 60;

const EVENT_RULES = [
  { re: /缺少\s*(node|astrbot)/i, tone: 'err', text: '缺少运行时', detail: () => '请用完整版发行包' },
  { re: /exit\s+(-?\d+)/i, tone: 'err', text: '进程退出', detail: m => 'code ' + m[1] + '，自动重启中' },
  { re: /aiocqhttp.*已连接|适配器已连接|connected\s+ws/i, tone: 'ok', text: '桥接已连通', detail: () => '' },
  { re: /WebUI\s*ready|panel\s*ready/i, tone: 'ok', text: '面板已就绪', detail: () => '' },
  { re: /已加载插件\s*(\d+)/i, tone: 'ok', text: '插件已加载', detail: m => m[1] + ' 个' },
  { re: /spawned\s+pid=(\d+)/i, tone: 'ok', text: '进程已启动', detail: m => 'pid ' + m[1] },
  { re: /token\s+ok/i, tone: 'ok', text: '凭证已同步', detail: () => '两端一致' },
  { re: /^ports\s/i, tone: 'ok', text: '端口探测完成', detail: () => '' },
  { re: /configs?\s+written/i, tone: 'warn', text: '配置已写入', detail: () => '' },
  { re: /已一致|skip.*write/i, tone: 'warn', text: '配置已一致', detail: () => '跳过写入' },
];

function pushEvent(tag, body) {
  const s = String(body || '');
  const isErr = /!$/.test(tag);
  for (const r of EVENT_RULES) {
    const m = s.match(r.re);
    if (!m) continue;
    const ev = {
      id: ++eventSeq,
      tone: isErr ? 'err' : r.tone,
      text: r.text,
      detail: typeof r.detail === 'function' ? r.detail(m) : '',
      who: tag.replace(/!$/, ''),
      ts: new Date().toISOString(),
    };
    const same = events.find(e => e.text === ev.text && e.detail === ev.detail);
    if (same) { same.ts = ev.ts; same.count = (same.count || 1) + 1; same.id = ev.id; }
    else { events.push(ev); if (events.length > MAX_EVENTS) events.shift(); }
    return;
  }
}

function log(tag, chunk) {
  const s = String(chunk).trim();
  if (!s) return;
  const line = `[${new Date().toISOString()}] [${tag}] ${s}`;
  logBuf.push(line);
  if (logBuf.length > 3000) logBuf.shift();
  try { fs.appendFileSync(path.join(LOGS, 'run.log'), line + '\n'); } catch (e) {}
  pushEvent(tag, s);
}

function mkdirs() {
  [DATA, LOGS].forEach(d => { try { fs.mkdirSync(d, { recursive: true }); } catch (e) {} });
}

/* ============================== 端口 ============================== */
function portOpen(port, timeout = 350) {
  return new Promise(res => {
    let done = false;
    const s = net.connect({ host: '127.0.0.1', port });
    const fin = v => { if (done) return; done = true; s.destroy(); res(v); };
    s.setTimeout(timeout, () => fin(false));
    s.on('connect', () => fin(true));
    s.on('error', () => fin(false));
  });
}

async function discover(deadlineMs = 90000) {
  const t0 = Date.now();
  while (Date.now() - t0 < deadlineMs) {
    const open = {};
    for (const p of [PORT_WS, PORT_HTTP, PORT_VNC, ...WEBUI_PRIORITY]) open[p] = await portOpen(p);
    const live = Object.keys(open).filter(k => open[k]).map(Number);
    if (live.length) {
      const webui = WEBUI_PRIORITY.find(p => open[p]) || null;
      const ws = open[PORT_WS] ? PORT_WS : null;
      return { webui, ws, live, open };
    }
    await new Promise(r => setTimeout(r, 1000));
  }
  return { webui: null, ws: null, live: [], open: {} };
}

/* ============================== 配置 ============================== */
function stripBom(s) {
  return typeof s === 'string' && s.charCodeAt(0) === 0xFEFF ? s.slice(1) : s;
}

function readJsonFile(fp) {
  const raw = stripBom(fs.readFileSync(fp, 'utf8'));
  return JSON.parse(raw);
}

function readCfg() {
  const p = path.join(DATA, 'cmd_config.json');
  if (fs.existsSync(p)) {
    try { return readJsonFile(p); } catch (e) { log('boot', '读取 cmd_config 失败: ' + e.message); }
  }
  const t = path.join(ROOT, 'astrbot', 'cmd_config.template.json');
  if (fs.existsSync(t)) {
    try { return JSON.parse(fs.readFileSync(t, 'utf8')); } catch (e) {}
  }
  return {};
}
function writeCfg(cfg) {
  // AstrBot 用 utf-8-sig 读写；这里同样写 BOM，保持两边编码一致
  const body = '\uFEFF' + JSON.stringify(cfg, null, 2);
  fs.writeFileSync(path.join(DATA, 'cmd_config.json'), body, 'utf8');
}

function bootstrap(wsPort) {
  const port = wsPort || PORT_WS;
  const tp = path.join(DATA, '.token');
  let token = fs.existsSync(tp) ? fs.readFileSync(tp, 'utf8').trim() : '';
  if (!token) { token = crypto.randomBytes(24).toString('base64url'); fs.writeFileSync(tp, token); }

  /* AstrBot 侧：解析失败时绝不写回，避免把用户配置整体覆盖 */
  let cfg;
  try {
    cfg = readJsonFile(path.join(DATA, 'cmd_config.json'));
  } catch (e) {
    if (fs.existsSync(path.join(DATA, 'cmd_config.json'))) {
      log('boot!', 'cmd_config.json 解析失败，跳过写入以保护配置: ' + e.message);
      return;
    }
    cfg = {};
  }
  /* 面板强制只监听回环，避免暴露到局域网 */
  cfg.dashboard = cfg.dashboard && typeof cfg.dashboard === 'object' ? cfg.dashboard : {};
  if (cfg.dashboard.host !== '127.0.0.1') {
    cfg.dashboard.host = '127.0.0.1';
    log('boot', 'dashboard.host 已修正为 127.0.0.1');
  }
  cfg.platform = Array.isArray(cfg.platform) ? cfg.platform : [];
  let p = cfg.platform.find(x => x.id === 'snowluma');
  if (!p) { p = { id: 'snowluma', type: 'aiocqhttp' }; cfg.platform.push(p); }
  Object.assign(p, {
    enable: true, ws_reverse_host: '127.0.0.1',
    ws_reverse_port: port, ws_reverse_token: token,
  });
  writeCfg(cfg);

  /* SnowLuma 侧：networks.wsClients 指向 AstrBot 的 OneBot 反向 WS，令牌必须与 AstrBot 一致 */
  const slDir = path.join(ROOT, 'snowluma', 'config');
  try { fs.mkdirSync(slDir, { recursive: true }); } catch (e) {}
  const connPath = path.join(slDir, 'connections.json');
  let slc = { networks: { wsClients: [] } };
  if (fs.existsSync(connPath)) {
    try { slc = readJsonFile(connPath); } catch (e) {}
  }
  slc.networks = slc.networks && typeof slc.networks === 'object' ? slc.networks : {};
  const clients = Array.isArray(slc.networks.wsClients) ? slc.networks.wsClients : [];
  const URL_WS = 'ws://127.0.0.1:' + port + '/ws';
  const mine = clients.find(c => c && c.name === CLIENT_NAME);
  const same = mine && mine.url === URL_WS && mine.accessToken === token && mine.enabled !== false;
  if (!same) {
    slc.networks.wsClients = clients.filter(c => !c || c.name !== CLIENT_NAME);
    slc.networks.wsClients.push({
      name: CLIENT_NAME, enabled: true, url: URL_WS, role: 'Universal',
      accessToken: token, messageFormat: 'array',
      reportSelfMessage: false, reconnectIntervalMs: 3000,
    });
    fs.writeFileSync(connPath, JSON.stringify(slc, null, 2));
    log('boot', 'connections.json 已写入 (ws=' + URL_WS + ')');
  } else {
    log('boot', 'connections.json 已一致，跳过写入');
  }

  /* SnowLuma 按 QQ 号落盘的 overlay 覆盖文件，令牌不同步会导致 403 */
  try {
    for (const f of fs.readdirSync(slDir)) {
      if (!/^onebot_\d+\.json$/.test(f)) continue;
      const fp = path.join(slDir, f);
      let oc = readJsonFile(fp);
      const nets = oc.networks && typeof oc.networks === 'object' ? oc.networks : {};
      const arr = Array.isArray(nets.wsClients) ? nets.wsClients : [];
      const list = arr.filter(c => !c || c.name !== CLIENT_NAME);
      list.push({
        name: CLIENT_NAME, enabled: true, url: URL_WS, role: 'Universal',
        accessToken: token, messageFormat: 'array',
        reportSelfMessage: false, reconnectIntervalMs: 3000,
      });
      oc.networks = Object.assign({}, nets, { wsClients: list });
      fs.writeFileSync(fp, JSON.stringify(oc, null, 2));
      log('boot', 'overlay 已同步: ' + f);
    }
  } catch (e) { log('boot', 'overlay 同步跳过: ' + e.message); }
  log('boot', 'token ok, ws=' + port);
}

function hardenOffline() {
  const p = path.join(ROOT, 'snowluma', 'config', 'app.json');
  if (!fs.existsSync(p)) return;
  const bak = p + '.orig';
  if (!fs.existsSync(bak)) { try { fs.copyFileSync(p, bak); } catch (e) {} }
  try {
    const c = readJsonFile(p);
    let touched = false;
    for (const k of ['autoUpdate', 'checkUpdate', 'telemetry']) {
      if (k in c && typeof c[k] === 'boolean' && c[k] !== false) { c[k] = false; touched = true; }
    }
    if (touched) fs.writeFileSync(p, JSON.stringify(c, null, 2));
  } catch (e) { log('boot', 'harden skip: ' + e.message); }
}

/* ============================== 进程 ============================== */
const ENV = () => ({
  ...process.env,
  ASTRBOT_ROOT: AB_ROOT,
  PYTHONUTF8: '1',
  TZ: 'Asia/Shanghai',
  PATH: `${path.join(ROOT, 'snowluma')};${path.join(ROOT, 'python')};${process.env.PATH}`,
});

function startSL() {
  const dir = path.join(ROOT, 'snowluma');
  const node = path.join(dir, 'node.exe');
  const entry = path.join(dir, 'index.mjs');
  if (!fs.existsSync(node) || !fs.existsSync(entry)) {
    log('SL!', '缺少 node.exe 或 index.mjs（是否用了 -lite 包？）');
    return;
  }
  sl = spawn(node, [entry], { cwd: dir, env: ENV(), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  sl.stdout.on('data', d => log('SL', d));
  sl.stderr.on('data', d => log('SL!', d));
  sl.on('exit', c => {
    log('SL', 'exit ' + c);
    sl = null;
    if (wantRun) setTimeout(startSL, 3000);
  });
  log('SL', 'spawned pid=' + sl.pid);
}

/* AstrBot 启动：带端口预检 + 指数退避，避免首启失败后疯狂重启 */
let abFails = 0;
let abStartedAt = 0;
let abRestartTimer = null;
let abStarting = false;          // 启动中的互斥锁，避免并发拉起两个实例

function clearPortIfStale(port, label) {
  return new Promise(resolve => {
    portOpen(port, 400).then(open => {
      if (!open) return resolve(true);
      log('AB!', label + ' 端口 ' + port + ' 已被占用，尝试清理残留进程');
      const ps = [
        '-NoProfile', '-NonInteractive', '-Command',
        "Get-NetTCPConnection -State Listen -LocalPort " + port +
        " -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }",
      ];
      try {
        spawn('powershell', ps, { windowsHide: true }).on('exit', () => {
          setTimeout(() => portOpen(port, 500).then(o => resolve(!o)), 1200);
        });
      } catch (e) { resolve(true); }
    });
  });
}

async function startAB() {
  const py  = path.join(ROOT, 'python', 'python.exe');
  const src = path.join(ROOT, 'astrbot', 'src');
  const dist = path.join(src, 'astrbot', 'dashboard', 'dist');
  const entry = path.join(src, 'main.py');

  if (!fs.existsSync(py)) { log('AB!', '缺少内嵌 Python：' + py); return; }
  if (!fs.existsSync(entry)) { log('AB!', '缺少 AstrBot 源码：' + entry); return; }
  if (!fs.existsSync(path.join(dist, 'index.html'))) { log('AB!', '缺少面板静态资源：' + dist); return; }

  if (ab && ab.pid) return;                      // 已在运行
  if (abStarting) return;                        // 正在启动，别重复拉起
  abStarting = true;

  try {
    await startABLocked();
  } finally {
    abStarting = false;
  }
}

async function startABLocked() {
  const py  = path.join(ROOT, 'python', 'python.exe');
  const src = path.join(ROOT, 'astrbot', 'src');
  const dist = path.join(src, 'astrbot', 'dashboard', 'dist');
  const entry = path.join(src, 'main.py');

  if (!(await clearPortIfStale(AB_PORT, 'AstrBot'))) {
    log('AB!', '端口 ' + AB_PORT + ' 无法释放，30 秒后重试');
    abRestartTimer = setTimeout(startAB, 30000);
    return;
  }

  fs.mkdirSync(AB_ROOT, { recursive: true });

  /* 每次启动前修一次配置：面板只监听回环，避免用户改过之后被暴露 */
  try {
    const cfg = readJsonFile(path.join(DATA, 'cmd_config.json'));
    cfg.dashboard = cfg.dashboard && typeof cfg.dashboard === 'object' ? cfg.dashboard : {};
    let dirty = false;
    if (cfg.dashboard.host !== '127.0.0.1') { cfg.dashboard.host = '127.0.0.1'; dirty = true; }
    if (cfg.dashboard.port !== AB_PORT) { cfg.dashboard.port = AB_PORT; dirty = true; }
    if (dirty) writeCfg(cfg);
  } catch (e) { log('AB!', '启动前配置校正跳过: ' + e.message); }

  const env = ENV();
  try {
    const cred = readJsonFile(path.join(ROOT, 'credential.json'));
    env.ASTRBOT_DASHBOARD_INITIAL_PASSWORD = cred.astrbot_password || '';
  } catch (e) {}

  abStartedAt = Date.now();
  ab = spawn(py, ['-u', entry, '--webui-dir', dist], { cwd: src, env, windowsHide: true });

  ab.stdout.on('data', d => log('AB', d));
  ab.stderr.on('data', d => log('AB!', d));
  ab.on('error', e => { log('AB!', 'spawn 失败: ' + e.message); });

  ab.on('exit', (c, sig) => {
    const ran = Date.now() - abStartedAt;
    log('AB', 'exit ' + c + (sig ? ' sig=' + sig : '') + ' 运行 ' + Math.round(ran / 1000) + 's');
    ab = null;
    if (!wantRun) return;
    /* 跑够 60 秒算稳定，重置失败计数；否则退避 3/5/10/20/30 秒 */
    if (ran >= 60000) abFails = 0;
    abFails = Math.min(abFails + 1, 6);
    const delays = [3000, 5000, 10000, 20000, 30000, 60000];
    const delay = delays[Math.min(abFails - 1, delays.length - 1)];
    log('AB', '将在 ' + Math.round(delay / 1000) + 's 后重启（连续失败 ' + abFails + ' 次）');
    abRestartTimer = setTimeout(startAB, delay);
  });

  log('AB', 'spawned pid=' + ab.pid);
}

function stopAll() {
  [sl, ab].forEach(p => {
    if (p && p.pid) {
      try { spawn('taskkill', ['/pid', String(p.pid), '/T', '/F'], { windowsHide: true }); } catch (e) {}
    }
  });
  sl = ab = null;
}

async function restartPipeline() {
  stopAll();
  await new Promise(r => setTimeout(r, 1500));
  bootstrap(null);            // 先落盘配置，再起进程
  startSL();
  startAB();
  discovered = await discover();
  log('boot', 'ports ' + JSON.stringify({ webui: discovered.webui, ws: discovered.ws }));
  if (discovered.ws && discovered.ws !== PORT_WS) bootstrap(discovered.ws);
  hardenOffline();
  return discovered;
}

/* ============================== 窗口 / 托盘 ============================== */
function createWin() {
  win = new BrowserWindow({
    width: 1080, height: 720, minWidth: 940, minHeight: 640,
    frame: false, backgroundColor: '#e8e5e1', show: false,
    title: 'QQNexus', icon: ICON,
    webPreferences: {
      preload: path.join(INSTALL, 'preload.js'),
      nodeIntegration: false, contextIsolation: true,
    },
  });
  win.setMenuBarVisibility(false);
  win.webContents.on('console-message', (_e, level, message, line, sourceId) => {
    log('UI', level + ' ' + message + ' @' + sourceId + ':' + line);
  });
  win.webContents.on('render-process-gone', (_e, d) => log('UI!', 'render gone: ' + JSON.stringify(d)));
  win.webContents.on('preload-error', (_e, p, err) => log('UI!', 'preload error ' + p + ' ' + err.message));
  win.loadFile(path.join(INSTALL, 'index.html'));
  win.once('ready-to-show', () => win.show());
  win.on('close', e => { if (wantRun) { e.preventDefault(); win.hide(); } });
  win.on('show', () => win.webContents.send('win-visibility', true));
  win.on('hide', () => win.webContents.send('win-visibility', false));
}

if (!app.requestSingleInstanceLock()) app.quit();
app.on('second-instance', () => { if (win) { win.show(); win.focus(); } });

app.on('ready', async () => {
  mkdirs();
  hardenOffline();
  createWin();

  bootstrap(null);            // AstrBot 启动前必须有配置
  startSL();
  startAB();
  startSampler();

  discover().then(p => {
    discovered = p;
    log('boot', 'ports ' + JSON.stringify({ webui: p.webui, ws: p.ws, live: p.live }));
    if (p.ws && p.ws !== PORT_WS) bootstrap(p.ws);
    hardenOffline();
    if (win && !win.isDestroyed()) win.webContents.send('ports-ready', p);
  }).catch(e => log('boot', 'discover fail: ' + e.message));

  /* 群名/人名回填：插件只在新消息时记名字，历史条目靠这里补齐 */
  const backfill = setInterval(() => {
    if (!wantRun) return;
    const script = path.join(ROOT, 'scripts', 'backfill_names.py');
    if (!fs.existsSync(script)) return;
    try {
      execFileSync(pyForScripts(), [script], { encoding: 'utf8', timeout: 15000, cwd: ROOT });
    } catch (e) {}
  }, 120000);
  app.on('before-quit', () => clearInterval(backfill));
  setTimeout(() => {
    const script = path.join(ROOT, 'scripts', 'backfill_names.py');
    if (!fs.existsSync(script)) return;
    try { execFileSync(pyForScripts(), [script], { encoding: 'utf8', timeout: 15000, cwd: ROOT }); } catch (e) {}
  }, 30000);

  /* 凭据同步：AstrBot 起来后核对面板账号密码，并把结果回写 credential.json */
  const credTimer = setInterval(() => {
    if (!wantRun) return;
    syncCredentialFromAstrBot();
  }, 15000);
  app.on('before-quit', () => clearInterval(credTimer));
  setTimeout(syncCredentialFromAstrBot, 20000);

  /* AstrBot 首启约 40s 才监听 6199，界面只探一次会误报未连通，因此持续轮询 */
  let lastSig = '';
  const poll = setInterval(async () => {
    if (!wantRun) return;
    const open = {};
    for (const pt of [PORT_WS, AB_PORT, ...WEBUI_PRIORITY]) open[pt] = await portOpen(pt);
    const webui = WEBUI_PRIORITY.find(x => open[x]) || discovered.webui;
    const ws = open[PORT_WS] ? PORT_WS : null;
    const sig = [webui, ws, open[AB_PORT]].join(':');
    if (sig === lastSig) return;
    lastSig = sig;
    discovered = { webui, ws, live: Object.keys(open).filter(k => open[k]).map(Number), ab: !!open[AB_PORT] };
    log('boot', 'ports ' + JSON.stringify({ webui, ws, ab: !!open[AB_PORT] }));
    if (win && !win.isDestroyed()) win.webContents.send('ports-ready', discovered);
  }, 4000);
  app.on('before-quit', () => clearInterval(poll));

  try {
    tray = new Tray(ICON);
    tray.setToolTip('QQNexus');
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: '打开面板', click: () => win && win.show() },
      { label: 'SnowLuma 面板', click: () => discovered.webui
          ? shell.openExternal(`http://127.0.0.1:${discovered.webui}`)
          : shell.openPath(path.join(LOGS, 'run.log')) },
      { label: `AstrBot :${AB_PORT}`, click: () => shell.openExternal(`http://127.0.0.1:${AB_PORT}`) },
      { type: 'separator' },
      { label: '重启全部', click: () => { restartPipeline().catch(() => {}); } },
      { label: '看日志', click: () => shell.openPath(path.join(LOGS, 'run.log')) },
      { type: 'separator' },
      { label: '退出', click: () => { wantRun = false; stopAll(); app.quit(); } },
    ]));
    tray.on('double-click', () => win && win.show());
  } catch (e) { log('boot', '托盘创建失败: ' + e.message); }
});

app.on('window-all-closed', e => e.preventDefault());
app.on('before-quit', () => { wantRun = false; stopAll(); stopSampler(); });

/* ============================== 通用工具 ============================== */
function apiRequest(base, pathname, apiKey, opt) {
  opt = opt || {};
  const method = opt.method || 'GET';
  const body = opt.body || null;
  const timeout = opt.timeout || 15000;
  return new Promise(resolve => {
    let u;
    try { u = new URL(base.replace(/\/+$/, '') + pathname); }
    catch (e) { return resolve({ status: 0, error: 'BASE_INVALID' }); }
    const mod = u.protocol === 'http:' ? http : https;
    const payload = body ? JSON.stringify(body) : null;
    const headers = { Authorization: 'Bearer ' + apiKey, 'User-Agent': 'QQNexus/1.0', Accept: 'application/json' };
    if (payload) { headers['Content-Type'] = 'application/json'; headers['Content-Length'] = Buffer.byteLength(payload); }
    const req = mod.request({
      hostname: u.hostname, port: u.port || (u.protocol === 'http:' ? 80 : 443),
      path: u.pathname + u.search, method, headers, timeout,
    }, res => {
      let b = '';
      res.on('data', d => { b += d; if (b.length > 4 * 1024 * 1024) res.destroy(); });
      res.on('end', () => {
        let json = null;
        try { json = JSON.parse(b); } catch (e) {}
        resolve({ status: res.statusCode, body: b, json });
      });
    });
    req.on('timeout', () => { req.destroy(); resolve({ status: 0, error: 'TIMEOUT' }); });
    req.on('error', e => resolve({ status: 0, error: e.code || e.message }));
    if (payload) req.write(payload);
    req.end();
  });
}

function explainStatus(r) {
  const c = r.status;
  if (c === 0) {
    if (r.error === 'TIMEOUT') return '请求超时，检查网络或 Base 地址';
    if (r.error === 'ENOTFOUND') return '域名解析失败，Base 可能写错了';
    if (r.error === 'ECONNREFUSED') return '端口拒绝连接';
    if (r.error === 'BASE_INVALID') return 'Base 地址格式不对';
    if (/CERT|SSL|TLS/i.test(r.error || '')) return '证书校验失败';
    return '网络错误：' + (r.error || 'unknown');
  }
  if (c === 401) return 'Key 无效或已过期（401）';
  if (c === 403) return 'Key 无权限（403）';
  if (c === 404) return '接口不存在，Base 可能少了 /v1（404）';
  if (c === 429) return '请求过于频繁（429）';
  if (c >= 500) return '服务端错误（' + c + '）';
  return 'HTTP ' + c;
}

function parseModels(json) {
  if (!json) return [];
  const pick = x => (typeof x === 'string' ? x : (x && (x.id || x.name || x.model)));
  if (Array.isArray(json.data)) return json.data.map(pick).filter(Boolean);
  if (Array.isArray(json.models)) return json.models.map(x => String(pick(x) || '').replace(/^models\//, '')).filter(Boolean);
  if (json.result && Array.isArray(json.result.data)) return json.result.data.map(pick).filter(Boolean);
  return [];
}

function rankModels(list) {
  const prefer = [/^deepseek-chat$/, /^deepseek-reasoner$/, /^gpt-4o-mini$/, /^gpt-4o$/,
    /^gpt-4\.1/, /^moonshot-v1/, /^qwen-plus$/, /^qwen-max$/, /^glm-4-plus$/, /^glm-4$/];
  const score = id => {
    for (let i = 0; i < prefer.length; i++) if (prefer[i].test(id)) return i;
    if (/embed|whisper|tts|dall-e|moderation|rerank|image-|audio/i.test(id)) return 900;
    return 500;
  };
  return [...new Set(list)].sort((a, b) => {
    const d = score(a) - score(b);
    return d !== 0 ? d : a.localeCompare(b);
  });
}

function pyForScripts() {
  /* 本安装用的是内嵌 Python，放在 ROOT/python/python.exe */
  for (const p of [
    path.join(ROOT, 'python', 'python.exe'),
    path.join(ROOT, 'astrbot', 'venv', 'Scripts', 'python.exe'),
    path.join(ROOT, 'astrbot', 'venv', 'bin', 'python'),
    path.join(ROOT, 'runtime', 'astrbot-venv', 'bin', 'python'),
  ]) if (fs.existsSync(p)) return p;
  return process.platform === 'win32' ? 'python' : 'python3';
}

function rootScript(name) {
  for (const p of [path.join(ROOT, name), path.join(ROOT, 'scripts', name)]) {
    if (fs.existsSync(p)) return p;
  }
  return null;
}

/* ============================== IPC：窗口与进程 ============================== */
ipcMain.handle('win-min', () => win && win.minimize());
ipcMain.handle('win-hide', () => win && win.hide());
ipcMain.handle('open-log-dir', () => shell.openPath(LOGS));
ipcMain.handle('quit-all', () => { wantRun = false; stopAll(); app.quit(); });
ipcMain.handle('open', (_e, u) => shell.openExternal(u));
ipcMain.handle('restart-all', async () => { await restartPipeline(); return true; });
ipcMain.handle('ports', () => discovered);
ipcMain.handle('resources', () => resSample);

ipcMain.handle('open-if', async (_e, url) => {
  const m = String(url || '').match(/^https?:\/\/127\.0\.0\.1:(\d+)/);
  if (!m) return { ok: false, msg: '地址不合法' };
  if (!(await portOpen(+m[1]))) return { ok: false, msg: '端口 ' + m[1] + ' 未开启' };
  shell.openExternal(url);
  return { ok: true };
});

/* ============================== 资源采样 ============================== */
/* 目标：真实 CPU% / 内存占用，且不拖慢界面。
   做法：常驻一个 PowerShell 采样进程，每 2 秒输出一次 JSON（进程树 CPU 秒数 +
   WorkingSet），主进程用两次采样的 CPU 时间差除以墙钟时间算百分比。 */
let resSample = { at: 0, cpu: 0, memMb: 0, procs: [], cores: 1, sysMemMb: 0 };
let sampler = null;
let lastCpuSec = null;
let lastCpuAt = 0;
/* 采样器脚本带唯一标记，便于精确清理，不会误杀其他 PowerShell */
const SAMPLER_TAG = 'QQNEXUS_SAMPLER_' + process.pid;

function samplerScript() {
  return [
    '$ErrorActionPreference = "SilentlyContinue"',
    '$tag = "QQNEXUS_SAMPLER_TAG"',
    'while ($true) {',
    '  $roots = @(' + 'ROOTPIDS' + ')',
    '  $ids = New-Object System.Collections.Generic.List[int]',
    '  foreach ($r in $roots) {',
    '    $ids.Add([int]$r)',
    '    Get-CimInstance Win32_Process -Filter "ParentProcessId=$r" | ForEach-Object { $ids.Add([int]$_.ProcessId) }',
    '  }',
    '  $rows = @()',
    '  foreach ($i in ($ids | Select-Object -Unique)) {',
    '    $p = Get-Process -Id $i',
    '    if ($p) { $rows += [pscustomobject]@{ pid = $p.Id; name = $p.ProcessName; mem = $p.WorkingSet64; cpu = $p.TotalProcessorTime.TotalSeconds } }',
    '  }',
    '  $sys = Get-CimInstance Win32_OperatingSystem',
    '  $obj = [pscustomobject]@{',
    '    at = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()',
    '    cores = [Environment]::ProcessorCount',
    '    sysFreeMb = [math]::Round($sys.FreePhysicalMemory / 1024)',
    '    sysTotalMb = [math]::Round($sys.TotalVisibleMemorySize / 1024)',
    '    procs = $rows',
    '  }',
    '  $obj | ConvertTo-Json -Compress -Depth 4',
    '  [Console]::Out.Flush()',
    '  Start-Sleep -Milliseconds 1500',
    '}',
  ].join('\n');
}

function startSampler() {
  if (sampler) return;
  const { spawn: spawnPs } = require('child_process');
  /* 先清掉上次残留的采样器（异常退出会留下孤儿进程，越积越多） */
  killStaleSamplers();
  const roots = [sl && sl.pid, ab && ab.pid, process.pid].filter(Boolean);
  const script = samplerScript()
    .replace('ROOTPIDS', roots.join(','))
    .replace('QQNEXUS_SAMPLER_TAG', SAMPLER_TAG);
  sampler = spawnPs('powershell', ['-NoProfile', '-NonInteractive', '-Command', script], {
    windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'],
  });
  let buf = '';
  sampler.stdout.on('data', d => {
    buf += d.toString();
    let idx;
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);
      if (!line || line[0] !== '{') continue;
      try { applySample(JSON.parse(line)); } catch (e) {}
    }
  });
  sampler.on('exit', () => { sampler = null; if (wantRun) setTimeout(startSampler, 3000); });
}

function applySample(s) {
  if (!s || !Array.isArray(s.procs)) return;
  let cpuSec = 0, mem = 0;
  for (const r of s.procs) { cpuSec += Number(r.cpu || 0); mem += Number(r.mem || 0); }
  const now = Date.now();
  let cpuPct = 0;
  if (lastCpuSec !== null && now > lastCpuAt) {
    const dcpu = Math.max(0, cpuSec - lastCpuSec);
    const dt = (now - lastCpuAt) / 1000;
    cpuPct = (dcpu / dt / (s.cores || 1)) * 100;
  }
  lastCpuSec = cpuSec;
  lastCpuAt = now;
  resSample = {
    at: now,
    cpu: Math.max(0, Math.min(100, Math.round(cpuPct * 10) / 10)),
    memMb: Math.round(mem / 1048576),
    cores: s.cores || 1,
    sysFreeMb: s.sysFreeMb || 0,
    sysTotalMb: s.sysTotalMb || 0,
    procs: s.procs.map(r => ({
      pid: r.pid, name: r.name,
      memMb: Math.round(Number(r.mem || 0) / 1048576),
    })),
  };
}

function killStaleSamplers() {
  const ps = [
    '-NoProfile', '-NonInteractive', '-Command',
    "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | " +
    "Where-Object { $_.CommandLine -like '*QQNEXUS_SAMPLER_*' -and $_.CommandLine -notlike '*" + SAMPLER_TAG + "*' } | " +
    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
  ];
  try { spawn('powershell', ps, { windowsHide: true }); } catch (e) {}
}

function stopSampler() {
  if (sampler) { try { spawn('taskkill', ['/pid', String(sampler.pid), '/T', '/F'], { windowsHide: true }); } catch (e) {} sampler = null; }
}

/* ============================== IPC：状态 ============================== */
ipcMain.handle('status', () => {
  let hasProvider = false, hasKey = false, providerId = null, model = null, apiBase = null;
  try {
    const cfg = readCfg();
    const pid = cfg.provider_settings && cfg.provider_settings.provider_id;
    const providers = cfg.provider || [];
    const sources = cfg.provider_sources || [];
    const pr = (pid ? providers.find(x => x.id === pid) : null) ||
               providers.find(x => x.enable !== false);
    if (pr) {
      const src = pr.provider_source_id
        ? sources.find(s => s.id === pr.provider_source_id) || {}
        : pr;
      const keys = Array.isArray(src.key) ? src.key : (src.key ? [src.key] : []);
      const key0 = keys[0] || src.api_key || '';
      hasProvider = true;
      hasKey = !!(key0 && String(key0).length > 10);
      providerId = pr.id; model = pr.model || null; apiBase = src.api_base || null;
    }
  } catch (e) {}
  return {
    snowluma: !!sl, astrbot: !!ab, dataDir: DATA,
    hasProvider, hasKey, providerId, model, apiBase,
    events: events.slice(-24).reverse(), eventSeq,
    log: logBuf.slice(-120).join('\n'),
  };
});

const FLAG = path.join(DATA, '.firstrun');
ipcMain.handle('is-first-run', () => !fs.existsSync(FLAG));
ipcMain.handle('first-run-done', () => { try { fs.writeFileSync(FLAG, '1'); } catch (e) {} });

/* ============================== IPC：模型 ============================== */
ipcMain.handle('fetch-models', async (_e, p) => {
  const base = String((p && p.api_base) || '').trim();
  const key = String((p && p.api_key) || '').trim();
  if (!base) return { ok: false, msg: '先填 API Base' };
  if (!key) return { ok: false, msg: '先填 API Key' };

  log('boot', 'fetch-models: ' + base + '/models');
  const r = await apiRequest(base, '/models', key, { method: 'GET' });

  if (r.status >= 200 && r.status < 300) {
    const models = rankModels(parseModels(r.json));
    if (models.length) {
      log('boot', 'fetch-models ok: ' + models.length + ' 个模型');
      return { ok: true, models, source: 'api', msg: '拉取到 ' + models.length + ' 个模型' };
    }
    return { ok: false, msg: '接口有返回，但没解析到模型名', models: [] };
  }
  if (r.status === 401 || r.status === 403) return { ok: false, msg: explainStatus(r), hard: true };
  if (r.status === 404) {
    const probe = await apiRequest(base, '/chat/completions', key, {
      method: 'POST',
      body: { model: p.model || 'gpt-4o-mini', messages: [{ role: 'user', content: 'hi' }], max_tokens: 1 },
    });
    if (probe.status === 401 || probe.status === 403) return { ok: false, msg: explainStatus(probe), hard: true };
    if (probe.status >= 200 && probe.status < 300) {
      return { ok: true, models: p.model ? [p.model] : [], source: 'probe', msg: '此网关不支持列出模型，但 Key 可用' };
    }
    return { ok: false, msg: '不支持模型列表，chat 探测也失败：' + explainStatus(probe) };
  }
  return { ok: false, msg: explainStatus(r) };
});

ipcMain.handle('test-provider', async (_e, p) => {
  const base = String((p && p.api_base) || '').trim();
  const key = String((p && p.api_key) || '').trim();
  const model = String((p && p.model) || '').trim();
  if (!base) return { ok: false, msg: '先填 API Base' };
  if (!key) return { ok: false, msg: '先填 API Key' };

  const m = await apiRequest(base, '/models', key, { method: 'GET' });
  if (m.status >= 200 && m.status < 300) {
    const list = rankModels(parseModels(m.json));
    if (model && list.length && list.indexOf(model) === -1) {
      return { ok: false, msg: 'Key 可用，但模型 "' + model + '" 不在列表里' };
    }
    return { ok: true, msg: '连通正常' };
  }
  if (m.status === 401 || m.status === 403) return { ok: false, msg: explainStatus(m) };

  const target = model || 'gpt-4o-mini';
  const c = await apiRequest(base, '/chat/completions', key, {
    method: 'POST',
    body: { model: target, messages: [{ role: 'user', content: 'hi' }], max_tokens: 1, stream: false },
  });
  if (c.status >= 200 && c.status < 300) return { ok: true, msg: 'Key 可用（chat 探测通过）' };
  if (c.status === 404) return { ok: false, msg: '模型 "' + target + '" 不存在（404）' };
  return { ok: false, msg: explainStatus(c) };
});

ipcMain.handle('save-provider', async (_e, p) => {
  if (!p || !p.api_key || !p.api_base || !p.model) {
    return { ok: false, msg: 'Key / Base / 模型名都不能空' };
  }
  const cfg = readCfg();
  const apiBase = p.api_base.replace(/\/+$/, '');

  /* AstrBot v4.29 分两层：provider_sources 存连接，provider 存模型 */
  const SRC_ID = 'qqnexus_source';
  const PRV_ID = 'qqnexus_model';

  cfg.provider_sources = Array.isArray(cfg.provider_sources) ? cfg.provider_sources : [];
  let src = cfg.provider_sources.find(x => x.id === SRC_ID);
  if (!src) { src = { id: SRC_ID }; cfg.provider_sources.push(src); }
  Object.assign(src, {
    provider: 'openai', type: 'openai_chat_completion',
    provider_type: 'chat_completion', enable: true,
    key: [p.api_key], api_base: apiBase, timeout: 120,
    proxy: '', custom_headers: {},
  });

  cfg.provider = Array.isArray(cfg.provider) ? cfg.provider : [];
  let pr = cfg.provider.find(x => x.id === PRV_ID);
  if (!pr) { pr = { id: PRV_ID }; cfg.provider.push(pr); }
  Object.assign(pr, {
    enable: true, provider_source_id: SRC_ID, model: p.model,
    modalities: ['text', 'image', 'tool_use'],
    custom_extra_body: {}, max_context_tokens: 1000000,
  });

  cfg.provider_settings = Object.assign({}, cfg.provider_settings, { provider_id: PRV_ID });

  if (p.system_prompt) {
    cfg.persona = Array.isArray(cfg.persona) ? cfg.persona : [];
    let pe = cfg.persona.find(x => x.id === 'cream');
    if (!pe) { pe = { id: 'cream', name: '奶油' }; cfg.persona.push(pe); }
    pe.system_prompt = p.system_prompt;
    cfg.provider_settings.persona_id = 'cream';
  }
  writeCfg(cfg);
  log('boot', 'provider saved: ' + p.model + ' @ ' + apiBase);

  syncToAstrBot(p);
  restartPipeline().catch(e => log('boot', 'restart fail: ' + e.message));
  return { ok: true, msg: '已保存，正在重载' };
});

/* ============================== IPC：同步到 AstrBot ============================== */
function syncToAstrBot(p) {
  const script = rootScript('apply_provider.py');
  if (!script) { log('boot', 'apply_provider.py 缺失，跳过同步'); return { ok: false }; }
  try {
    const out = execFileSync(pyForScripts(), [
      script,
      '--id', p.id || 'default',
      '--api-base', p.api_base,
      '--model', p.model,
      '--key', p.api_key || '',
      '--system-prompt', p.system_prompt || '',
    ], { encoding: 'utf8', timeout: 15000 });
    log('boot', 'AstrBot 同步: ' + out.trim());
    return { ok: true, msg: out.trim() };
  } catch (e) {
    log('boot', 'AstrBot 同步失败: ' + e.message);
    return { ok: false, msg: e.message };
  }
}

/* ============================== 凭据同步（客户端为准） ============================== */
/* AstrBot 面板只存 pbkdf2 哈希，反推不出明文，所以同步方向是：
   客户端 credential.json 为准 -> 面板密码向客户端看齐。
   面板一旦起得来，就核对一次；不一致就用客户端密码把面板改回来。 */
let lastCredSync = 0;

function syncCredentialFromAstrBot(force) {
  const now = Date.now();
  if (!force && now - lastCredSync < 60000) return;
  lastCredSync = now;

  const script = path.join(ROOT, 'scripts', 'sync_credential.py');
  if (!fs.existsSync(script)) return;

  const py = path.join(ROOT, 'python', 'python.exe');
  if (!fs.existsSync(py)) return;

  /* 面板没起来时登录必然失败，会被误判成「密码被改」，所以先确认端口活着 */
  if (!discovered || !discovered.ab) {
    portOpen(AB_PORT, 800).then(open => {
      if (!open) return;                     // 还没起来，下次再说
      runCredentialSync(py, script, force);
    });
    return;
  }
  runCredentialSync(py, script, force);
}

function runCredentialSync(py, script, force) {

  require('child_process').execFile(py, [script], { cwd: ROOT, timeout: 30000, encoding: 'utf8' }, (err, stdout) => {
    if (err) { log('boot', '凭据同步失败: ' + err.message); return; }
    let r = null;
    try { r = JSON.parse(String(stdout).trim().split('\n').pop()); } catch (e) { return; }
    if (!r) return;
    if (r.state === 'in-sync') return;
    if (r.state === 'panel-down') { log('boot', '面板未就绪，凭据同步稍后重试'); return; }
    if (r.state === 'panel-reset') {
      log('boot', '检测到面板密码被改动，已重置为客户端密码（备份 ' + r.backup + '），正在重启 AstrBot');
      if (win && !win.isDestroyed()) win.webContents.send('credential-synced', { state: r.state });
      restartAstrBotOnly();
      return;
    }
    if (r.state === 'user-fixed') {
      log('boot', 'AstrBot 用户名已同步为 ' + r.user);
      if (win && !win.isDestroyed()) win.webContents.send('credential-synced', { state: r.state, user: r.user });
    }
  });
}

/* 只重启 AstrBot，避免把 SnowLuma 的 QQ 会话一起断掉。
   启动后 90 秒内视为「正在启动」，不允许因为密码同步而重启，否则会陷入
   启动 -> 判定 -> 杀掉 -> 重启的死循环。 */
function restartAstrBotOnly() {
  const running = Date.now() - abStartedAt;
  if (ab && ab.pid && running < 90000) {
    log('boot', 'AstrBot 启动中（' + Math.round(running / 1000) + 's），跳过本次密码重置重启，稍后再试');
    lastCredSync = 0;                 // 让下一轮可以重试
    return false;
  }
  if (ab && ab.pid) {
    try { spawn('taskkill', ['/pid', String(ab.pid), '/T', '/F'], { windowsHide: true }); } catch (e) {}
  }
  ab = null;
  setTimeout(() => { if (wantRun) startAB(); }, 2500);
  return true;
}

function verifyDashboardPassword(raw, stored) {
  try {
    if (!raw || !stored) return null;
    const parts = String(stored).split('$');
    if (parts.length !== 4) return null;
    const [, iter, salt, hash] = parts;
    const calc = crypto.pbkdf2Sync(raw, salt, parseInt(iter, 10), 32, 'sha256').toString('base64');
    return calc === hash;
  } catch (e) { return null; }
}

/* ============================== IPC：凭据 ============================== */
/* 把 AstrBot 面板密码重置成 credential.json 里的那份，供界面一键修复 */
ipcMain.handle('resync-credential-password', () => {
  const script = path.join(ROOT, 'scripts', 'sync_password.py');
  if (!fs.existsSync(script)) return { ok: false, msg: '缺少 sync_password.py' };
  try {
    const out = execFileSync(path.join(ROOT, 'python', 'python.exe'), [script], {
      encoding: 'utf8', timeout: 30000, cwd: ROOT,
    });
    log('boot', '面板密码已重置: ' + out.trim());
    const credPath = path.join(ROOT, 'credential.json');
    try {
      const cred = readJsonFile(credPath);
      if (cred.astrbot_password_synced === false) {
        cred.astrbot_password_synced = true;
        fs.writeFileSync(credPath, JSON.stringify(cred, null, 2), 'utf8');
      }
    } catch (e) {}
    return { ok: true, msg: out.trim() };
  } catch (e) {
    log('boot', '面板密码重置失败: ' + e.message);
    return { ok: false, msg: e.message };
  }
});

/* 在客户端设置 AstrBot 面板密码：写入 credential.json，并把面板哈希改成同一个值。
   这样密码以客户端为准，不再依赖面板里那个无法反推的哈希。 */
ipcMain.handle('set-astrbot-password', (_e, payload) => {
  const pwd = String((payload && payload.password) || '');
  const user = String((payload && payload.username) || '').trim();

  if (pwd.length < 8) return { ok: false, msg: '密码至少 8 位' };
  if (!/[A-Za-z]/.test(pwd) || !/[0-9]/.test(pwd)) return { ok: false, msg: '密码需同时包含字母和数字' };

  const credPath = path.join(ROOT, 'credential.json');
  let cred;
  try { cred = readJsonFile(credPath); } catch (e) { return { ok: false, msg: 'credential.json 读取失败' }; }

  const oldPwd = cred.astrbot_password;
  const oldUser = cred.astrbot_user;
  cred.astrbot_password = pwd;
  if (user) cred.astrbot_user = user;
  cred.astrbot_password_synced = true;
  delete cred.astrbot_password_updated_at;
  cred.astrbot_password_updated_at = new Date().toISOString();

  try {
    fs.writeFileSync(credPath, JSON.stringify(cred, null, 2), 'utf8');
  } catch (e) { return { ok: false, msg: 'credential.json 写入失败: ' + e.message }; }

  const script = path.join(ROOT, 'scripts', 'sync_password.py');
  if (!fs.existsSync(script)) return { ok: true, msg: '密码已保存到本机（面板将在下次启动生效）' };

  try {
    const out = execFileSync(path.join(ROOT, 'python', 'python.exe'), [script], {
      encoding: 'utf8', timeout: 30000, cwd: ROOT,
    });
    log('boot', '面板密码已更新为客户端设置值');
    lastCredSync = Date.now();          // 刚设过，别立刻再触发同步
    /* 面板需要重启才会用新密码校验，交给调用方决定是否重启 */
    return { ok: true, msg: '密码已更新，重启 AstrBot 后生效', out: out.trim(), needRestart: true };
  } catch (e) {
    log('boot', '面板密码写入失败: ' + e.message);
    /* 回滚，避免客户端和面板彻底对不上 */
    cred.astrbot_password = oldPwd;
    if (oldUser) cred.astrbot_user = oldUser;
    try { fs.writeFileSync(credPath, JSON.stringify(cred, null, 2), 'utf8'); } catch (err) {}
    return { ok: false, msg: '面板密码写入失败：' + e.message };
  }
});

ipcMain.handle('get-credentials', () => {
  for (const p of [
    path.join(ROOT, 'credential.json'),
    path.join(ROOT, '..', 'credential.json'),
    path.join(app.getPath('userData'), 'credential.json'),
  ]) {
    if (!fs.existsSync(p)) continue;
    try {
      const raw = readJsonFile(p);
      return {
        astrbot_user: raw.astrbot_user || '',
        astrbot_password: raw.astrbot_password || '',
        astrbot_password_synced: raw.astrbot_password_synced !== false,
        snowluma_password: raw.snowluma_password || '',
        onebot_token: raw.onebot_token || '',
      };
    } catch (e) { log('boot', '读取 credential.json 失败: ' + e.message); return null; }
  }
  return null;
});

/* ============================== IPC：统计 ============================== */
ipcMain.handle('get-stats', () => {
  let p = null;
  for (const c of [
    path.join(ROOT, 'astrbot', 'root', 'data', 'qqnexus_stats.json'),
    path.join(ROOT, 'runtime', 'astrbot', 'data', 'qqnexus_stats.json'),
    path.join(DATA, 'qqnexus_stats.json'),
  ]) if (fs.existsSync(c)) { p = c; break; }

  if (!p) return { total: 0, group_total: 0, private_total: 0, sessions: 0, groups: {}, privates: {}, updated_at: 0 };
  try {
    const raw = JSON.parse(fs.readFileSync(p, 'utf8'));
    const trim = (obj, n) => Object.fromEntries(
      Object.entries(obj || {})
        .sort((a, b) => (b[1].count || 0) - (a[1].count || 0))
        .slice(0, n)
        .map(([k, v]) => [k, {
          count: (v && v.count) || 0,
          last_seen: (v && v.last_seen) || 0,
          name: (v && v.name) || '',
        }]));
    return {
      total: raw.total || 0, group_total: raw.group_total || 0,
      private_total: raw.private_total || 0, sessions: raw.sessions || 0,
      updated_at: raw.updated_at || 0,
      groups: trim(raw.groups, 12), privates: trim(raw.privates, 12),
    };
  } catch (e) { log('boot', '读取 qqnexus_stats.json 失败: ' + e.message); return null; }
});

/* Token 统计：起 Python 进程读 sqlite 有 200~400ms 开销，做成后台异步缓存，
   界面按需读缓存，既实时又不卡。 */
let tokenCache = null;
let tokenCacheAt = 0;
let tokenLoading = false;

function refreshTokenCache() {
  if (tokenLoading) return;
  const script = rootScript('token_stats.py');
  if (!script) return;
  tokenLoading = true;
  require('child_process').execFile(
    pyForScripts(), [script],
    { encoding: 'utf8', timeout: 15000, cwd: ROOT },
    (err, stdout) => {
      tokenLoading = false;
      if (err) { log('boot', 'Token 统计失败: ' + err.message); return; }
      try {
        tokenCache = JSON.parse(String(stdout).trim().split('\n').pop() || '{}');
        tokenCacheAt = Date.now();
      } catch (e) { log('boot', 'Token 统计解析失败: ' + e.message); }
    }
  );
}

ipcMain.handle('get-token-stats', () => {
  /* 缓存超过 5 秒就在后台刷新，先返回旧值保证界面不卡 */
  if (!tokenCache || Date.now() - tokenCacheAt > 5000) refreshTokenCache();
  if (!tokenCache) return null;
  return Object.assign({}, tokenCache, { cacheAgeMs: Date.now() - tokenCacheAt });
});

/* ============================== IPC：健康探测 ============================== */
function probeOne(port, timeout) {
  return new Promise(resolve => {
    const started = Date.now();
    const req = http.request({ hostname: '127.0.0.1', port, path: '/', method: 'GET', timeout: timeout || 3000 }, res => {
      let b = '';
      res.on('data', d => { b += d; if (b.length > 4000) res.destroy(); });
      res.on('end', () => resolve({ ok: res.statusCode >= 200 && res.statusCode < 500, status: res.statusCode, ms: Date.now() - started }));
      res.on('error', () => resolve({ ok: false, status: 0, ms: Date.now() - started }));
    });
    req.on('timeout', () => { req.destroy(); resolve({ ok: false, status: 0, ms: timeout, timeout: true }); });
    req.on('error', () => resolve({ ok: false, status: 0, ms: Date.now() - started }));
    req.end();
  });
}

ipcMain.handle('probe-health', async (_e, p) => {
  const list = (p && Array.isArray(p.targets)) ? p.targets : [];
  const results = await Promise.all(list.map(async t => {
    const r = await probeOne(t.port, 3000);
    return { key: t.key, name: t.name, port: t.port, ok: r.ok, status: r.status, ms: r.ms, timeout: !!r.timeout };
  }));
  return { at: Date.now(), results };
});

/* ============================== IPC：文件与图片 ============================== */
ipcMain.handle('pick-image', async () => {
  try {
    const { canceled, filePaths } = await dialog.showOpenDialog(win, {
      title: '选择壁纸', properties: ['openFile'],
      filters: [{ name: '图片', extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp'] }],
    });
    if (canceled || !filePaths || !filePaths.length) return { ok: false, canceled: true };
    const p = filePaths[0];
    const stat = fs.statSync(p);
    if (stat.size > 8 * 1024 * 1024) return { ok: false, msg: '图片超过 8MB' };
    const ext = path.extname(p).slice(1).toLowerCase();
    const mime = (ext === 'jpg' || ext === 'jpeg') ? 'image/jpeg'
      : ext === 'webp' ? 'image/webp' : ext === 'bmp' ? 'image/bmp' : 'image/png';
    const b64 = fs.readFileSync(p).toString('base64');
    return { ok: true, dataUrl: `data:${mime};base64,${b64}`, size: stat.size };
  } catch (e) { return { ok: false, msg: e.message }; }
});

ipcMain.handle('save-file', async (_e, p) => {
  try {
    const defaultPath = path.join(app.getPath('downloads'), p.name || 'export.json');
    const { canceled, filePath } = await dialog.showSaveDialog(win, {
      title: '导出配置文件', defaultPath, filters: [{ name: 'JSON', extensions: ['json'] }],
    });
    if (canceled || !filePath) return { ok: false, canceled: true };
    fs.writeFileSync(filePath, String(p.text || ''), 'utf8');
    log('boot', 'config exported: ' + filePath);
    return { ok: true, path: filePath };
  } catch (e) { return { ok: false, msg: e.message }; }
});

ipcMain.handle('pick-file', async (_e, p) => {
  try {
    const { canceled, filePaths } = await dialog.showOpenDialog(win, {
      title: '导入配置文件', properties: ['openFile'],
      filters: (p && p.filters) || [{ name: 'JSON', extensions: ['json'] }],
    });
    if (canceled || !filePaths || !filePaths.length) return { ok: false, canceled: true };
    const filePath = filePaths[0];
    const stat = fs.statSync(filePath);
    if (stat.size > 2 * 1024 * 1024) return { ok: false, msg: '文件过大（>2MB）' };
    return { ok: true, path: filePath, text: fs.readFileSync(filePath, 'utf8') };
  } catch (e) { return { ok: false, msg: e.message }; }
});
