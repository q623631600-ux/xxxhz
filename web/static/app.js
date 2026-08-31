function startNewBook() {
    var input = document.getElementById("new-book-input");
    if (!input) return;
    var name = input.value.trim();
    if (!name) { alert("请输入书名"); return; }
    window.location.href = "/work?book=" + encodeURIComponent(name);
}

function esc(text) { if (!text) return ""; var d = document.createElement("div"); d.textContent = text; return d.innerHTML; }

function selectKp(b, k) { var bookName = _safeDecodeURI(b); window.location.href = "/work?book=" + encodeURIComponent(bookName) + "&kp_id=" + k; }

var STEP_ROUTES = {
    plan_book: function(b) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/plan"; },
    generate_hooks: function(b, k) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/hooks/" + k; },
    generate_script: function(b, k) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/script/" + k; },
    content_units: function(b, k) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/content-units/" + k; },
    visual_beats: function(b, k) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/visual-beats/" + k; },
    image_prompts: function(b, k) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/image-prompts/" + k; },
    generate_images: function(b, k) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/generate-images/" + k; },
    generate_audio: function(b, k) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/generate-audio/" + k; },
    timeline_assembly: function(b, k) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/timeline-assembly/" + k; },
    generate_subtitles: function(b, k) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/generate-subtitles/" + k; },
    compose_final_video: function(b, k) { return "/api/pipeline/" + encodeURIComponent(b) + "/run/compose-final-video/" + k; },
};

// ================================================================
// 钩子（Hook）功能
// ================================================================

function getCurrentBook() {
    var u = new URLSearchParams(window.location.search);
    return (typeof _safeDecodeURI !== 'undefined') ? _safeDecodeURI(u.get('book') || '') : (u.get('book') || '');
}

function getCurrentKpId() {
    return parseInt(new URLSearchParams(window.location.search).get('kp_id') || '0');
}

function generateHooks() {
    var bookName = getCurrentBook();
    var kpId = getCurrentKpId();
    if (!bookName || bookName === '__new__' || !kpId || kpId <= 0) {
        showHookError('请先选择一个知识点');
        return;
    }
    var btn = document.getElementById('btn-generate-hooks');
    var status = document.getElementById('hook-status');
    var errEl = document.getElementById('hook-error');
    if (errEl) errEl.style.display = 'none';
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 生成中...'; }
    if (status) status.textContent = '⏳ 正在调用 AI 生成 10 条候选钩子...';

    fetch('/api/pipeline/' + encodeURIComponent(bookName) + '/run/hooks/' + kpId, { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(j) {
            if (btn) { btn.disabled = false; btn.textContent = '🎣 重新生成'; }
            if (j.success) {
                if (status) status.textContent = '';
                loadHooks();
            } else {
                showHookError(j.error || '生成失败');
            }
        })
        .catch(function(e) {
            if (btn) { btn.disabled = false; btn.textContent = '🎣 生成钩子'; }
            showHookError('请求失败: ' + e.message);
        });
}

function showHookError(msg) {
    var errEl = document.getElementById('hook-error');
    var status = document.getElementById('hook-status');
    if (errEl) { errEl.textContent = '❌ ' + msg; errEl.style.display = 'inline'; }
    if (status) status.textContent = '❌ ' + msg;
}

function loadHooks() {
    var bookName = getCurrentBook();
    var kpId = getCurrentKpId();
    if (!bookName || bookName === '__new__' || !kpId || kpId <= 0) return;

    var container = document.getElementById('hook-candidates');
    var grid = document.getElementById('hook-grid');
    var status = document.getElementById('hook-status');
    var badge = document.getElementById('hook-selected-badge');
    var preview = document.getElementById('hook-preview');
    var autoBtn = document.getElementById('btn-auto-select');
    var errEl = document.getElementById('hook-error');
    if (errEl) errEl.style.display = 'none';

    fetch('/api/pipeline/' + encodeURIComponent(bookName) + '/hooks/' + kpId)
        .then(function(r) { return r.json(); })
        .then(function(j) {
            if (!j.success || !j.data || !j.data.candidates || j.data.candidates.length === 0) {
                if (status) status.textContent = '暂无候选钩子，点击「生成钩子」量产 10 条';
                if (container) container.style.display = 'none';
                if (autoBtn) autoBtn.style.display = 'none';
                return;
            }
            if (status) status.textContent = '';
            if (container) container.style.display = 'block';

            var hooks = j.data.candidates;
            var primaryIdx = j.data.primary_index;
            var hasSelected = j.data.has_selected;

            // 渲染钩子卡片
            var html = '';
            for (var i = 0; i < hooks.length; i++) {
                var isSelected = (primaryIdx === i);
                html += '<div class="hook-card' + (isSelected ? ' hook-card-selected' : '') + '" onclick="selectHook(' + i + ')" data-index="' + i + '">';
                html += '<div class="hook-card-num">#' + (i + 1) + '</div>';
                html += '<div class="hook-card-text">' + esc(hooks[i]) + '</div>';
                html += '<div class="hook-card-check">' + (isSelected ? '✓' : '') + '</div>';
                html += '</div>';
            }
            if (grid) grid.innerHTML = html;

            // 更新选定状态
            if (hasSelected && primaryIdx !== null && primaryIdx !== undefined) {
                if (badge) { badge.style.display = 'inline-block'; badge.textContent = '✓ 已选 #' + (primaryIdx + 1); }
                if (preview) preview.textContent = '当前开场：' + hooks[primaryIdx];
                if (autoBtn) autoBtn.style.display = 'none';
            } else {
                if (badge) badge.style.display = 'none';
                if (preview) preview.textContent = '点击卡片选定主钩子';
                if (autoBtn) autoBtn.style.display = 'inline-block';
            }
        })
        .catch(function(e) {
            if (status) status.textContent = '加载失败: ' + e.message;
        });
}

function selectHook(hookIndex) {
    var bookName = getCurrentBook();
    var kpId = getCurrentKpId();
    fetch('/api/pipeline/' + encodeURIComponent(bookName) + '/hooks/' + kpId + '/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hook_index: hookIndex }),
    })
        .then(function(r) { return r.json(); })
        .then(function(j) {
            if (j.success) {
                loadHooks();
            } else {
                showHookError(j.error || '选定失败');
            }
        })
        .catch(function(e) {
            showHookError('请求失败: ' + e.message);
        });
}

