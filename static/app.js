/* 静态演示版（无后端）— 拦截 API 请求并提示 */
(function () {
  var toast = null;
  function show(msg) {
    if (toast) toast.remove();
    toast = document.createElement('div');
    toast.textContent = msg;
    toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1a1d24;color:#e6e6e6;border:1px solid #333844;padding:10px 18px;border-radius:10px;font-size:13px;z-index:9999;box-shadow:0 8px 24px rgba(0,0,0,.4);';
    document.body.appendChild(toast);
    setTimeout(function () { toast.remove(); toast = null; }, 2600);
  }
  var _fetch = window.fetch;
  window.fetch = function (url, opts) {
    if (typeof url === 'string' && url.indexOf('/api/') !== -1) {
      show('🧪 静态演示版 · 此操作需要后端服务');
      return Promise.reject(new Error('demo mode'));
    }
    return _fetch.apply(this, arguments);
  };
})();
