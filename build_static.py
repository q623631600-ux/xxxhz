"""
静态演示站点生成器
====================
把「讲书工作流 Web 工作台」渲染成纯静态 HTML（无后端、无 API、无成本）。
用法：python build_static.py
输出：site/ 目录（可直接部署到 Vercel / GitHub Pages / 任意静态托管）
"""
import os
import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

BASE = Path(__file__).parent
TEMPLATES = BASE / "web" / "templates"
STATIC = BASE / "web" / "static"
OUT = BASE / "site"

jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES)))

# 复用真实数据加载器（读取 output/ 目录）
from services.web_project_loader import loader  # noqa: E402


def render(name: str, **kw) -> str:
    return jinja_env.get_template(name).render(**kw)


def rewrite(html: str) -> str:
    """把服务端路由链接改写为静态 .html 文件链接"""
    # 静态资源
    html = html.replace('src="/static/', 'src="static/')
    html = html.replace('href="/static/', 'href="static/')
    # 知识点详情 /project/{book}/kp/{id}
    html = re.sub(r'href="/project/([^/"]+)/kp/(\d+)"', r'href="kp-\1-\2.html"', html)
    # 项目页 /project/{book}
    html = re.sub(r'href="/project/([^/"]+)"', r'href="project-\1.html"', html)
    # 工作台 /work?...  -> work.html
    html = re.sub(r'href="/work(?:\?[^"]*)?"', 'href="work.html"', html)
    # 简单页面
    html = html.replace('href="/dashboard"', 'href="dashboard.html"')
    html = html.replace('href="/growth"', 'href="growth.html"')
    html = html.replace('href="/feedback"', 'href="feedback.html"')
    # 根路径
    html = html.replace('href="/"', 'href="index.html"')
    return html


def write(path: Path, html: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


# 静态演示版的 JS 存根：拦截对后端的 API 请求，给出友好提示
DEMO_JS = """/* 静态演示版（无后端）— 拦截 API 请求并提示 */
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
"""


def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "static").mkdir(parents=True, exist_ok=True)

    books = loader.list_books()
    html_count = 0

    # 1) 首页（项目列表）
    write(OUT / "index.html", rewrite(render("index.html", books=books, has_output=True)))
    html_count += 1

    # 2) 每本书的项目页 + 每个知识点详情页
    for b in books:
        name = b["name"]
        summary = loader.book_summary(name)
        write(OUT / f"project-{name}.html",
              rewrite(render("project.html", summary=summary, book_name=name)))
        html_count += 1
        for kp in summary.get("kps", []):
            detail = loader.kp_detail(name, kp["kp_id"])
            if "error" in detail:
                continue
            write(OUT / f"kp-{name}-{kp['kp_id']}.html",
                  rewrite(render("kp_detail.html", detail=detail, book_name=name, kp_id=kp["kp_id"])))
            html_count += 1

    # 3) 工作台（默认新任务视图）
    write(OUT / "work.html",
          rewrite(render("pipeline.html", book_name="__new__", kp_id=0,
                         initial_status={}, file_previews={}, all_kps=[])))
    html_count += 1

    # 4) 数据分析 / 5) Agent 学习 / 6) 反馈中心
    from agent import BookGrowthAgent  # noqa: E402
    agent = BookGrowthAgent()
    review = agent.review()
    write(OUT / "dashboard.html",
          rewrite(render("dashboard.html", review=review,
                         has_memory=bool(review.get("total_produced", 0) > 0))))
    html_count += 1
    write(OUT / "growth.html", rewrite(render("growth.html", data=agent.growth_summary())))
    html_count += 1
    write(OUT / "feedback.html", rewrite(render("feedback.html")))
    html_count += 1

    # 静态资源
    shutil.copy(STATIC / "style.css", OUT / "static" / "style.css")
    (OUT / "static" / "app.js").write_text(DEMO_JS, encoding="utf-8")

    print(f"✅ 完成：生成 {html_count} 个 HTML 页面 → {OUT}")


if __name__ == "__main__":
    build()