function autoSelectHook() {
    var bookName = getCurrentBook();
    var kpId = getCurrentKpId();
    var autoBtn = document.getElementById('btn-auto-select');
    var errEl = document.getElementById('hook-error');
    if (errEl) errEl.style.display = 'none';
    if (autoBtn) { autoBtn.disabled = true; autoBtn.textContent = '⏳ 评分中...'; }

    fetch('/api/pipeline/' + encodeURIComponent(bookName) + '/hooks/' + kpId + '/auto-select', {
        method: 'POST'
    })
        .then(function(r) { return r.json(); })
        .then(function(j) {
            if (autoBtn) { autoBtn.disabled = false; autoBtn.textContent = '🤖 AI 自动选最佳'; }
            if (j.success) {
                loadHooks();
            } else {
                showHookError(j.error || '自动选择失败');
            }
        })
        .catch(function(e) {
            if (autoBtn) { autoBtn.disabled = false; autoBtn.textContent = '🤖 AI 自动选最佳'; }
            showHookError('请求失败: ' + e.message);
        });
}

// ================================================================
// 增长信号指示器
// ================================================================

function loadGrowthSignals() {
    fetch('/api/growth/signals')
        .then(function(r) { return r.json(); })
        .then(function(j) {
            var badge = document.getElementById('growth-badge');
            var text = document.getElementById('growth-text');
            if (!j.success || !j.data || !j.data.has_signals) {
                if (badge) badge.style.display = 'none';
                if (text) text.textContent = '无历史数据 — 选题使用默认策略';
                return;
            }
            var d = j.data;
            if (badge) {
                badge.style.display = 'inline';
                badge.textContent = '📈 增长模式';
                badge.style.cssText = 'padding:0.15rem 0.5rem;border-radius:999px;background:color-mix(in srgb, var(--brand) 15%, transparent);color:var(--brand);font-weight:600;font-size:0.7rem;';
            }
            var parts = [];
            if (d.total_videos_analyzed) parts.push(d.total_videos_analyzed + '条视频分析');
            if (d.best_structure) parts.push('最佳结构: ' + d.best_structure);
            if (d.best_opening) parts.push('最佳开场: ' + d.best_opening);
            if (text) text.textContent = parts.join(' · ');
        })
        .catch(function() {
            var text = document.getElementById('growth-text');
            if (text) text.textContent = '';
        });
}

// 页面加载时自动加载钩子和增长信号
document.addEventListener('DOMContentLoaded', function() {
    loadGrowthSignals();
    setTimeout(function() {
        var bookName = getCurrentBook();
        var kpId = getCurrentKpId();
        if (bookName && bookName !== '__new__' && kpId > 0) {
            loadHooks();
        }
    }, 500);
});

// ---- 步骤实时进度轮询 ----
var _stepPollTimers = {};

function startStepPoll(bookName, kpId, stepId) {
    stopStepPoll(stepId);
    var pe = document.getElementById("progress-" + stepId);
    var pt = document.getElementById("progress-text-" + stepId);
    var startTime = Date.now();
    _stepPollTimers[stepId] = setInterval(function() {
        var elapsed = Math.floor((Date.now() - startTime) / 1000);
        var elStr = Math.floor(elapsed / 60) + "分" + (elapsed % 60) + "秒";

        fetch("/api/pipeline/" + encodeURIComponent(bookName) + "/step-progress/" + kpId)
            .then(function(r){ return r.json(); })
            .then(function(j) {
                if (!j.success) return;
                var steps = j.data || {};
                var p = steps[stepId];
                if (p) {
                    if (pe) { pe.style.width = p.progress + "%"; pe.style.display = "block"; }
                    if (pt) pt.textContent = p.message + " (" + elStr + ")";
                    if (p.progress >= 100) stopStepPoll(stepId);
                } else if (pt) {
                    pt.textContent = "执行中... (" + elStr + ")";
                }
            })
            .catch(function(){});
    }, 2000);
}

function stopStepPoll(stepId) {
    if (_stepPollTimers[stepId]) {
        clearInterval(_stepPollTimers[stepId]);
        delete _stepPollTimers[stepId];
    }
}

