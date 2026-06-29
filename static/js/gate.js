(function () {
    const STORAGE_KEY = 'pvzh_gate_token';
    const META_KEY = 'pvzh_gate_meta';
    const BUILD = '20260629b';

    let statusPayload = null;

    function trimToken(value) {
        return String(value || '').trim();
    }

    function getStoredToken() {
        try {
            return trimToken(localStorage.getItem(STORAGE_KEY));
        } catch (_) {
            return '';
        }
    }

    function readMeta() {
        try {
            const raw = localStorage.getItem(META_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (_) {
            return null;
        }
    }

    function saveMeta(meta) {
        try {
            if (meta) localStorage.setItem(META_KEY, JSON.stringify(meta));
            else localStorage.removeItem(META_KEY);
        } catch (_) {}
    }

    function saveStoredToken(token) {
        const value = trimToken(token);
        try {
            if (value) localStorage.setItem(STORAGE_KEY, value);
            else localStorage.removeItem(STORAGE_KEY);
        } catch (_) {}
    }

    function shouldAttachToken(url) {
        const value = String(url || '');
        return value && !value.includes('/api/gate/verify') && !value.includes('/admin');
    }

    function normalizeFetchArgs(input, init) {
        const token = getStoredToken();

        if (input instanceof Request) {
            const url = input.url || '';
            if (!shouldAttachToken(url) || !token) {
                return [input, init];
            }
            const headers = new Headers(input.headers);
            headers.set('X-Gate-Token', token);
            const nextRequest = new Request(input, {
                headers,
                credentials: input.credentials === 'omit' ? 'same-origin' : (input.credentials || 'same-origin'),
            });
            return [nextRequest, init];
        }

        const url = typeof input === 'string'
            ? input
            : (input && typeof input.href === 'string' ? input.href : String(input || ''));

        const nextInit = { ...(init || {}) };
        nextInit.credentials = nextInit.credentials || 'same-origin';

        if (token && shouldAttachToken(url)) {
            const headers = new Headers(nextInit.headers || {});
            headers.set('X-Gate-Token', token);
            nextInit.headers = headers;
        }

        return [url, nextInit];
    }

    async function gateFetch(input, init) {
        const args = normalizeFetchArgs(input, init);
        return window.__pvzhGate._originalFetch(...args);
    }

    function appendTokenToFormData(formData) {
        const token = getStoredToken();
        if (token && formData && typeof formData.set === 'function') {
            formData.set('_gate_token', token);
        }
        return formData;
    }

    function hydrateStatusFromLocal() {
        const token = getStoredToken();
        const meta = readMeta();
        if (!token || !meta) return;

        statusPayload = {
            authenticated: true,
            scope: meta.scope,
            scope_label: meta.scope_label || '已激活',
            can_aux: meta.can_aux !== false,
            can_mod: meta.can_mod !== false,
        };
        updateActivateButton();
    }

    function updateActivateButton() {
        const btn = document.getElementById('pvzh-gate-btn');
        const text = document.getElementById('pvzh-gate-btn-text');
        if (!btn || !text) return;

        btn.classList.remove('text-green-700', 'bg-green-50', 'text-amber-700', 'bg-amber-50', 'text-slate-500');

        if (statusPayload && statusPayload.authenticated) {
            const label = statusPayload.scope_label || '已激活';
            text.textContent = label;
            btn.classList.add('text-green-700', 'bg-green-50');
            btn.title = `已激活：${label}`;
            return;
        }

        if (getStoredToken()) {
            text.textContent = '待验证';
            btn.classList.add('text-amber-700', 'bg-amber-50');
            btn.title = '已保存邀请码，点击验证激活';
            return;
        }

        text.textContent = '激活';
        btn.classList.add('text-slate-500');
        btn.title = '点击输入邀请码激活工具';
    }

    function showModal() {
        const modal = document.getElementById('pvzh-gate-modal');
        const input = document.getElementById('pvzh-gate-input');
        const error = document.getElementById('pvzh-gate-error');
        const status = document.getElementById('pvzh-gate-status');
        if (!modal || !input) return;

        if (error) {
            error.classList.add('hidden');
            error.textContent = '';
        }

        if (status) {
            if (statusPayload && statusPayload.authenticated) {
                status.textContent = `当前已激活：${statusPayload.scope_label || statusPayload.scope}`;
                status.classList.remove('hidden');
            } else if (getStoredToken()) {
                status.textContent = '已保存邀请码，点击下方按钮验证';
                status.classList.remove('hidden');
            } else {
                status.classList.add('hidden');
                status.textContent = '';
            }
        }

        input.value = getStoredToken();
        modal.classList.remove('hidden');
        setTimeout(() => input.focus(), 50);
    }

    function hideModal() {
        const modal = document.getElementById('pvzh-gate-modal');
        if (modal) modal.classList.add('hidden');
    }

    async function refreshStatus() {
        if (!getStoredToken()) {
            statusPayload = null;
            saveMeta(null);
            updateActivateButton();
            return statusPayload;
        }

        try {
            const response = await gateFetch('/api/gate/status');
            const data = await response.json();
            if (data.authenticated) {
                statusPayload = data;
                saveMeta({
                    scope: data.scope,
                    scope_label: data.scope_label,
                    can_aux: data.can_aux,
                    can_mod: data.can_mod,
                    saved_at: Date.now(),
                });
            } else if (!statusPayload || !statusPayload.authenticated) {
                statusPayload = null;
            }
        } catch (_) {
            if (!statusPayload || !statusPayload.authenticated) {
                statusPayload = null;
            }
        }
        updateActivateButton();
        return statusPayload;
    }

    async function verifyToken(token) {
        const clean = trimToken(token);
        const response = await window.__pvzhGate._originalFetch('/api/gate/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ token: clean }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || data.message || '验证失败');
        }

        saveStoredToken(clean);
        statusPayload = {
            authenticated: true,
            scope: data.scope,
            scope_label: data.scope_label,
            can_aux: data.can_aux,
            can_mod: data.can_mod,
        };
        saveMeta({
            scope: data.scope,
            scope_label: data.scope_label,
            can_aux: data.can_aux,
            can_mod: data.can_mod,
            saved_at: Date.now(),
        });
        updateActivateButton();
        return data;
    }

    async function clearActivation() {
        saveStoredToken('');
        saveMeta(null);
        statusPayload = null;
        try {
            await gateFetch('/api/gate/logout', { method: 'POST' });
        } catch (_) {}
        updateActivateButton();
    }

    async function parseGateError(response) {
        if (response.status !== 401 && response.status !== 403) return null;
        try {
            const data = await response.clone().json();
            if (data.code === 'GATE_REQUIRED' || data.code === 'GATE_SCOPE_DENIED') {
                return data.message || data.error || '请先在顶部点击「激活」输入邀请码';
            }
        } catch (_) {}
        return null;
    }

    function bindUi() {
        const btn = document.getElementById('pvzh-gate-btn');
        const submit = document.getElementById('pvzh-gate-submit');
        const clear = document.getElementById('pvzh-gate-clear');
        const backdrop = document.getElementById('pvzh-gate-modal');

        if (btn) btn.addEventListener('click', () => showModal());

        if (submit) {
            submit.addEventListener('click', async () => {
                const input = document.getElementById('pvzh-gate-input');
                const error = document.getElementById('pvzh-gate-error');
                const token = trimToken(input?.value);

                if (!token) {
                    if (error) {
                        error.textContent = '请输入邀请码';
                        error.classList.remove('hidden');
                    }
                    return;
                }

                submit.disabled = true;
                submit.textContent = '验证中...';
                if (error) error.classList.add('hidden');

                try {
                    await verifyToken(token);
                    hideModal();
                } catch (err) {
                    if (error) {
                        error.textContent = err.message || '验证失败';
                        error.classList.remove('hidden');
                    }
                } finally {
                    submit.disabled = false;
                    submit.textContent = '验证并保存';
                }
            });
        }

        if (clear) {
            clear.addEventListener('click', async () => {
                await clearActivation();
                const input = document.getElementById('pvzh-gate-input');
                if (input) input.value = '';
                hideModal();
            });
        }

        if (backdrop) {
            backdrop.addEventListener('click', (event) => {
                if (event.target === backdrop) hideModal();
            });
        }

        document.getElementById('pvzh-gate-input')?.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') submit?.click();
        });
    }

    function boot() {
        bindUi();
        hydrateStatusFromLocal();
        refreshStatus();
    }

    window.__pvzhGate = {
        BUILD,
        _originalFetch: window.fetch.bind(window),
        getToken: getStoredToken,
        saveToken: saveStoredToken,
        clearActivation,
        refreshStatus,
        openModal: showModal,
        appendTokenToFormData,
        parseGateError,
        gateFetch,
    };

    window.fetch = function (input, init) {
        return gateFetch(input, init);
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }

    window.addEventListener('pageshow', () => {
        hydrateStatusFromLocal();
        refreshStatus();
    });
})();