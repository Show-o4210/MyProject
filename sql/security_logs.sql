-- =============================================================================
-- PVZH 工具箱 · 安全审计表 security_logs
-- 用法：在 Supabase → SQL Editor 中整段执行。
--
-- 现象：Render 日志出现
--   [SECURITY] Failed to log to Supabase:
--   {'message': 'permission denied for table security_logs', 'code': '42501', ...}
-- 原因几乎总是：表未建 / RLS 未开策略 / 未 GRANT INSERT 给 anon。
-- 后端 SUPABASE_KEY 使用 anon key 写入（与 feedbacks 相同模式）。
--
-- 会 DROP 旧表后重建（旧审计数据会清空；需保留请先导出）。
-- =============================================================================

-- 1) 删旧表
DROP TABLE IF EXISTS public.security_logs CASCADE;

-- 2) 建表（字段与 security.py log_security_event 写入一致）
CREATE TABLE public.security_logs (
    id              bigserial PRIMARY KEY,
    ip              text NOT NULL DEFAULT '',
    user_agent      text NOT NULL DEFAULT '',
    reason          text NOT NULL DEFAULT '',
    severity        text NOT NULL DEFAULT 'medium'
                    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    request_path    text NOT NULL DEFAULT '',
    request_method  text NOT NULL DEFAULT '',
    timestamp       timestamptz NOT NULL DEFAULT now(),
    blocked         boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.security_logs IS '安全拦截/可疑请求审计日志';
COMMENT ON COLUMN public.security_logs.blocked IS 'true=已拦截；false=仅记录未拦截';
COMMENT ON COLUMN public.security_logs.severity IS 'low | medium | high | critical';

-- 3) 索引：按时间 / IP / 严重级别查询
CREATE INDEX security_logs_timestamp_idx
    ON public.security_logs (timestamp DESC);

CREATE INDEX security_logs_ip_timestamp_idx
    ON public.security_logs (ip, timestamp DESC);

CREATE INDEX security_logs_blocked_timestamp_idx
    ON public.security_logs (blocked, timestamp DESC)
    WHERE blocked = true;

-- 4) RLS
ALTER TABLE public.security_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "security_logs_anon_insert" ON public.security_logs;
DROP POLICY IF EXISTS "security_logs_anon_select" ON public.security_logs;
DROP POLICY IF EXISTS "security_logs_service_all" ON public.security_logs;

-- 4a) anon / authenticated：只允许 INSERT（后端用 anon key 写审计）
--     不开放公开 SELECT，避免 anon key 泄露后被批量拉取审计数据
CREATE POLICY "security_logs_anon_insert"
    ON public.security_logs
    FOR INSERT
    TO anon, authenticated
    WITH CHECK (
        char_length(COALESCE(ip, '')) <= 128
        AND char_length(COALESCE(user_agent, '')) <= 2000
        AND char_length(COALESCE(reason, '')) <= 500
        AND severity IN ('low', 'medium', 'high', 'critical')
        AND char_length(COALESCE(request_path, '')) <= 2000
        AND char_length(COALESCE(request_method, '')) <= 16
    );

-- 4b) 若需要 /security/stats 用 anon key 读今日抽样，取消下面策略的注释。
--     默认关闭：stats 在无 SELECT 权限时会返回 stats unavailable，不影响拦截本身。
-- CREATE POLICY "security_logs_anon_select"
--     ON public.security_logs
--     FOR SELECT
--     TO anon, authenticated
--     USING (true);

-- 5) 表级 GRANT
REVOKE ALL ON TABLE public.security_logs FROM PUBLIC;
REVOKE ALL ON TABLE public.security_logs FROM anon;
REVOKE ALL ON TABLE public.security_logs FROM authenticated;

GRANT INSERT ON TABLE public.security_logs TO anon;
GRANT INSERT ON TABLE public.security_logs TO authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.security_logs_id_seq TO anon;
GRANT USAGE, SELECT ON SEQUENCE public.security_logs_id_seq TO authenticated;

-- 若启用了上面的 anon SELECT 策略，再执行：
-- GRANT SELECT ON TABLE public.security_logs TO anon, authenticated;

GRANT ALL ON TABLE public.security_logs TO service_role;
GRANT ALL ON SEQUENCE public.security_logs_id_seq TO service_role;

-- =============================================================================
-- 自检
-- =============================================================================
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_schema = 'public' AND table_name = 'security_logs'
-- ORDER BY ordinal_position;
--
-- -- 模拟 anon 插入（应成功）：
-- SET ROLE anon;
-- INSERT INTO public.security_logs
--   (ip, user_agent, reason, severity, request_path, request_method, timestamp, blocked)
-- VALUES
--   ('0.0.0.0', 'sql-test', 'permission_self_check', 'low', '/health', 'GET', now(), false);
-- RESET ROLE;
--
-- -- 模拟 anon 查询（默认应失败 / 无 SELECT）：
-- SET ROLE anon;
-- SELECT * FROM public.security_logs LIMIT 1;
-- RESET ROLE;