async function runStep(bookName, kpId, stepId) {
    var route = STEP_ROUTES[stepId];
    if (!route) return;
    var url = route(bookName, kpId);
    var se = document.getElementById("status-" + stepId);
    var oe = document.getElementById("output-" + stepId);
    var ee = document.getElementById("error-" + stepId);
    var be = document.getElementById("btn-" + stepId);
    var pe = document.getElementById("progress-" + stepId);
    var pt = document.getElementById("progress-text-" + stepId);
    if (se) { se.className = "step-status status-running"; se.textContent = "执行中..."; }
    if (be) be.disabled = true;
    if (oe) oe.style.display = "none";
    if (ee) ee.style.display = "none";
    if (pe) { pe.style.width = "5%"; pe.style.display = "block"; }
    if (pt) { pt.style.display = "block"; pt.textContent = "正在启动..."; }

    startStepPoll(bookName, kpId, stepId);

    try {
        var resp = await fetch(url, { method: "POST" });
        var data = await resp.json();
        stopStepPoll(stepId);
        if (pe && data.success) { pe.style.width = "100%"; }
        if (pt && data.success) { pt.textContent = "完成"; }
        if (data.success) {
            if (se) { se.className = "step-status status-completed"; se.textContent = "完成"; }
            if (be) { be.textContent = "重新运行"; be.className = "btn btn-outline"; be.disabled = false; }
            if (oe) {
                var extraLink = "";
                if (stepId === "compose_final_video") {
                    extraLink = " <a href='/api/project/" + encodeURIComponent(bookName) + "/kp/" + kpId + "/video/final' class='btn btn-sm' style='background:var(--primary);color:var(--primary-foreground);text-decoration:none;border-radius:0.5rem;padding:0.3rem 0.8rem;font-weight:600;' download>⬇ 下载视频</a>";
                }
                oe.style.display = "block";
                var detailHtml = "";
                if (stepId === "timeline_assembly" && data.beats) {
                    detailHtml = " 🎬 " + data.beats + "个画面 · " + data.audio_segs + "段音频 · " + (data.total_duration || "") + "";
                }
                oe.innerHTML = "<p>✅ 已完成" + detailHtml + extraLink + " | <a href='/project/" + encodeURIComponent(bookName) + "/kp/" + kpId + "' class='btn btn-sm' style='text-decoration:none;'>查看详情 →</a> <button class='btn btn-sm' onclick='location.reload()'>刷新页面</button></p>";
            }
        } else {
            if (se) { se.className = "step-status status-failed"; se.textContent = "失败"; }
            if (be) be.disabled = false;
            if (pt) pt.textContent = "失败: " + (data.error || "未知错误");
            if (ee) { ee.style.display = "block"; ee.innerHTML = "<strong>错误:</strong> " + esc(data.error || "未知"); }
        }
    } catch(e) {
        stopStepPoll(stepId);
        if (se) { se.className = "step-status status-failed"; se.textContent = "失败"; }
        if (be) be.disabled = false;
        if (pt) pt.textContent = "请求失败";
        if (ee) { ee.style.display = "block"; ee.innerHTML = "<strong>请求失败:</strong> " + esc(e.message); }
    }
}

document.addEventListener("DOMContentLoaded", function() {
    var input = document.getElementById("new-book-input");
    if (input) input.addEventListener("keydown", function(ev) { if (ev.key === "Enter") startNewBook(); });
    var aiInput = document.getElementById("ai-input");
    if (aiInput) aiInput.addEventListener("keydown", function(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            var val = aiInput.value.trim();
            if (val) window._agentProduce(val);
        }
    });
    var kimi = document.getElementById("agent-query-input");
    if (kimi) kimi.addEventListener("keydown", function(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            var val = kimi.value.trim();
            if (val) window._agentProduce(val);
        }
    });
    loadAgentDrafts();
    loadFeedbackPrefs();
    // 如果 URL 中有 auto_generate=1，自动触发生成
    var urlp2 = new URLSearchParams(window.location.search);
    if (urlp2.get('auto_generate') === '1') {
        var urlBook = _safeDecodeURI(urlp2.get('book') || '');
        if (urlBook && urlBook !== '__new__') {
            setTimeout(function() { window._agentProduce(urlBook); }, 500);
        }
    }
});

function loadFeedbackPrefs() {
    var prefsEl = document.getElementById('feedback-prefs');
    var listEl = document.getElementById('feedback-prefs-list');
    if (!prefsEl || !listEl) return;
    fetch('/api/feedback/memory')
        .then(function(r){ return r.json(); })
        .then(function(j) {
            if (!j.success) return;
            var prefs = j.data.preferences;
            var liked = prefs.liked_styles || [];
            var disliked = prefs.disliked_styles || [];
            var parts = [];
            if (liked.length) parts.push('👍 ' + liked.join('、'));
            if (disliked.length) parts.push('👎 ' + disliked.join('、'));
            if (parts.length) {
                listEl.textContent = parts.join(' | ');
                prefsEl.style.display = 'block';
            }
        })
        .catch(function(){});
}

function setTopicFocus(text) {
    var inp = document.getElementById('topic-focus-input');
    if (inp) inp.value = text;
}

function extractBookFromQuery(q) {
    var m = q.match(/《(.+?)》/);
    if (m) return m[1].trim();
    return q.replace(/帮我分析|帮我|分析|适合做哪些视频选题|适合做什么|怎么做/g, "").trim();
}

function agentQuickAnalyze() {
    var inp = document.getElementById("agent-query-input");
    if (!inp || !inp.value.trim()) { alert("请输入书名"); return; }
    var bn = extractBookFromQuery(inp.value.trim());
    if (bn) window.location.href = "/work?book=" + encodeURIComponent(bn) + "&auto_analyze=1";
}

function agentQuickGenerate() {
    var inp = document.getElementById("agent-query-input");
    if (!inp || !inp.value.trim()) { alert("请输入书名"); return; }
    var bn = extractBookFromQuery(inp.value.trim());
    if (bn) window.location.href = "/work?book=" + encodeURIComponent(bn) + "&auto_generate=1";
}

