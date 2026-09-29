#!/usr/bin/env node
/**
 * shoot.mjs —— 零依赖的 CDP 截图驱动（无头 Chrome）
 *
 * 用途：按一份 JSON 配置批量截图，支持"必须先往 localStorage 塞登录令牌才能进"的页面。
 * 依赖：只用 Node 内置能力（Node 22 自带全局 fetch 与全局 WebSocket），不装任何 npm 包。
 *
 * 用法：
 *   node tools/shoot.mjs <config.json> [outDir]
 *     <config.json>  必填，配置路径（见 shoot.config.example.json）
 *     [outDir]       选填，覆盖配置里的 outDir
 *
 * 退出码：全部成功 0；任何一个 shot 失败则把错误打到 stderr 并以 1 退出。
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import net from 'node:net';
import { spawn, spawnSync } from 'node:child_process';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 浏览器候选路径：优先用配置里的，其次本机 Chrome，最后退到 Edge。 */
const BROWSER_CANDIDATES = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
];

const DEFAULTS = {
  width: 1600,
  height: 1000,
  deviceScaleFactor: 1,
  tokenKey: 'docwise_token',
  waitForTimeout: 8000,
  cdpTimeout: 20000, // 单条 CDP 命令超时：任何命令都不允许无限挂起
  navTimeout: 15000,
};

// ---------------------------------------------------------------------------
// CDP 客户端：一条 WebSocket + id 请求响应表 + 事件监听表
// ---------------------------------------------------------------------------

class CdpClient {
  constructor(wsUrl, { timeoutMs = DEFAULTS.cdpTimeout } = {}) {
    this.wsUrl = wsUrl;
    this.timeoutMs = timeoutMs;
    this._seq = 0;
    this._pending = new Map(); // id -> { resolve, reject, timer, method }
    this._listeners = new Map(); // `${sessionId}|${method}` -> Set<fn>
    this._closed = false;
  }

  /** 建立连接并等握手完成。 */
  connect() {
    return new Promise((resolve, reject) => {
      let ws;
      try {
        ws = new WebSocket(this.wsUrl);
      } catch (err) {
        reject(new Error(`无法创建 WebSocket 连接 ${this.wsUrl}: ${err.message}`));
        return;
      }
      this.ws = ws;

      const onError = (ev) => {
        ws.removeEventListener('open', onOpen);
        reject(new Error(`WebSocket 连接失败 ${this.wsUrl}: ${ev?.message || ev?.error?.message || 'unknown'}`));
      };
      const onOpen = () => {
        ws.removeEventListener('error', onError);
        resolve(this);
      };

      ws.addEventListener('error', onError);
      ws.addEventListener('open', onOpen);
      ws.addEventListener('message', (ev) => this._onMessage(ev.data));
      ws.addEventListener('close', () => {
        this._closed = true;
        // 连接断了以后，所有在飞的请求立即失败，绝不留下悬挂的 promise
        for (const [id, entry] of this._pending) {
          clearTimeout(entry.timer);
          this._pending.delete(id);
          entry.reject(new Error(`CDP 连接已关闭，命令未完成: ${entry.method}`));
        }
      });
    });
  }

  _onMessage(raw) {
    let msg;
    try {
      msg = JSON.parse(typeof raw === 'string' ? raw : Buffer.from(raw).toString('utf8'));
    } catch {
      return; // 协议外的脏帧直接忽略
    }

    if (msg.id != null && this._pending.has(msg.id)) {
      const entry = this._pending.get(msg.id);
      this._pending.delete(msg.id);
      clearTimeout(entry.timer);
      if (msg.error) {
        entry.reject(new Error(`CDP ${entry.method} 出错: ${msg.error.message || JSON.stringify(msg.error)}`));
      } else {
        entry.resolve(msg.result || {});
      }
      return;
    }

    if (msg.method) {
      const key = `${msg.sessionId || ''}|${msg.method}`;
      const set = this._listeners.get(key);
      if (set) {
        for (const fn of [...set]) {
          try {
            fn(msg.params || {});
          } catch {
            /* 监听器里的异常不影响主流程 */
          }
        }
      }
    }
  }

