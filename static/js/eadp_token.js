/**
 * EADP 凭证共享逻辑：Token 支持手动输入或 data/token.dat 自动读取；
 * Persona ID 始终由用户手动填写，不从凭证文件解析。
 */
(function (global) {
    'use strict';

    function createAuthForm() {
        return {
            auth_mode: 'auto',
            token: '',
            persona_id: '',
            refresh_token: '',
            expires_at: null,
            auto_refresh: true,
            credential_source: 'data/token.dat',
            token_valid: null,
            expires_at_text: '',
            has_refresh_token: false,
            stored_loaded: false,
            stored_error: '',
        };
    }

    function formatExpiresAt(ts) {
        if (!ts) return '';
        try {
            return new Date(Number(ts) * 1000).toLocaleString('zh-CN');
        } catch (e) {
            return '';
        }
    }

    async function readJsonSafely(response) {
        const text = await response.text();
        try {
            return JSON.parse(text);
        } catch (e) {
            return { success: false, error: text || `请求失败（状态码: ${response.status}）` };
        }
    }

    function applyParsedCredentials(form, data) {
        form.token = data.access_token || '';
        form.refresh_token = data.refresh_token || '';
        form.expires_at = data.expires_at ?? null;
        form.expires_at_text = data.expires_at_text || formatExpiresAt(data.expires_at);
        form.token_valid = data.token_valid;
        form.has_refresh_token = Boolean(data.has_refresh_token || data.refresh_token);
        form.credential_source = data.source || 'data/token.dat';
        form.stored_loaded = true;
        form.stored_error = '';
        if (form.has_refresh_token) {
            form.auto_refresh = true;
        }
    }

    async function loadStoredCredentials() {
        const response = await fetch('/api/eadp/stored-credentials');
        return readJsonSafely(response);
    }

    async function refreshToken(refreshTokenValue) {
        const response = await fetch('/api/eadp/refresh-token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshTokenValue }),
        });
        return readJsonSafely(response);
    }

    function buildAuthPayload(form) {
        const payload = {
            auth_mode: form.auth_mode || 'manual',
            token: (form.token || '').trim(),
            persona_id: (form.persona_id || '').trim(),
        };

        if (form.auth_mode === 'auto') {
            payload.refresh_token = (form.refresh_token || '').trim();
            payload.expires_at = form.expires_at;
            payload.auto_refresh = Boolean(form.auto_refresh);
        }

        return payload;
    }

    function validateAuthForm(form) {
        if (form.auth_mode === 'auto') {
            if (!form.stored_loaded && !form.token) {
                return '本地凭证加载失败，请检查 data/token.dat 或切换到手动输入';
            }
        } else if (!form.token) {
            return '请填写 EADP-AUTH-TOKEN';
        }

        if (!form.persona_id) {
            return '请手动填写 EADP-PERSONA-ID（不会从凭证文件自动读取）';
        }

        if (form.auth_mode === 'auto' && form.auto_refresh && !form.refresh_token) {
            return '本地凭证中未找到 refresh_token，无法自动续期，请关闭自动续期或更新 data/token.dat';
        }

        return null;
    }

    function applyTokenMeta(form, meta) {
        if (!meta) return;
        if (meta.access_token) {
            form.token = meta.access_token;
        }
        if (meta.refresh_token) {
            form.refresh_token = meta.refresh_token;
        }
        if (meta.expires_at !== undefined && meta.expires_at !== null) {
            form.expires_at = meta.expires_at;
            form.expires_at_text = formatExpiresAt(meta.expires_at);
        }
        if (meta.token_valid_after !== undefined) {
            form.token_valid = meta.token_valid_after;
        }
    }

    async function initAutoCredentials(form, options) {
        const opts = options || {};
        const setError = typeof opts.setError === 'function' ? opts.setError : null;

        if (form.auth_mode !== 'auto') {
            return { success: true, skipped: true };
        }

        try {
            const data = await loadStoredCredentials();
            if (!data.success) {
                form.stored_loaded = false;
                form.stored_error = data.error || '读取本地凭证失败';
                if (setError) setError(form.stored_error);
                return data;
            }
            applyParsedCredentials(form, data);
            return data;
        } catch (err) {
            form.stored_loaded = false;
            form.stored_error = `读取本地凭证失败：${err.message}`;
            if (setError) setError(form.stored_error);
            return { success: false, error: form.stored_error };
        }
    }

    function switchAuthMode(form, mode) {
        form.auth_mode = mode;
        if (mode === 'manual') {
            form.stored_loaded = false;
            form.stored_error = '';
            form.token_valid = null;
            form.expires_at_text = '';
        }
    }

    global.EadpToken = {
        createAuthForm,
        formatExpiresAt,
        readJsonSafely,
        applyParsedCredentials,
        loadStoredCredentials,
        refreshToken,
        buildAuthPayload,
        validateAuthForm,
        applyTokenMeta,
        initAutoCredentials,
        switchAuthMode,
    };
})(window);