// ─── 全局状态 ──────────────────────────────────────────────
// 当前书名（反复解码直到纯净中文）
function _safeDecodeURI(s) {
    if (!s) return "";
    var prev;
    var r = s;
    do {
        prev = r;
        try { r = decodeURIComponent(r); } catch(e) { break; }
    } while (r !== prev);
    return r;
}
window._agentBookName = _safeDecodeURI(new URLSearchParams(window.location.search).get("book") || "");
// 当前选题列表（完整），由 loadAgentDrafts / _agentProduce 维护
window._agentTopics = [];

// ─── 加载已保存选题（完整列表）────────────────────────────
function loadAgentDrafts() {
    var urlp = new URLSearchParams(window.location.search);
    var rawBook = urlp.get("book") || "";
    var bookName = _safeDecodeURI(rawBook);
    var activeKpId = parseInt(urlp.get("kp_id") || "0");
    var sub = document.getElementById("topic-pool-subtitle");

    // 同步全局状态（再次保底解码）
    if (bookName) window._agentBookName = bookName;

    if (!bookName) return Promise.resolve();

    return fetch("/api/agent/drafts?book_name=" + encodeURIComponent(bookName))
    .then(function(r) { return r.json(); })
    .then(function(j) {
        var el = document.getElementById("agent-topics");
        if (!el) return;

        if (!j.success || !j.data || !j.data.saved || !j.data.saved.length) {
            el.innerHTML = '<div class="topic-pool-empty">暂无选题，点击上方「生成选题池」开始分析</div>';
            if (sub) sub.textContent = '0 个选题';
            window._agentTopics = [];
            return;
        }

        var list = j.data.saved;
        if (sub) sub.textContent = list.length + ' 个选题';

        // 更新全局选题列表
        window._agentTopics = list.map(function(s) {
            return {
                topic_id: s.topic_id,
                topic_title: s.topic_title || "",
                score: s.score || 0,
                hook_type: s.hook_type || "",
                why_attractive: s.why_attractive || "",
                target_audience: s.target_audience || "",
                content_angle: s.content_angle || "",
                has_script: !!s.has_script,
                kp_id: s.kp_id || (100 + (s.topic_id || 0))
            };
        });
        window._agentSelected = new Set(list.map(function(s){ return s.topic_id; }));
        window._agentStrategyParams = window._agentStrategyParams || {};

        renderTopicPool(list, bookName, activeKpId);
    })
    .catch(function() {
        var el = document.getElementById("agent-topics");
        if (el) el.innerHTML = '<div class="topic-pool-empty">加载失败，请刷新重试</div>';
    });
}

// ─── 渲染选题卡片 ──────────────────────────────────────────
function renderTopicPool(list, bookName, activeKpId) {
    var el = document.getElementById("agent-topics");
    if (!el) return;

    var h = '<div class="topic-pool-list">';
    list.forEach(function(s) {
        var kpId = s.kp_id || (100 + (s.topic_id || 0));
        var score = parseInt(s.score) || 0;
        var title = esc(s.topic_title || "未命名选题");
        var hookType = esc(s.hook_type || "");
        var isActive = (kpId === activeKpId);
        var hasScript = !!s.has_script;
        var scoreClass = score >= 85 ? 'high' : (score >= 70 ? 'med' : 'low');
        var topicId = s.topic_id;

        h += '<div class="topic-pool-card ' + (isActive ? 'topic-card-active' : '') + '" id="topic-card-' + topicId + '">';
        // onclick 不传 bookName，仅传 topicId；_agentSelectTopic 通过全局 window._agentBookName 取书名
        h += '<div class="topic-card-main" onclick="window._agentSelectTopic(' + topicId + ')">';
        h += '<div class="topic-card-top">';
        h += '<div class="topic-card-title">' + title + '</div>';
        h += '<div class="topic-card-score"><span class="topic-score-num ' + scoreClass + '">' + score + '</span></div>';
        h += '</div>';
        h += '<div class="topic-card-meta">';
        if (hookType) h += '<span class="topic-card-tag">' + hookType + '</span>';
        h += '<span class="topic-card-id">KP #' + kpId + '</span>';
        if (isActive) h += '<span class="topic-card-current">当前</span>';
        h += '</div>';
        h += '<div class="topic-card-status">';
        if (hasScript) {
            h += '<span class="topic-status-badge status-done">&#10003; 讲稿已生成</span>';
        } else {
            h += '<span class="topic-status-badge status-pending">等待生成讲稿</span>';
        }
        h += '</div>';
        h += '</div>'; // /topic-card-main
        h += '<div class="topic-card-actions">';
        h += '<button class="tbtn tbtn-primary tbtn-sm" onclick="event.stopPropagation();window._agentSelectTopic(' + topicId + ')">进入工作台</button>';
        if (!hasScript) {
            h += '<button class="tbtn tbtn-outline tbtn-sm" onclick="event.stopPropagation();window._agentGenScript(' + topicId + ')" id="gen-btn-' + topicId + '">生成讲稿</button>';
        }
        h += '<button class="tbtn tbtn-ghost tbtn-sm" onclick="event.stopPropagation();window._agentDeleteTopic(' + topicId + ')" title="删除选题">删除</button>';
        h += '<span id="gen-status-' + topicId + '" class="topic-gen-status"></span>';
        h += '</div>';
        h += '<div class="topic-card-feedback">';
        h += '<button class="fb-btn fb-like" onclick="event.stopPropagation();feedbackTopic(' + topicId + ', ' + "'like'" + ', ' + "'" + title + "'" + ')" title="这个选题不错">👍</button>';
        h += '<button class="fb-btn fb-dislike" onclick="event.stopPropagation();feedbackTopic(' + topicId + ', ' + "'dislike'" + ', ' + "'" + title + "'" + ')" title="这个选题不行">👎</button>';
        h += '<span id="fb-status-' + topicId + '" class="fb-status"></span>';
        h += '</div>';
        h += '</div>';
    });
    h += '</div>';
    el.innerHTML = h;
    el.style.display = 'block';
}