  /** 发一条 CDP 命令，按 id 配对返回；超时即拒绝（默认 20s）。 */
  send(method, params = {}, sessionId) {
    const id = ++this._seq;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this._pending.delete(id);
        reject(new Error(`CDP 命令超时(${this.timeoutMs}ms): ${method}`));
      }, this.timeoutMs);

      this._pending.set(id, { resolve, reject, timer, method });

      try {
        this.ws.send(JSON.stringify(payload));
      } catch (err) {
        clearTimeout(timer);
        this._pending.delete(id);
        reject(new Error(`CDP 命令发送失败 ${method}: ${err.message}`));
      }
    });
  }

  /** 注册事件监听（按 sessionId + method 精确匹配）。 */
  on(method, sessionId, handler) {
    const key = `${sessionId || ''}|${method}`;
    if (!this._listeners.has(key)) this._listeners.set(key, new Set());
    this._listeners.get(key).add(handler);
    return () => this._listeners.get(key)?.delete(handler);
  }

  /** 等一个事件（超时返回 null，由调用方决定是否致命）。 */
  waitForEvent(method, sessionId, timeoutMs) {
    return new Promise((resolve) => {
      let done = false;
      const off = this.on(method, sessionId, (params) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        off();
        resolve(params);
      });
      const timer = setTimeout(() => {
        if (done) return;
        done = true;
        off();
        resolve(null);
      }, timeoutMs);
    });
  }

  close() {
    try {
      this.ws?.close();
    } catch {
      /* ignore */
    }
  }
}

// ---------------------------------------------------------------------------
// 浏览器进程 / DevTools 端点
// ---------------------------------------------------------------------------

/** 让系统分配一个空闲端口（listen 0 再关掉）。 */
function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function fileExists(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

function resolveBrowser(explicit) {
  if (explicit) {
    if (!fileExists(explicit)) throw new Error(`配置里的 chrome 路径不存在: ${explicit}`);
    return explicit;
  }
  for (const c of BROWSER_CANDIDATES) if (fileExists(c)) return c;
  throw new Error(`没找到可用的 Chrome/Edge，尝试过:\n  ${BROWSER_CANDIDATES.join('\n  ')}`);
}

/** Chrome 启动时会把实际端口写进 user-data-dir/DevToolsActivePort（第一行=端口）。 */
function readActivePort(userDataDir) {
  try {
    const txt = fs.readFileSync(path.join(userDataDir, 'DevToolsActivePort'), 'utf8');
    const port = Number.parseInt(txt.split(/\r?\n/)[0], 10);
    return Number.isInteger(port) && port > 0 ? port : null;
  } catch {
    return null;
  }
}

/** 探一下某个端口上是不是已经有一个 DevTools HTTP 端点。 */
async function probeVersion(port) {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/json/version`, {
      signal: AbortSignal.timeout(1500),
    });
    if (!res.ok) return null;
    const info = await res.json();
    return info?.webSocketDebuggerUrl ? info : null;
  } catch {
    return null;
  }
}

/** 读 Chrome 的 stderr 日志尾部（失败诊断用；文件可能还被 Chrome 占着，读不到就返回空）。 */
function readTail(p, limit = 4000) {
  try {
    return fs.readFileSync(p, 'utf8').slice(-limit).trim();
  } catch {
    return '';
  }
}

/**
 * 等 DevTools 端点就绪。
 * 端口给的是我们预先挑的空闲端口；同时读 DevToolsActivePort 兜底
 * （端口被抢占 / Chrome 自行改端口时以它写的为准）。
 */
async function resolveDevTools(userDataDir, candidatePort, child, getStderr, timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      const err = getStderr();
      throw new Error(
        `Chrome 启动后立即退出（exit code ${child.exitCode}）${err ? `\n--- chrome stderr ---\n${err}` : ''}`,
      );
    }
    const active = readActivePort(userDataDir);
    if (active) {
      const info = await probeVersion(active);
      if (info) return { port: active, info };
    }
    const info = await probeVersion(candidatePort);
    if (info) return { port: candidatePort, info };
    await sleep(150);
  }
  const err = getStderr();
  throw new Error(
    `等待 Chrome DevTools 端点超时(${timeoutMs}ms)，端口 ${candidatePort}${err ? `\n--- chrome stderr ---\n${err}` : ''}`,
  );
}

/** 杀进程树（Windows 上必须用 taskkill /T，否则 Chrome 的子进程会留下来）。 */
function killProcessTree(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  try {
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      child.kill('SIGKILL');
    }
  } catch {
    /* ignore */
  }
  try {
    child.kill('SIGKILL');
  } catch {
    /* ignore */
  }
}

function removeDirWithRetry(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 150 });
  } catch (err) {
    console.error(`[warn] 临时目录删除失败（可手动清理）: ${dir} — ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// 登录令牌
// ---------------------------------------------------------------------------

/**
 * 用 Node 自带 fetch 直接打登录接口，拿 token。
 * 注意：在启动 Chrome 之前做，令牌拿不到就根本不必开浏览器。
 */
async function fetchAuthToken(auth) {
  if (!auth?.loginUrl) throw new Error('config.auth 存在但缺少 loginUrl');
  if (!auth.username || !auth.password) throw new Error('config.auth 缺少 username / password');

  let res;
  try {
    res = await fetch(auth.loginUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ username: auth.username, password: auth.password }),
      signal: AbortSignal.timeout(15000),
    });
  } catch (err) {
    throw new Error(`登录请求失败 ${auth.loginUrl}: ${err.message}`);
  }

  const text = await res.text();
  if (!res.ok) {
    throw new Error(`登录失败 HTTP ${res.status} ${res.statusText} — ${auth.loginUrl}\n${text.slice(0, 400)}`);
  }

  let body;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(`登录响应不是 JSON — ${auth.loginUrl}\n${text.slice(0, 400)}`);
  }

  const token = body?.token ?? body?.access_token;
  if (!token || typeof token !== 'string') {
    throw new Error(`登录响应里没有 token 字段 — ${auth.loginUrl}\n${text.slice(0, 400)}`);
  }
  return token;
}

