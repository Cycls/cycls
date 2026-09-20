// Injected into every app, so an app calls `cycls.get`/`set`/`read`/`write`
// instead of hand-rolling postMessage. `get`/`set` are the workspace's shelf in
// the object store, one row per key; `cycls.me` is the viewer's own and
// `cycls.users` is everyone's, which the server allows admins only.

const SHIM = `<script>(function(){
  // A sandboxed frame has an opaque origin, so even READING window.localStorage
  // throws SecurityError. That kills any app — or any library inside one — that
  // touches it during render, which is most of them. Swap in an in-memory store
  // so it degrades to "forgets on reload" instead of a blank page. Anything that
  // must survive a reload belongs in cycls.get/set, which is shared anyway.
  try { window.localStorage.getItem("probe"); } catch (e) {
    var mem = {};
    var store = {
      getItem: function(k){ return Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null; },
      setItem: function(k, v){ mem[k] = String(v); },
      removeItem: function(k){ delete mem[k]; },
      clear: function(){ mem = {}; },
      key: function(i){ var ks = Object.keys(mem); return i < ks.length ? ks[i] : null; }
    };
    Object.defineProperty(store, "length", { get: function(){ return Object.keys(mem).length; } });
    try {
      Object.defineProperty(window, "localStorage", { value: store, configurable: true });
      Object.defineProperty(window, "sessionStorage", { value: store, configurable: true });
    } catch (e2) {}
  }

  var seq = 0, waiting = new Map(), ctx = null, resolveReady, tries = 0, link = null;
  var ready = new Promise(function(r){ resolveReady = r; });

  function send(msg){ if (link) link.postMessage(msg); else parent.postMessage(msg, '*'); }

  function call(type, payload){
    return new Promise(function(res, rej){
      var id = ++seq;
      waiting.set(id, { res: res, rej: rej });
      send(Object.assign({ type: type, id: id }, payload));
    });
  }

  function receive(m){
    m = m || {};
    if (m.type === 'cycls:init' && !ctx) {
      ctx = { path: m.path, scope: m.scope, theme: m.theme, locale: m.locale, canWrite: !!m.canWrite };
      api.ctx = ctx;
      resolveReady(ctx);
      return;
    }
    if (m.type !== 'cycls:read:result' && m.type !== 'cycls:write:result'
        && m.type !== 'cycls:save:result' && m.type !== 'cycls:fetch:result'
        && m.type !== 'cycls:data:result') return;
    var p = waiting.get(m.id);
    if (!p) return;
    waiting.delete(m.id);
    if (!m.ok) { var err = new Error(m.error || 'failed'); err.status = m.status; return p.rej(err); }
    p.res(m.type === 'cycls:data:result' ? m.result
        : m.type === 'cycls:read:result' ? m.content
        : m.type === 'cycls:save:result' ? m.path
        : m.type === 'cycls:fetch:result' ? { status: m.status, body: m.body, contentType: m.contentType }
        : undefined);
  }

  addEventListener('message', function(e){
    // The host hands over a private port with init; after that nothing rides the window,
    // so a document that replaces this one inherits no channel. A host that sends no port
    // keeps working on the window alone.
    if (!link && e.ports && e.ports[0]) {
      link = e.ports[0];
      link.onmessage = function(ev){ receive(ev.data); };
    }
    receive(e.data);
  });

  // A throwing app used to be a blank frame with nothing anywhere.
  function report(m){ try { send({ type: 'cycls:loaderror', message: String(m).slice(0, 500) }); } catch (e) {} }
  addEventListener('error', function(e){ report(e.message || 'script error'); });
  addEventListener('unhandledrejection', function(e){
    report((e.reason && e.reason.message) || e.reason || 'unhandled rejection');
  });

  // Retry the handshake: the host's listener usually mounts first, but nothing
  // guarantees it.
  (function announce(){
    if (ctx || tries++ > 40) return;
    parent.postMessage({ type: 'cycls:ready' }, '*');
    setTimeout(announce, 50);
  })();

  function resolve(p){
    if (typeof p !== 'string' || !p) throw new Error('path required');
    if (p.indexOf(ctx.scope + '/') === 0) return p;
    return ctx.scope ? ctx.scope + '/' + p : p;
  }
  async function read(p){ await ready; return call('cycls:read', { path: resolve(p) }); }
  async function write(p, content){
    await ready;
    return call('cycls:write', { path: resolve(p), content: String(content) });
  }

  async function data(op){ await ready; return call('cycls:data', op); }

  // One shelf, one audience. The server re-derives it: the viewer comes from
  // the session and the role from the workspace, so who is a hint, not a claim.
  function shelf(who){
    return {
      get: async function(key, fallback){
        var r = await data({ op: 'get', key: String(key), who: who });
        return r ? r.value : fallback;
      },
      set: function(key, value){ return data({ op: 'put', key: String(key), value: value, who: who }); },
      remove: function(key){ return data({ op: 'delete', key: String(key), who: who }); },
      all: function(prefix){ return data({ op: 'list', prefix: prefix || '', who: who }); }
    };
  }

  var kv = null, loading = null, timer = null, pending = null, settle = null, dirty = new Set(), clipped = false;

  // Concurrent callers share one list, or a later one would clobber the
  // mutations an earlier set() already made.
  function load(){
    if (kv) return Promise.resolve(kv);
    if (!loading) loading = (async function(){
      var next = {};
      try {
        var page = await data({ op: 'list' }) || {};
        (page.rows || []).forEach(function(r){ next[r.key] = r.value; });
        clipped = !!page.truncated;
      } catch (e) {}
      kv = next;
      loading = null;
      return kv;
    })();
    return loading;
  }

  function schedule(){
    if (!pending) {
      pending = new Promise(function(res, rej){ settle = { res: res, rej: rej }; });
      pending.catch(function(){});   // a set() nobody awaits must not warn
    }
    clearTimeout(timer);
    timer = setTimeout(flush, 250);
    return pending;
  }

  // One row per key, so a burst of set()s costs one write each and two writers
  // only collide on the same key — the whole-file rewrite this replaced lost
  // everything another tab or the agent had changed.
  async function flush(){
    clearTimeout(timer);
    if (!pending) return;
    var s = settle, mine = dirty;
    pending = null; settle = null; dirty = new Set();
    try {
      await Promise.all(Array.from(mine).map(function(k){
        return Object.prototype.hasOwnProperty.call(kv, k)
          ? data({ op: 'put', key: k, value: kv[k] })
          : data({ op: 'delete', key: k });
      }));
      s.res();
    } catch (e) { s.rej(e); }
  }

  addEventListener('pagehide', function(){ flush(); });

  var api = {
    ctx: null,
    ready: ready,
    read: read,
    write: write,
    // Puts a file anywhere in the workspace, but only ever where the person
    // picks in the host's dialog. Resolves to the chosen path; rejects with
    // 'cancelled' if they dismiss it.
    save: async function(name, content){
      await ready;
      return call('cycls:save', { name: name, content: String(content) });
    },
    get: async function(key, fallback){
      var s = await load();
      if (Object.prototype.hasOwnProperty.call(s, key)) return s[key];
      // The shelf did not fit in one page, so "absent" here is not an answer.
      if (clipped) throw new Error('cycls.get: this app has too many keys to load at once — use cycls.me.all(prefix) or keep fewer');
      return fallback;
    },
    set: async function(key, value){
      var s = await load();
      if (value === undefined) delete s[key]; else s[key] = value;
      dirty.add(key);
      return schedule();
    },
    // Read-modify-write that does not lose a concurrent one: the write carries
    // the version it read, and a 412 means someone got there first, so re-read
    // and re-apply rather than overwrite them.
    update: async function(key, fn){
      for (var i = 0; i < 5; i++) {
        var cur = await data({ op: 'get', key: String(key) });
        var next = await fn(cur ? cur.value : undefined);
        try {
          await data({ op: 'put', key: String(key), value: next, version: cur ? cur.version : '' });
          if (kv) kv[key] = next;
          return next;
        } catch (e) {
          if (e.status !== 412) throw e;
        }
      }
      throw new Error('cycls.update: gave up after 5 tries on ' + key);
    },
    // A connector's own API, live. The app never holds a token: the host resolves the
    // workspace's grant per call, so a refreshed one is inherited with no change here.
    connector: function(name){
      return {
        fetch: async function(path, init){
          await ready;
          init = init || {};
          return call('cycls:fetch', { name: String(name), path: String(path),
                                       method: init.method || 'GET', headers: init.headers || {},
                                       body: init.body === undefined ? undefined : String(init.body) });
        },
        json: async function(path, init){
          var r = await api.connector(name).fetch(path, init);
          if (r.status >= 400) throw new Error(name + ' ' + r.status + ': ' + String(r.body).slice(0, 200));
          return JSON.parse(r.body || 'null');
        }
      };
    },
    all: async function(){ return Object.assign({}, await load()); },
    // This viewer's own rows — nobody else's, and no id to get wrong.
    me: shelf('me'),
    // Every member's, for an admin. It rejects for anyone else, which is both the
    // boundary and how an app tells which of the two views to render.
    users: {
      all: function(prefix){ return data({ op: 'list', prefix: prefix || '', who: 'all' }); },
      get: async function(user, key){
        var r = await data({ op: 'get', key: String(key), who: String(user) });
        return r ? r.value : undefined;
      },
      set: function(user, key, value){
        return data({ op: 'put', key: String(key), value: value, who: String(user) });
      },
      remove: function(user, key){ return data({ op: 'delete', key: String(key), who: String(user) }); }
    },
    keys: async function(){ return Object.keys(await load()); },
    flush: flush,
    resize: function(h){ parent.postMessage({ type: 'cycls:resize', height: h }, '*'); }
  };
  window.cycls = api;
})();<\/script>`;

export function injectShim(html: string): string {
  const head = /<head[^>]*>/i.exec(html);
  if (head) return html.slice(0, head.index + head[0].length) + SHIM + html.slice(head.index + head[0].length);
  const htmlTag = /<html[^>]*>/i.exec(html);
  if (htmlTag) {
    return html.slice(0, htmlTag.index + htmlTag[0].length) + SHIM + html.slice(htmlTag.index + htmlTag[0].length);
  }
  return SHIM + html;
}
