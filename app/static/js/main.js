/* IT Manager — 共用 JS（Theme / Toast / Confirm Modal / Quick Nav / AJAX helpers） */
(function () {
    'use strict';

    const getCsrfToken = () => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    };

    // ── Theme manager ─────────────────────────────────────
    const THEME_KEY = 'cm-theme';
    const mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    function applyTheme(pref) {
        const effective = (pref === 'auto')
            ? (mq && mq.matches ? 'dark' : 'light')
            : pref;
        document.documentElement.setAttribute('data-bs-theme', effective);
        document.documentElement.setAttribute('data-cm-theme-pref', pref);
        updateThemeIcon(pref);
        document.dispatchEvent(new CustomEvent('cm:theme-change', {
            detail: {pref, effective}
        }));
    }

    function updateThemeIcon(pref) {
        const icon = document.getElementById('cm-theme-icon');
        if (!icon) return;
        const cls = pref === 'dark'  ? 'bi-moon-stars-fill'
                  : pref === 'light' ? 'bi-sun-fill'
                                     : 'bi-circle-half';
        icon.className = 'bi ' + cls;
    }

    function getThemePref() {
        return localStorage.getItem(THEME_KEY) || 'auto';
    }

    function setThemePref(pref) {
        if (pref === 'auto') localStorage.removeItem(THEME_KEY);
        else localStorage.setItem(THEME_KEY, pref);
        applyTheme(pref);
    }

    function initTheme() {
        const pref = getThemePref();
        applyTheme(pref);
        document.querySelectorAll('[data-cm-theme]').forEach((btn) => {
            btn.addEventListener('click', () => setThemePref(btn.dataset.cmTheme));
        });
        if (mq) {
            const onChange = () => {
                if (getThemePref() === 'auto') applyTheme('auto');
            };
            if (mq.addEventListener) mq.addEventListener('change', onChange);
            else if (mq.addListener) mq.addListener(onChange);
        }
    }

    // ── Toast 系統 ──
    function showToast(message, level = 'info', delay = 3500) {
        const container = document.getElementById('toast-container');
        if (!container) {
            console.warn('toast container not found');
            alert(message);
            return;
        }
        const iconMap = {
            success: 'bi-check-circle-fill',
            danger:  'bi-x-circle-fill',
            warning: 'bi-exclamation-triangle-fill',
            info:    'bi-info-circle-fill',
        };
        const bgMap = {
            success: 'text-bg-success',
            danger:  'text-bg-danger',
            warning: 'text-bg-warning',
            info:    'text-bg-info',
        };
        const div = document.createElement('div');
        div.className = `toast align-items-center border-0 ${bgMap[level] || bgMap.info}`;
        div.setAttribute('role', 'alert');
        div.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <i class="bi ${iconMap[level] || iconMap.info} me-1"></i>${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto"
                        data-bs-dismiss="toast"></button>
            </div>`;
        container.appendChild(div);
        const t = new bootstrap.Toast(div, {delay});
        div.addEventListener('hidden.bs.toast', () => div.remove());
        t.show();
    }

    // ── Confirm Modal ──
    function confirmModal({title, body, okText = '確認', okClass = 'btn-danger'} = {}) {
        return new Promise((resolve) => {
            const modalEl = document.getElementById('confirm-modal');
            if (!modalEl) {
                resolve(window.confirm(body || title || '確認？'));
                return;
            }
            if (title) document.getElementById('confirm-modal-title').textContent = title;
            if (body)  document.getElementById('confirm-modal-body').textContent = body;
            const okBtn = document.getElementById('confirm-modal-ok');
            okBtn.textContent = okText;
            okBtn.className = `btn ${okClass}`;

            const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
            let decided = false;
            const onOk = () => { decided = true; modal.hide(); resolve(true); };
            const onHidden = () => {
                okBtn.removeEventListener('click', onOk);
                modalEl.removeEventListener('hidden.bs.modal', onHidden);
                if (!decided) resolve(false);
            };
            okBtn.addEventListener('click', onOk);
            modalEl.addEventListener('hidden.bs.modal', onHidden);
            modal.show();
        });
    }

    // ── AJAX helpers ──
    async function postJSON(url, body = null) {
        const opts = {
            method: 'POST',
            headers: {'X-CSRFToken': getCsrfToken()},
        };
        if (body) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        const res = await fetch(url, opts);
        let data = null;
        try { data = await res.json(); } catch (e) { /* non-JSON */ }
        return {ok: res.ok, status: res.status, data};
    }

    // ── data-confirm 表單攔截（全站） ──
    document.addEventListener('submit', async (e) => {
        const form = e.target;
        if (!(form instanceof HTMLFormElement)) return;
        const msg = form.dataset.confirm;
        if (!msg) return;
        if (form.dataset.confirmed === '1') return;
        e.preventDefault();
        const ok = await confirmModal({body: msg});
        if (ok) {
            form.dataset.confirmed = '1';
            form.submit();
        }
    }, true);

    // ── Submit button loading spinner ──
    // Any <button data-loading-text="..."> inside a form switches to a spinner on submit.
    document.addEventListener('submit', (e) => {
        const form = e.target;
        if (!(form instanceof HTMLFormElement)) return;
        form.querySelectorAll('button[type="submit"][data-loading-text], button[data-loading-text]:not([type])').forEach((btn) => {
            if (btn.classList.contains('is-loading')) return;
            const original = btn.innerHTML;
            btn.dataset.originalContent = original;
            btn.classList.add('is-loading');
            btn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>${btn.dataset.loadingText || '處理中…'}`;
            btn.disabled = true;
        });
    });

    // ── Quick Nav (Ctrl+K / ⌘K) ──
    function initQuickNav() {
        const dataEl = document.getElementById('cm-quicknav-data');
        const modalEl = document.getElementById('cm-quicknav-modal');
        if (!dataEl || !modalEl) return;
        let items;
        try { items = JSON.parse(dataEl.textContent); }
        catch (e) { items = {}; }
        const entries = Object.entries(items).map(([name, url]) => ({name, url}));
        const input = document.getElementById('cm-quicknav-input');
        const list = document.getElementById('cm-quicknav-list');
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        let active = 0;

        function render(q) {
            const needle = (q || '').trim().toLowerCase();
            const filtered = needle
                ? entries.filter((e) => e.name.toLowerCase().includes(needle))
                : entries;
            if (!filtered.length) {
                list.innerHTML = '<li class="cm-empty-hint">找不到符合的頁面</li>';
                active = -1;
                return;
            }
            list.innerHTML = filtered.map((e, i) =>
                `<li data-url="${e.url}" class="${i === 0 ? 'is-active' : ''}"><i class="bi bi-arrow-right-short"></i>${e.name}</li>`
            ).join('');
            active = 0;
        }

        function go(i) {
            const lis = list.querySelectorAll('li[data-url]');
            if (!lis.length) return;
            active = (i + lis.length) % lis.length;
            lis.forEach((li, idx) => li.classList.toggle('is-active', idx === active));
            lis[active].scrollIntoView({block: 'nearest'});
        }

        function commit() {
            const el = list.querySelector('li.is-active[data-url]');
            if (el) window.location.href = el.dataset.url;
        }

        input.addEventListener('input', () => render(input.value));
        input.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); go(active + 1); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); go(active - 1); }
            else if (e.key === 'Enter') { e.preventDefault(); commit(); }
        });
        list.addEventListener('click', (e) => {
            const li = e.target.closest('li[data-url]');
            if (li) window.location.href = li.dataset.url;
        });
        modalEl.addEventListener('shown.bs.modal', () => {
            input.value = '';
            render('');
            input.focus();
        });

        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                modal.show();
            }
        });
        const btn = document.getElementById('cm-quicknav-btn');
        if (btn) btn.addEventListener('click', () => modal.show());
    }

    // ── 格式工具 ──
    const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));

    const fmtSize = (n) => {
        if (n == null) return '';
        if (n < 1024) return n + ' B';
        if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
        return (n / 1024 / 1024).toFixed(2) + ' MB';
    };

    // ── 差異比較版本清單：連續相同 hash 的中間版本折疊 ──
    function renderVersionRows(items, viewUrlTpl, dlUrlTpl) {
        if (!items || !items.length) return '';

        const groups = [];
        let cur = null;
        items.forEach((it) => {
            const key = it.checksum || `__nohash_${it.id}`;
            if (cur && cur.key === key) {
                cur.items.push(it);
            } else {
                cur = {key, items: [it]};
                groups.push(cur);
            }
        });

        const rowHtml = (it) => {
            const hash = it.checksum
                ? `<code class="text-muted" title="${escapeHtml(it.checksum)}" style="cursor: help;">${escapeHtml(it.checksum.slice(0, 10))}</code>`
                : '<span class="text-muted">—</span>';
            const viewUrl = viewUrlTpl.replace(/\/0\/view$/, '/' + it.id + '/view');
            const dlUrl = dlUrlTpl.replace(/\/0\/download$/, '/' + it.id + '/download');
            return `
                <tr>
                    <td class="text-center"><input type="radio" name="left" value="${it.id}" class="form-check-input"></td>
                    <td class="text-center"><input type="radio" name="right" value="${it.id}" class="form-check-input"></td>
                    <td class="small text-nowrap">${escapeHtml(it.started_at)}</td>
                    <td class="small">${hash}</td>
                    <td class="text-end small text-muted">${fmtSize(it.size)}</td>
                    <td class="text-center text-nowrap">
                        <a href="${viewUrl}" target="_blank" rel="noopener"
                           class="btn btn-sm btn-outline-secondary" title="在新分頁檢視">
                            <i class="bi bi-eye"></i>
                        </a>
                        <a href="${dlUrl}" class="btn btn-sm btn-outline-secondary" title="下載">
                            <i class="bi bi-download"></i>
                        </a>
                    </td>
                </tr>`;
        };

        let gid = 0;
        return groups.map((g) => {
            if (g.items.length <= 2) {
                return g.items.map(rowHtml).join('');
            }
            gid += 1;
            const groupId = `cmp-grp-${gid}-${Math.random().toString(36).slice(2, 8)}`;
            const head = rowHtml(g.items[0]);
            const tail = rowHtml(g.items[g.items.length - 1]);
            const middleRows = g.items.slice(1, -1).map((it) =>
                rowHtml(it).replace('<tr>',
                    `<tr class="version-collapse-row d-none" data-group="${groupId}">`)
            ).join('');
            const midCount = g.items.length - 2;
            const toggle = `
                <tr class="table-light version-collapse-toggle" data-group="${groupId}" style="cursor: pointer;">
                    <td colspan="6" class="text-center small text-muted py-2">
                        <i class="bi bi-chevron-down me-1"></i>
                        中間 ${midCount} 個版本 hash 相同（點擊展開）
                    </td>
                </tr>
                ${middleRows}`;
            return head + toggle + tail;
        }).join('');
    }

    function autoCollapseRows(containerEl, {colspan = 6} = {}) {
        const trs = Array.from(
            containerEl.querySelectorAll('tr[data-checksum]'));
        if (trs.length < 3) return;

        let gid = 0;
        let i = 0;
        while (i < trs.length) {
            const cur = trs[i].dataset.checksum;
            let j = i + 1;
            while (j < trs.length && trs[j].dataset.checksum === cur && cur) {
                j += 1;
            }
            const size = j - i;
            if (size >= 3) {
                gid += 1;
                const groupId = `cmp-grp-auto-${gid}`;
                const midRows = trs.slice(i + 1, j - 1);
                const midCount = midRows.length;
                midRows.forEach((r) => {
                    r.classList.add('version-collapse-row', 'd-none');
                    r.dataset.group = groupId;
                });
                const toggle = document.createElement('tr');
                toggle.className = 'table-light version-collapse-toggle';
                toggle.dataset.group = groupId;
                toggle.style.cursor = 'pointer';
                toggle.innerHTML = `
                    <td colspan="${colspan}" class="text-center small text-muted py-2">
                        <i class="bi bi-chevron-down me-1"></i>
                        中間 ${midCount} 個版本 hash 相同（點擊展開）
                    </td>`;
                trs[i].parentNode.insertBefore(toggle, trs[i + 1]);
            }
            i = j;
        }
    }

    function bindVersionCollapseToggles(rootEl) {
        rootEl.addEventListener('click', (e) => {
            const tr = e.target.closest('.version-collapse-toggle');
            if (!tr) return;
            const gid = tr.dataset.group;
            const hidden = rootEl.querySelectorAll(
                `tr.version-collapse-row[data-group="${gid}"]`);
            if (!hidden.length) return;
            const willShow = hidden[0].classList.contains('d-none');
            hidden.forEach((r) => r.classList.toggle('d-none', !willShow));
            const icon = tr.querySelector('i.bi');
            if (icon) icon.className = willShow ? 'bi bi-chevron-up me-1' : 'bi bi-chevron-down me-1';
        });
    }

    // ── 表格即時過濾 ──
    function initTableFilter(input, table, {emptyText = '查無符合項目'} = {}) {
        if (!input || !table) return;
        const tbody = table.tBodies[0];
        if (!tbody) return;
        const colCount = (table.tHead && table.tHead.rows[0])
            ? table.tHead.rows[0].cells.length : 1;
        let emptyRow = tbody.querySelector('tr.table-filter-empty');
        const filter = () => {
            const q = input.value.trim().toLowerCase();
            let shown = 0;
            Array.from(tbody.rows).forEach((tr) => {
                if (tr.classList.contains('table-filter-empty')) return;
                if (tr.dataset.filterSkip === '1') return;
                const hit = !q || tr.textContent.toLowerCase().includes(q);
                tr.classList.toggle('d-none', !hit);
                if (hit) shown += 1;
            });
            if (shown === 0 && q) {
                if (!emptyRow) {
                    emptyRow = document.createElement('tr');
                    emptyRow.className = 'table-filter-empty';
                    emptyRow.innerHTML = `<td colspan="${colCount}" class="text-center text-muted py-4">${emptyText}</td>`;
                    tbody.appendChild(emptyRow);
                }
                emptyRow.classList.remove('d-none');
            } else if (emptyRow) {
                emptyRow.classList.add('d-none');
            }
        };
        input.addEventListener('input', filter);
    }

    // ── Init all ──
    document.addEventListener('DOMContentLoaded', () => {
        initTheme();
        initQuickNav();
    });

    // legacy shim: showConfirmModal(title, body, okCallback) — used in task-manager inherited templates
    window.showConfirmModal = function (title, body, okCallback) {
        confirmModal({title, body}).then((ok) => { if (ok && typeof okCallback === 'function') okCallback(); });
    };

    // expose
    window.CM = {
        showToast,
        confirmModal,
        postJSON,
        getCsrfToken,
        escapeHtml,
        fmtSize,
        renderVersionRows,
        bindVersionCollapseToggles,
        autoCollapseRows,
        initTableFilter,
        setThemePref,
    };
})();