// ─── 选中选题 → 进入工作台 ──────────────────────────────
window._agentSelectTopic = function(topicId) {
    var bookName = window._agentBookName;
    if (!bookName) { alert('缺少书名，请刷新页面'); return; }
    var kpId = 100 + topicId;
    window.location.href = "/work?book=" + encodeURIComponent(bookName) + "&kp_id=" + kpId;
};

// ─── 删除选题 ──────────────────────────────────────────────
window._agentDeleteTopic = function(topicId) {
    if (!confirm('确定要删除这个选题吗？')) return;
    var card = document.getElementById('topic-card-' + topicId);
    if (card) card.style.opacity = '0.3';

    var remaining = (window._agentTopics || []).filter(function(t) { return t.topic_id !== topicId; });
    var bookName = window._agentBookName;
    if (!bookName) { alert('缺少书名'); return; }

    fetch('/api/agent/confirm-topic', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
            book_name: bookName,
            topic_ids: remaining.map(function(t){return t.topic_id;}),
            topics: remaining,
            strategy_params: window._agentStrategyParams||{}
        })
    }).then(function(r){return r.json();}).then(function(j) {
        window._agentTopics = remaining;
        loadAgentDrafts();
    }).catch(function() {
        if (card) card.style.opacity = '1';
        alert('删除失败');
    });
};

// ─── 生成讲稿（核心修复）───────────────────────────────────
window._agentGenScript = async function(topicId) {
    var btn = document.getElementById('gen-btn-' + topicId);
    var st = document.getElementById('gen-status-' + topicId);
    var bookName = window._agentBookName;

    // === 校验 ===
    if (!bookName) {
        if (st) st.textContent = '错误：缺少书名';
        if (st) st.style.color = 'var(--destructive)';
        return;
    }
    if (!window._agentTopics || window._agentTopics.length === 0) {
        if (st) st.textContent = '请先生成并选择选题';
        if (st) st.style.color = 'var(--destructive)';
        return;
    }

    // 找到该选题数据
    var topic = null;
    for (var i = 0; i < window._agentTopics.length; i++) {
        if (window._agentTopics[i].topic_id === topicId) {
            topic = window._agentTopics[i];
            break;
        }
    }
    if (!topic) {
        if (st) st.textContent = '未找到选题 (#' + topicId + ')';
        if (st) st.style.color = 'var(--destructive)';
        if (btn) { btn.disabled = false; btn.textContent = '生成讲稿'; }
        return;
    }

    // === 显示 loading ===
    if (btn) { btn.disabled = true; btn.textContent = '保存中...'; }
    if (st) { st.textContent = '准备中...'; st.style.color = 'var(--muted-foreground)'; }

    try {
        // Step 1: 保存选题到 knowledge_plan.json
        if (st) st.textContent = '正在保存选题...';
        var saveResp = await fetch('/api/agent/confirm-topic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                book_name: bookName,
                topic_ids: [topicId],
                topics: window._agentTopics,
                strategy_params: window._agentStrategyParams || {}
            })
        });
        var saveData = await saveResp.json();
        if (!saveData.success) {
            if (btn) { btn.disabled = false; btn.textContent = '生成讲稿'; }
            if (st) { st.textContent = '保存失败: ' + (saveData.error || '未知错误'); st.style.color = 'var(--destructive)'; }
            return;
        }

        // Step 2: 生成讲稿
        if (st) { st.textContent = 'AI 生成中...'; st.style.color = 'var(--muted-foreground)'; }
        if (btn) btn.textContent = '生成中...';

        try {
            var gcController = new AbortController();
            var gcTimeout = setTimeout(function() { gcController.abort(); }, 120000);
            var r = await fetch('/api/agent/generate-script', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ book_name: bookName, topic_id: topicId }),
                signal: gcController.signal
            });
            clearTimeout(gcTimeout);
            var j = await r.json();
            if (j.success) {
                var d = j.data;
                if (btn) { btn.textContent = '已生成'; btn.className = 'tbtn tbtn-sm'; btn.disabled = true; }
                if (st) {
                    var pipelineUrl2 = '/work?book=' + encodeURIComponent(bookName) + '&kp_id=' + d.kp_id;
                    st.innerHTML = '✅ 完成 <strong>' + (d.script_words || '?') + '</strong>字 | <a href="' + pipelineUrl2 + '" style="color:var(--brand);font-weight:600;">进入工作台 →</a>';
                    st.style.color = 'var(--brand)';
                }
                if (d.kp_id) {
                    window.location.href = '/work?book=' + encodeURIComponent(bookName) + '&kp_id=' + d.kp_id;
                    return;
                }
                return;
            }
            if (btn) { btn.disabled = false; btn.textContent = '重新生成'; }
            if (st) { st.innerHTML = '<span style=color:var(--destructive);font-weight:600;>失败: </span>' + esc(j.error || 'AI 生成出错'); }
        } catch(e) {
            // 即使 fetch 超时/失败，后端可能已成功生成，直接跳到工作台
            var genUrl = '/work?book=' + encodeURIComponent(bookName) + '&kp_id=' + (100 + topicId);
            if (btn) { btn.disabled = false; btn.textContent = '查看结果'; btn.className = 'tbtn tbtn-primary tbtn-sm'; btn.onclick = function(){ window.location.href = genUrl; }; }
            if (st) { st.innerHTML = '⏳ 后台正在生成，<a href="' + genUrl + '" style="color:var(--brand);font-weight:600;">点击查看进度 →</a>'; st.style.color = 'var(--muted-foreground)'; }
        }
    } catch(e) {
        // 外层 try：保存选题失败时静默处理
        console.warn('保存选题/生成讲稿出错:', e);
    }
};

