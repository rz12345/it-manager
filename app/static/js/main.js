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

    // expose
    window.CM = {
        showToast,
        confirmModal,
        postJSON,
        getCsrfToken,
    };
})();