// ---------------------------------------------------------------------------
// 页面操作
// ---------------------------------------------------------------------------

/** 导航并等 load 事件（等不到就只告警，靠后续 waitFor 兜底）。 */
async function navigate(cdp, sessionId, url, { timeout = DEFAULTS.navTimeout } = {}) {
  const loaded = cdp.waitForEvent('Page.loadEventFired', sessionId, timeout);
  const res = await cdp.send('Page.navigate', { url }, sessionId);
  if (res.errorText) console.error(`[warn] 导航到 ${url} 失败: ${res.errorText}`);
  const ok = await loaded;
  if (!ok) console.error(`[warn] 等待 loadEventFired 超时(${timeout}ms): ${url}`);
}

/** 跑一段 JS 表达式，返回完整的 Runtime.evaluate 结果。 */
function evaluate(cdp, sessionId, expression) {
  return cdp.send(
    'Runtime.evaluate',
    { expression, returnByValue: true, awaitPromise: true, userGesture: true },
    sessionId,
  );
}

function isTruthyResult(res) {
  if (!res || res.exceptionDetails) return false;
  const r = res.result;
  if (!r || r.subtype === 'error') return false;
  return Boolean(r.value);
}

/** 把 shot 的 steps 一条条执行掉。 */
async function runSteps(cdp, sessionId, shotName, steps) {
  const list = Array.isArray(steps) ? steps : [];
  const STEP_KEYS = ['wait', 'waitFor', 'eval', 'click'];

  for (let i = 0; i < list.length; i++) {
    const step = list[i] || {};
    const present = STEP_KEYS.filter((k) => Object.prototype.hasOwnProperty.call(step, k));
    if (present.length !== 1) {
      throw new Error(
        `shot "${shotName}" 第 ${i + 1} 个 step 必须且只能有 wait / waitFor / eval / click 之一，实际: ${JSON.stringify(step)}`,
      );
    }

    if (present[0] === 'wait') {
      const ms = Number(step.wait);
      if (!Number.isFinite(ms) || ms < 0) throw new Error(`shot "${shotName}" 的 wait 不是合法毫秒数: ${step.wait}`);
      await sleep(ms);
      continue;
    }

    if (present[0] === 'waitFor') {
      const expr = String(step.waitFor);
      const timeout = Number.isFinite(Number(step.timeout)) ? Number(step.timeout) : DEFAULTS.waitForTimeout;
      const deadline = Date.now() + timeout;
      let last = null;
      let satisfied = false;
      while (Date.now() < deadline) {
        last = await evaluate(cdp, sessionId, expr);
        if (isTruthyResult(last)) {
          satisfied = true;
          break;
        }
        await sleep(150);
      }
      if (!satisfied) {
        const detail = last?.exceptionDetails?.exception?.description || last?.exceptionDetails?.text || '';
        throw new Error(
          `shot "${shotName}" 第 ${i + 1} 个 step waitFor 超时(${timeout}ms)，表达式始终为假: ${expr}` +
            (detail ? `\n  表达式抛错: ${String(detail).split('\n')[0]}` : ''),
        );
      }
      continue;
    }

    if (present[0] === 'eval') {
      const expr = String(step.eval);
      const res = await evaluate(cdp, sessionId, expr);
      if (res.exceptionDetails) {
        const d = res.exceptionDetails.exception?.description || res.exceptionDetails.text || 'unknown';
        console.error(`[warn] shot "${shotName}" 第 ${i + 1} 个 step eval 抛错: ${String(d).split('\n')[0]}`);
      }
      continue;
    }

    // click
    const sel = String(step.click);
    const res = await evaluate(
      cdp,
      sessionId,
      `(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return false; el.click(); return true; })()`,
    );
    if (res.exceptionDetails) {
      const d = res.exceptionDetails.exception?.description || res.exceptionDetails.text || 'unknown';
      throw new Error(
        `shot "${shotName}" 第 ${i + 1} 个 step click 执行出错，选择器 ${sel}: ${String(d).split('\n')[0]}`,
      );
    }
    if (res.result?.value !== true) {
      throw new Error(`shot "${shotName}" 第 ${i + 1} 个 step click 找不到元素: ${sel}`);
    }
  }
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

function readConfig(configPath) {
  let raw;
  try {
    raw = fs.readFileSync(configPath, 'utf8');
  } catch (err) {
    throw new Error(`读不到配置文件 ${configPath}: ${err.message}`);
  }
  try {
    return JSON.parse(raw.replace(/^\uFEFF/, ''));
  } catch (err) {
    throw new Error(`配置文件不是合法 JSON ${configPath}: ${err.message}`);
  }
}

async function run() {
  const configPath = process.argv[2];
  if (!configPath || configPath === '-h' || configPath === '--help') {
    console.error('用法: node tools/shoot.mjs <config.json> [outDir]');
    process.exit(configPath ? 0 : 1);
  }

  const config = readConfig(configPath);
  if (!Array.isArray(config.shots) || config.shots.length === 0) {
    throw new Error('配置里 shots 必须是非空数组');
  }

  // 输出目录：命令行第二个参数 > 配置里的 outDir > 系统临时目录。
  // 默认落到临时目录而不是仓库里，免得截图凭空污染工作区。
  const outDirArg = process.argv[3];
  const outDir = path.resolve(outDirArg || config.outDir || path.join(os.tmpdir(), 'docwise-shots'));
  fs.mkdirSync(outDir, { recursive: true });

  const width = Number(config.width) || DEFAULTS.width;
  const height = Number(config.height) || DEFAULTS.height;

  // ① 先换登录令牌（拿不到就直接失败，不用浪费一次浏览器启动）
  const auth = config.auth || null;
  let token = null;
  let tokenKey = DEFAULTS.tokenKey;
  if (auth) {
    tokenKey = auth.tokenKey || DEFAULTS.tokenKey;
    token = await fetchAuthToken(auth);
    console.error(`[info] 已取得登录令牌，将写入 localStorage["${tokenKey}"]`);
  }

  const browserPath = resolveBrowser(config.chrome);
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'docwise-shoot-'));
  const port = await getFreePort();
  let child = null;
  let cdp = null;

  try {
    const args = [
      '--headless=new',
      '--disable-gpu',
      '--hide-scrollbars',
      '--no-first-run',
      '--no-default-browser-check',
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${userDataDir}`,
      `--window-size=${width},${height}`,
      'about:blank',
    ];

    // Chrome 的 stderr 落成文件而不是走管道：管道在被沙箱限制的环境里会 spawn EPERM，
    // 文件句柄两边都通用；日志放在 user-data-dir 里，清理临时目录时一起删掉。
    const chromeLogPath = path.join(userDataDir, 'chrome-stderr.log');
    let logFd = 'ignore';
    try {
      logFd = fs.openSync(chromeLogPath, 'w');
    } catch {
      logFd = 'ignore';
    }
    try {
      child = spawn(browserPath, args, { stdio: ['ignore', 'ignore', logFd], windowsHide: true });
    } finally {
      // 父进程必须马上关掉自己的副本，否则 Windows 上删除临时目录会被占用挡住
      if (typeof logFd === 'number') {
        try {
          fs.closeSync(logFd);
        } catch {
          /* ignore */
        }
      }
    }

    const getStderr = () => readTail(chromeLogPath);
    const { port: devtoolsPort, info } = await resolveDevTools(userDataDir, port, child, getStderr);

    // ② 连浏览器级 WebSocket，再 Target.createTarget + attach（flatten:true）
    //    这样每条页面级命令都要带 sessionId —— 多页面/多会话也不会串线。
    cdp = new CdpClient(info.webSocketDebuggerUrl);
    await cdp.connect();

    // 注意：Target.createTarget 不接受 width/height（Chrome 会报
    // "Target position can only be set for new windows"）；视口一律靠
    // 下面的 Emulation.setDeviceMetricsOverride 设。
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    if (!sessionId) throw new Error('Target.attachToTarget 没有返回 sessionId');

    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    if (info.Browser) console.error(`[info] 浏览器: ${info.Browser} (DevTools 端口 ${devtoolsPort})`);

    for (let i = 0; i < config.shots.length; i++) {
      const shot = config.shots[i] || {};
      const name = shot.name || `shot-${String(i + 1).padStart(2, '0')}`;
      const url = shot.url || config.base;
      if (!url) throw new Error(`shot "${name}" 既没有 url，配置里也没有 base`);

      const w = Number(shot.width) || width;
      const h = Number(shot.height) || height;
      const dsf = Number(shot.deviceScaleFactor) || Number(config.deviceScaleFactor) || DEFAULTS.deviceScaleFactor;

      // 视口要在导航前设好，否则页面会先按旧尺寸布局再重排
      await cdp.send(
        'Emulation.setDeviceMetricsOverride',
        { width: w, height: h, deviceScaleFactor: dsf, mobile: false },
        sessionId,
      );

      if (auth) {
        // ③ 「先落令牌再重载」的关键：
        //    localStorage 是按"源(origin)"隔离的，必须先真的把页面导航到目标源上，
        //    才写得到它名下的 localStorage；写完再导航一次，App 启动时就已经带着令牌了。
        //    令牌按**裸字符串**存（`src/auth.js` 的 getToken 直接读原值，没有 JSON.parse），
        //    这里两层 JSON.stringify 只是把 token 安全地嵌进要执行的 JS 表达式里。
        const seedUrl = config.base || new URL(url).origin + '/';
        await navigate(cdp, sessionId, seedUrl);

        const stored = JSON.stringify(token); // 生成 `"raw-token"` 这个 JS 字面量
        const res = await evaluate(
          cdp,
          sessionId,
          `localStorage.setItem(${JSON.stringify(tokenKey)}, ${stored})`,
        );
        if (res.exceptionDetails) {
          const d = res.exceptionDetails.exception?.description || res.exceptionDetails.text || 'unknown';
          throw new Error(
            `shot "${name}" 写入 localStorage 失败（${seedUrl}）: ${String(d).split('\n')[0]}`,
          );
        }

        const back = await evaluate(cdp, sessionId, `localStorage.getItem(${JSON.stringify(tokenKey)})`);
        if (back?.result?.value !== token) {
          throw new Error(
            `shot "${name}" localStorage 回读校验不通过（${seedUrl}，key=${tokenKey}）: ` +
              `期望 ${JSON.stringify(token).slice(0, 40)}... 实际 ${String(back?.result?.value).slice(0, 40)}...`,
          );
        }
      }

      // ④ 每个 shot 一次全新导航 → 执行 steps → 截图
      await navigate(cdp, sessionId, url);
      await runSteps(cdp, sessionId, name, shot.steps);

      const { data } = await cdp.send(
        'Page.captureScreenshot',
        { format: 'png', captureBeyondViewport: false, fromSurface: true },
        sessionId,
      );
      if (!data) throw new Error(`shot "${name}" 截图返回空数据`);

      const buf = Buffer.from(data, 'base64');
      if (buf.length === 0) throw new Error(`shot "${name}" 截图字节数为 0`);

      fs.writeFileSync(path.join(outDir, `${name}.png`), buf);
      console.log(`saved ${name}.png ${w}x${h}`);
    }
  } finally {
    // ⑤ 无论成败：关连接、杀进程树、删临时 profile
    cdp?.close();
    killProcessTree(child);
    await sleep(150);
    removeDirWithRetry(userDataDir);
  }
}

run().then(
  () => process.exit(0),
  (err) => {
    console.error(`shoot 失败: ${err?.message || err}`);
    process.exit(1);
  },
);