// ─── 生成选题池（Agent 分析）───────────────────────────────
// Content Growth Agent 推理步骤（增强版）
var reasoningStepsData = [
    { label: "读取历史内容信号规律", detail: "加载自身账号高/低表现信号记忆…" },
    { label: "分析高播放内容模式", detail: "识别情绪/认知/利益/代入信号表现…" },
    { label: "筛选已验证策略", detail: "从策略池中过滤废弃策略…" },
    { label: "匹配最优内容策略", detail: "结合品类与受众选择最佳策略…" },
    { label: "解析书籍结构与核心论点", detail: "识别章节与关键观点…" },
    { label: "注入增长信号到选题生成", detail: "用历史高表现信号优化选题方向…" },
    { label: "生成候选选题池", detail: "产出差异化、信号增强的选题角度…" },
    { label: "记录策略结果", detail: "将选择策略写入策略池…" },
];

window._agentProduce = async function(bookName) {
    // 统一提取书名
    if (bookName && bookName !== '__new__' && bookName !== '') {
        var extracted = extractBookFromQuery(bookName);
        if (extracted && extracted.length > 0 && extracted.length < 20) bookName = extracted;
    }
    if (!bookName || bookName === '__new__') {
        var inp = document.getElementById('ai-input') || document.getElementById('agent-query-input');
        if (inp && inp.value.trim()) {
            bookName = extractBookFromQuery(inp.value.trim());
        }
    }
    if (!bookName || bookName === '__new__' || bookName.length > 15) {
        var urlp = new URLSearchParams(window.location.search);
        bookName = _safeDecodeURI(urlp.get('book') || '');
    }
    if (!bookName || bookName === '__new__' || bookName.length > 15) return;

    // 如果当前页面是控制台（没有 btn-produce），跳转到工作台页面
    if (!document.getElementById('btn-produce')) {
        window.location.href = '/work?book=' + encodeURIComponent(bookName) + '&auto_generate=1';
        return;
    }
    var btn = document.getElementById('btn-produce');
    var st = document.getElementById('produce-status');
    var topics = document.getElementById('agent-topics');
    var reasoning = document.getElementById('agent-reasoning');
    var scriptWs = document.getElementById('agent-script-workspace');
    var res = document.getElementById('agent-result');

    btn.disabled = true; btn.textContent = '分析中…';
    if (st) st.textContent = '';
    if (scriptWs) scriptWs.style.display = 'none';
    if (res) res.style.display = 'none';

    // 推理过程动画
    if (reasoning) {
        var stepsHtml = reasoningStepsData.map(function(s, i) {
            return '<li class="v0-step" id="rs-' + i + '"><span class="v0-step-dot"><span class="v0-step-pending"></span></span><div><p class="v0-step-label pending">' + s.label + '</p><p class="v0-step-detail" style="display:none;">' + s.detail + '</p></div></li>';
        }).join('');
        reasoning.innerHTML = '<div class="v0-reasoning-card"><div class="v0-reasoning-header"><div class="v0-reasoning-icon">*</div><div><p class="v0-reasoning-query-label">正在分析</p><p class="v0-reasoning-query-text">《' + esc(bookName) + '》</p></div></div><ol class="v0-step-list">' + stepsHtml + '</ol></div>';
        reasoning.style.display = 'block';
        var stepIdx = 0;
        var stepTimer = setInterval(function() {
            if (stepIdx > 0) {
                var prev = document.getElementById('rs-' + (stepIdx-1));
                if (prev) {
                    prev.querySelector('.v0-step-dot').innerHTML = '<span class="v0-step-check">✓</span>';
                    prev.querySelector('.v0-step-label').className = 'v0-step-label done';
                    prev.querySelector('.v0-step-detail').style.display = 'block';
                }
            }
            if (stepIdx < reasoningStepsData.length) {
                var cur = document.getElementById('rs-' + stepIdx);
                if (cur) {
                    cur.querySelector('.v0-step-dot').innerHTML = '<span class="v0-step-spinner"></span>';
                    cur.querySelector('.v0-step-label').className = 'v0-step-label active';
                }
                stepIdx++;
            } else {
                clearInterval(stepTimer);
            }
        }, 600);
        window._stepTimer = stepTimer;
    }

    try {
        var produceController = new AbortController();
        var produceTimeout = setTimeout(function() { produceController.abort(); }, 120000);
        var r = await fetch('/api/agent/produce', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                book_name: bookName,
                focus: (document.getElementById('topic-focus-input') || {}).value || ''
            }),
            signal: produceController.signal
        });
        clearTimeout(produceTimeout);
        var j = await r.json();
        btn.disabled = false; btn.textContent = '重新生成选题池';
        if (st) st.textContent = '';
        if (window._stepTimer) clearInterval(window._stepTimer);

        if (!j.success) {
            if (st) st.innerHTML = '<span style="color:var(--destructive);">失败: ' + (j.error || '') + '</span>';
            return;
        }

        var d = j.data, list = d.topics || [];
        if (reasoning) {
            var lastStep = document.getElementById('rs-' + (reasoningStepsData.length-1));
            if (lastStep) {
                lastStep.querySelector('.v0-step-dot').innerHTML = '<span class="v0-step-check">✓</span>';
                lastStep.querySelector('.v0-step-label').className = 'v0-step-label done';
                lastStep.querySelector('.v0-step-detail').style.display = 'block';
            }
            reasoning.innerHTML += '<div class="v0-reasoning-done-banner">已完成分析 · 保存中…</div>';
        }

        // 更新全局
        window._agentBookName = bookName;
        window._agentTopics = list.map(function(t) {
            return {
                topic_id: t.topic_id,
                topic_title: t.topic_title || "",
                score: t.score || 0,
                hook_type: t.hook_type || "",
                why_attractive: t.why_attractive || "",
                target_audience: t.target_audience || "",
                content_angle: t.content_angle || ""
            };
        });
        window._agentSelected = new Set(list.map(function(t){ return t.topic_id; }));
        window._agentStrategyParams = {
            category: (d.classification||{}).category||'',
            strategy_name: (d.strategy||{}).strategy_name||''
        };

        // 自动保存所有选题到 knowledge_plan.json
        try {
            var saveResp = await fetch('/api/agent/confirm-topic', {
                method:'POST', headers:{'Content-Type':'application/json'},
                body:JSON.stringify({
                    book_name: bookName,
                    topic_ids: list.map(function(t){return t.topic_id;}),
                    topics: list,
                    strategy_params: window._agentStrategyParams
                })
            });
            var saveData = await saveResp.json();
            if (!saveData.success) {
                console.warn('保存选题响应异常:', saveData);
            }
        } catch(saveErr) {
            console.warn('自动保存选题失败（可忽略）:', saveErr);
        }

        // 跳转到新书的页面，刷新侧边栏和选区显示
        var newUrl = '/work?book=' + encodeURIComponent(bookName);
        if (window.location.href.indexOf('book=' + encodeURIComponent(bookName)) === -1) {
            window.location.href = newUrl;
            return;
        }
        // URL 已经是新书的，直接刷新选区
        window._agentBookName = bookName;
        try {
            await loadAgentDrafts();
        } catch(e) {
            console.warn('刷新选题池失败:', e);
        }
        if (reasoning) {
            var doneBanner = reasoning.querySelector('.v0-reasoning-done-banner');
            if (doneBanner) {
                // 保存完成后隐藏"保存中"
                doneBanner.textContent = '✅ 分析完成，已保存 ' + list.length + ' 个选题';
                doneBanner.style.background = 'color-mix(in srgb, var(--brand) 10%, transparent)';
                doneBanner.style.color = 'var(--brand)';
            }
        }
        if (st) st.textContent = '✅ ' + list.length + ' 个选题已保存';
        if (st) st.style.color = 'var(--brand)';

    } catch(e) {
        btn.disabled = false; btn.textContent = '生成选题池';
        if (window._stepTimer) clearInterval(window._stepTimer);
        var errMsg = e.name === 'AbortError' ? '请求超时（LLM 生成耗时较长，请重试）' : e.message;
        if (st) st.innerHTML = '<span style="color:var(--destructive);">错误: ' + errMsg + '</span>';
        console.error('生成选题池异常:', e);
    }
};

