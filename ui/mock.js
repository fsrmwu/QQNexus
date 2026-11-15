(() => {
  // Electron 环境：preload 已注入真实 ipcRenderer，假数据绝不覆盖
  if (window.ipcRenderer && typeof window.ipcRenderer.invoke === 'function') return;
  const state = {
    ports: { webui: 5099, ws: 3001, live: [5099, 3001] },
    status: {
      snowluma: true, astrbot: true,
      dataDir: 'C:\\Users\\浮生若梦\\AppData\\Local\\QQNexus\\data',
      hasProvider: false, hasKey: false, model: null, apiBase: null,
      events: [
        { id: 7, tone: 'ok',   text: '插件已加载', detail: '12 个', who: 'AB', ts: '2026-11-13T20:14:19.210Z', count: 1 },
        { id: 6, tone: 'ok',   text: '桥接已连通', detail: '',      who: 'AB', ts: '2026-11-13T20:14:18.905Z', count: 2 },
        { id: 5, tone: 'ok',   text: '面板已就绪', detail: '',      who: 'SL', ts: '2026-11-13T20:14:12.001Z', count: 1 },
        { id: 4, tone: 'ok',   text: '端口探测完成', detail: '',    who: 'boot', ts: '2026-11-13T20:14:11.402Z', count: 1 },
        { id: 3, tone: 'ok',   text: '凭证已同步', detail: '两端一致', who: 'boot', ts: '2026-11-13T20:14:11.418Z', count: 1 },
        { id: 2, tone: 'ok',   text: '进程已启动', detail: 'pid 9132', who: 'AB', ts: '2026-11-13T20:14:02.180Z', count: 1 },
        { id: 1, tone: 'warn', text: '配置已写入', detail: '',      who: 'boot', ts: '2026-11-13T20:14:02.113Z', count: 1 },
      ],
      log: [
        '[2026-11-13T20:14:02.113Z] [boot] configs written',
        '[2026-11-13T20:14:02.121Z] [SL] spawned pid=8420',
        '[2026-11-13T20:14:02.180Z] [AB] spawned pid=9132',
        '[2026-11-13T20:14:11.402Z] [boot] ports {"webui":5099,"ws":3001,"live":[5099,3001]}',
        '[2026-11-13T20:14:11.418Z] [boot] token ok, ws=3001',
        '[2026-11-13T20:14:12.001Z] [SL] WebUI ready on http://127.0.0.1:5099',
        '[2026-11-13T20:14:18.772Z] [AB] [OneBot.WS-Client] [astrbot] connected ws://127.0.0.1:3001/ws',
        '[2026-11-13T20:14:18.905Z] [AB] aiocqhttp(OneBot v11) 适配器已连接。',
        '[2026-11-13T20:14:19.210Z] [AB] 已加载插件 12 个'
      ].join('\n')
    }
  };
  window.ipcRenderer = {
    invoke: async (ch, ...a) => {
      if (ch === 'ports') return state.ports;
      if (ch === 'status') return state.status;
      if (ch === 'is-first-run') return false;
      if (ch === 'fetch-models') return { ok: true, source: 'api', msg: '拉取到 9 个模型',
        models: ['deepseek-chat','deepseek-reasoner','gpt-4o-mini','gpt-4o','moonshot-v1-8k',
                 'qwen-plus','qwen-max','glm-4-plus','text-embedding-3-small'] };
      if (ch === 'test-provider') return { ok: true, msg: 'HTTP 200' };
      if (ch === 'save-provider') { state.status.hasProvider = true; state.status.hasKey = true; state.status.model = a[0].model; return { ok: true, msg: '已保存，正在重载' }; }
      if (ch === 'probe-health') {
        const ts = (a[0] && a[0].targets) || [];
        return { at: Date.now(), results: ts.map((t,i) => ({key:t.key,name:t.name,port:t.port,
          ok:true,status:200,ms:[18,42][i]||25,timeout:false})) };
      }
      if (ch === 'save-file') return { ok: true, path: 'C:/Users/浮生若梦/Downloads/' + (a[0] && a[0].name) };
      if (ch === 'pick-file') return { ok: false, canceled: true };
      if (ch === 'get-token-stats') return {
        input: 23000, cached: 4000, output: 7700, total: 34700, calls: 3, model_count: 2,
        by_model: [ {model:'deepseek-chat', total:30800, calls:2},
                    {model:'gpt-4o-mini', total:3900, calls:1} ]
      };
      if (ch === 'pick-image') return { ok:false, canceled:true };
      if (ch === 'get-stats') return {
        total: 1284, group_total: 967, private_total: 317, sessions: 9,
        updated_at: Math.floor(Date.now()/1000),
        groups: { '725839104': {count: 512, last_seen: Math.floor(Date.now()/1000)-120, name: 'Neon Blade 开发群'},
                  '611203846': {count: 288, last_seen: Math.floor(Date.now()/1000)-600, name: 'AI 折腾交流'},
                  '902114573': {count: 167, last_seen: Math.floor(Date.now()/1000)-3600, name: '游戏引擎研究'} },
        privates: { '10086': {count: 141, last_seen: Math.floor(Date.now()/1000)-60},
                    '10010': {count: 92, last_seen: Math.floor(Date.now()/1000)-7200},
                    '10000': {count: 84, last_seen: Math.floor(Date.now()/1000)-20000} }
      };
      if (ch === 'get-credentials') return {
        astrbot_user: 'astrbot',
        astrbot_password: 'QnA9-Xk7mP2vLq8RtN4wZa',
        snowluma_password: 'QnS9-Hj3cB6yFd1KeM5pTg',
        onebot_token: 'Vb8nQ2xW7rT4yU6iO0pA3sD5fG1hJ9kL'
      };
      if (ch === 'open-if') return { ok: false, msg: '端口未开启（预览模式）' };
      return null;
    },
    on: () => {}
  };
})();
