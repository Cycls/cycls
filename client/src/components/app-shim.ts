// Injected into every app, so an app calls `cycls.get`/`set`/`read`/`write`
// instead of hand-rolling postMessage. The key-value store is one JSON file in
// the app's folder; `set` mutates memory and coalesces writes, so a burst of
// updates costs one PUT rather than one each.

export const STATE_FILE = "state.json";

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

  var seq = 0, waiting = new Map(), ctx = null, resolveReady, tries = 0;
  var ready = new Promise(function(r){ resolveReady = r; });

  function call(type, payload){
    return new Promise(function(res, rej){
      var id = ++seq;
      waiting.set(id, { res: res, rej: rej });
      parent.postMessage(Object.assign({ type: type, id: id }, payload), '*');
    });
  }

  addEventListener('message', function(e){
    var m = e.data || {};
    if (m.type === 'cycls:init' && !ctx) {
      ctx = { path: m.path, scope: m.scope, theme: m.theme, locale: m.locale, canWrite: !!m.canWrite };
      api.ctx = ctx;
      resolveReady(ctx);
      return;
    }
    if (m.type !== 'cycls:read:result' && m.type !== 'cycls:write:result'
        && m.type !== 'cycls:save:result') return;
    var p = waiting.get(m.id);
    if (!p) return;
    waiting.delete(m.id);
    if (!m.ok) return p.rej(new Error(m.error || 'failed'));
    p.res(m.type === 'cycls:read:result' ? m.content
        : m.type === 'cycls:save:result' ? m.path : undefined);
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

  var kv = null, loading = null, timer = null, pending = null, settle = null;

  // Concurrent callers share one fetch, or a later parse would clobber the
  // mutations an earlier set() already made.
  function load(){
    if (kv) return Promise.resolve(kv);
    if (!loading) loading = (async function(){
      try {
        var parsed = JSON.parse(await read(${JSON.stringify(STATE_FILE)}));
        kv = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
      } catch (e) { kv = {}; }
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

  async function flush(){
    clearTimeout(timer);
    if (!pending) return;
    var s = settle;
    pending = null; settle = null;
    try { await write(${JSON.stringify(STATE_FILE)}, JSON.stringify(kv)); s.res(); }
    catch (e) { s.rej(e); }
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
      return Object.prototype.hasOwnProperty.call(s, key) ? s[key] : fallback;
    },
    set: async function(key, value){
      var s = await load();
      if (value === undefined) delete s[key]; else s[key] = value;
      return schedule();
    },
    all: async function(){ return Object.assign({}, await load()); },
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