// ─── 反馈 ──────────────────────────────────────────────────
function feedbackTopic(topicId, feedback, topicTitle) {
    var fbStatus = document.getElementById('fb-status-' + topicId);
    var emoji = feedback === 'like' ? '👍' : '👎';
    var label = feedback === 'like' ? '喜欢' : '不喜欢';

    // 如果有原因就弹窗询问
    var reason = prompt(label + '这个选题——' + (feedback === 'like' ? '它好在哪里？' : '哪里不满意？有什么建议？') + '（可选，直接确定也可）');
    if (reason === null) return;

    fetch('/api/feedback/topic', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
            book_name: window._agentBookName||'',
            topic_id: topicId,
            topic_title: topicTitle||'',
            feedback: feedback,
            reason: (reason||'').trim()
        })
    }).then(function(r){return r.json();}).then(function(j){
        if (fbStatus) {
            fbStatus.textContent = feedback === 'like' ? ' 👍 已标记' : ' 👎 已标记';
            fbStatus.style.color = feedback === 'like' ? 'var(--brand)' : 'var(--destructive)';
            fbStatus.style.fontSize = '0.7rem';
            fbStatus.style.fontWeight = '600';
            setTimeout(function(){ fbStatus.textContent = ''; }, 3000);
        }
        // 提示下次选题时会考虑偏好
        if (window._produceStatusEl) {
            window._produceStatusEl.textContent = '已记录偏好，下次生成选题时会参考';
            window._produceStatusEl.style.color = 'var(--muted-foreground)';
        }
    }).catch(function(){});
}

// ─── 图片生成进度轮询 ────────────────────────────────────
var _imgPollTimer = null;

