/* Config Manager — 共用 JS（Toast / Confirm Modal / AJAX helpers） */
(function () {
    'use strict';

    const getCsrfToken = () => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    };

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
    // items 已依時間新到舊排序；相鄰 checksum 相同者視為同群組。
    // 群組 size>=3：顯示首尾 + 中間折疊列；size==2：全顯示；size==1：單列。
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

    // 掃描 container 內 tr[data-checksum]，將連續相同 checksum 的群組折疊
    // （群組 size>=3：首尾保留、中間折疊；size<=2：保留全部）。
    // 用於 Server-rendered 比較版本表格。
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

    // 綁定折疊切換（事件委派在 tbody / table 上）
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
    };
})();