function runImageGen(bookName, kpId) {
  var btn = document.getElementById('btn-generate_images');
  var se = document.getElementById('status-generate_images');
  var area = document.getElementById('img-progress-area');
  var output = document.getElementById('output-generate_images');
  var errEl = document.getElementById('error-generate_images');

  if (se) { se.className = 'step-status status-running'; se.textContent = '生成中...'; }
  if (btn) btn.disabled = true;
  if (output) output.style.display = 'none';
  if (errEl) errEl.style.display = 'none';
  if (area) area.style.display = 'block';

  // 开始轮询进度
  startImgPoll(bookName, kpId);

  fetch('/api/pipeline/' + encodeURIComponent(bookName) + '/run/generate-images/' + kpId, { method: 'POST' })
    .then(function(r){ return r.json(); })
    .then(function(data) {
      stopImgPoll();
      if (se) {
        if (data.success) {
          var failed = data.failed || 0;
          var perm = data.permanent_failed || 0;
          if (failed > 0) {
            se.className = 'step-status status-completed';
            se.textContent = failed + '张失败';
          } else {
            se.className = 'step-status status-completed';
            se.textContent = '完成';
          }
        } else {
          se.className = 'step-status status-failed';
          se.textContent = '失败';
        }
      }
      if (btn) { btn.disabled = false; btn.textContent = '重新生成'; }
      if (output) { output.style.display = 'block';
        var pf = data.permanent_failed || 0;
        var outputMsg = (data.success ? '✅ 完成' : '❌ 失败') + ' | 成功' + (data.generated||0) + '张';
        if (data.failed > 0) outputMsg += '，失败' + (data.failed||0) + '张';
        if (pf > 0) outputMsg += '（其中' + pf + '张连续失败4次已停止重试）';
        outputMsg += ' | <a href="/project/' + encodeURIComponent(bookName) + '/kp/' + kpId + '" style="color:var(--primary);font-weight:600;">查看详情 →</a>';
        output.innerHTML = '<p style="color:var(--green);padding:4px 0;">' + outputMsg + '</p>';
      }
      if (!data.success && errEl) { errEl.style.display = 'block'; errEl.innerHTML = '<strong>错误:</strong> ' + esc(data.error || '未知'); }
      updateImgProgress(data);
    })
    .catch(function(e) {
      stopImgPoll();
      if (se) { se.className = 'step-status status-failed'; se.textContent = '失败'; }
      if (btn) btn.disabled = false;
      if (errEl) { errEl.style.display = 'block'; errEl.innerHTML = '<strong>请求失败:</strong> ' + esc(e.message); }
    });
}

function runRetryImages(bookName, kpId) {
  var btn = document.getElementById('btn-retry-images');
  var se = document.getElementById('status-generate_images');
  var area = document.getElementById('img-progress-area');
  var errEl = document.getElementById('error-generate_images');

  if (se) { se.className = 'step-status status-running'; se.textContent = '重试中...'; }
  if (btn) btn.disabled = true;
  if (errEl) errEl.style.display = 'none';
  if (area) area.style.display = 'block';

  startImgPoll(bookName, kpId);

  fetch('/api/pipeline/' + encodeURIComponent(bookName) + '/run/retry-images/' + kpId, { method: 'POST' })
    .then(function(r){ return r.json(); })
    .then(function(data) {
      stopImgPoll();
      if (se) {
        var failed = data.failed || 0;
        se.className = 'step-status status-completed';
        se.textContent = failed > 0 ? failed + '张仍失败' : '完成';
      }
      if (btn) btn.disabled = false;
      updateImgProgress(data);
      var output = document.getElementById('output-generate_images');
      if (output) { output.style.display = 'block';
        var pf = data.permanent_failed || 0;
        var msg = (data.success ? '✅ 重试完成' : '❌ 重试失败') + ' | 成功' + (data.generated||0) + '张';
        if (data.failed > 0) msg += '，失败' + (data.failed||0) + '张';
        if (pf > 0) msg += '（其中' + pf + '张连续失败4次已停止重试）';
        output.innerHTML = '<p style="color:var(--green);padding:4px 0;">' + msg + '</p>';
      }
    })
    .catch(function(e) {
      stopImgPoll();
      if (se) { se.className = 'step-status status-failed'; se.textContent = '重试失败'; }
      if (btn) btn.disabled = false;
      if (errEl) { errEl.style.display = 'block'; errEl.innerHTML = '<strong>请求失败:</strong> ' + esc(e.message); }
    });
}

function startImgPoll(bookName, kpId) {
  stopImgPoll();
  _imgPollTimer = setInterval(function() {
    fetch('/api/pipeline/' + encodeURIComponent(bookName) + '/generate-progress/' + kpId)
      .then(function(r){ return r.json(); })
      .then(function(p) {
        updateImgProgress(p);
        if (p.stage === 'finish' || p.stage === 'paused') {
          stopImgPoll();
        }
      }).catch(function(){});
  }, 1500);
}

function stopImgPoll() {
  if (_imgPollTimer) {
    clearInterval(_imgPollTimer);
    _imgPollTimer = null;
  }
}

function updateImgProgress(p) {
  if (!p) return;
  var total = p.total || 0;
  var current = p.current || 0;
  var generated = p.generated || 0;
  var failed = p.failed || 0;
  var apiCalls = p.api_calls || 0;
  var stage = p.stage || '';
  var msg = p.message || '';

  if (total > 0) {
    var bar = document.getElementById('img-progress-bar');
    var txt = document.getElementById('img-progress-text');
    var pct = Math.round((current / total) * 100);
    if (bar) bar.style.width = Math.min(pct, 100) + '%';
    if (txt) txt.textContent = current + '/' + total;
  }

  var ge = document.getElementById('img-gen-count');
  var fe = document.getElementById('img-fail-count');
  var ae = document.getElementById('img-api-count');
  var se = document.getElementById('img-stage-badge');
  if (ge) ge.textContent = generated;
  if (fe) fe.textContent = failed;
  if (ae) ae.textContent = apiCalls;
  if (se) {
    se.textContent = stage === 'generating' ? '生成中' : stage === 'finish' ? '已完成' : stage === 'paused' ? '已暂停' : stage;
    se.style.background = stage === 'finish' ? 'color-mix(in srgb, var(--brand) 12%, transparent)' : stage === 'generating' ? 'color-mix(in srgb, oklch(0.5 0.13 245) 12%, transparent)' : 'var(--secondary)';
    se.style.color = stage === 'finish' ? 'var(--brand)' : stage === 'generating' ? 'oklch(0.5 0.13 245)' : 'var(--muted-foreground)';
  }
}
