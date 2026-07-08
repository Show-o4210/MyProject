-- =============================================================================
-- PVZH 工具箱 · 意见反馈表 feedbacks
-- 用法：在 Supabase → SQL Editor 中整段执行。
-- 会 DROP 旧表后重建（旧数据会清空，请先自行导出若需要保留）。
-- =============================================================================

-- 1) 删旧表（级联依赖策略一并清掉）
DROP TABLE IF EXISTS public.feedbacks CASCADE;

-- 2) 建表
CREATE TABLE public.feedbacks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type        text NOT NULL
                CHECK (type IN ('bug', 'feature', 'other')),
    content     text NOT NULL
                CHECK (char_length(content) > 0 AND char_length(content) <= 500),
    contact     text NOT NULL DEFAULT ''
                CHECK (char_length(contact) <= 100),
    ua_info     jsonb NOT NULL DEFAULT '{}'::jsonb,
    status      text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'read', 'archived')),
    created_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.feedbacks IS '用户意见反馈';
COMMENT ON COLUMN public.feedbacks.type IS 'bug | feature | other';
COMMENT ON COLUMN public.feedbacks.ua_info IS 'JSON: { ip, user_agent }';
COMMENT ON COLUMN public.feedbacks.status IS 'pending | read | archived';

-- 3) 索引：按状态 / 时间查未读
CREATE INDEX feedbacks_status_created_at_idx
    ON public.feedbacks (status, created_at DESC);

CREATE INDEX feedbacks_created_at_idx
    ON public.feedbacks (created_at DESC);

-- 4) RLS：开启行级安全
ALTER TABLE public.feedbacks ENABLE ROW LEVEL SECURITY;

-- 先清掉可能残留的同名策略（重建场景）
DROP POLICY IF EXISTS "feedbacks_anon_insert" ON public.feedbacks;
DROP POLICY IF EXISTS "feedbacks_service_all" ON public.feedbacks;
DROP POLICY IF EXISTS "feedbacks_authenticated_select" ON public.feedbacks;

-- 4a) 匿名 / 已登录客户端：只允许 INSERT（后端用 anon key 写入）
--     不开放 SELECT/UPDATE/DELETE，避免任何人用 anon key 把反馈列表读走
CREATE POLICY "feedbacks_anon_insert"
    ON public.feedbacks
    FOR INSERT
    TO anon, authenticated
    WITH CHECK (
        type IN ('bug', 'feature', 'other')
        AND char_length(content) > 0
        AND char_length(content) <= 500
        AND char_length(COALESCE(contact, '')) <= 100
        AND status = 'pending'
    );

-- 4b) service_role：完整权限（Dashboard / service_role key 绕过 RLS，
--     这里仍写策略便于权限审计清晰；service_role 默认可绕过 RLS）
--     若你只用 Dashboard 看数据，可不依赖此策略。

-- 5) 授权：表级 GRANT
--    注意：仅 GRANT INSERT 给 anon；SELECT 不给 anon
REVOKE ALL ON TABLE public.feedbacks FROM PUBLIC;
REVOKE ALL ON TABLE public.feedbacks FROM anon;
REVOKE ALL ON TABLE public.feedbacks FROM authenticated;

GRANT INSERT ON TABLE public.feedbacks TO anon;
GRANT INSERT ON TABLE public.feedbacks TO authenticated;

-- service_role 在 Supabase 中通常已有 bypass；为保险显式授予
GRANT ALL ON TABLE public.feedbacks TO service_role;

-- 6) 可选：给自己一个只读角色查看反馈（在 Dashboard 用 SQL 查即可，
--    一般不需要额外 role。Dashboard 用 postgres/service 身份，可直接 SELECT。）

-- =============================================================================
-- 自检（执行后可在 SQL Editor 跑下面几条确认）
-- =============================================================================
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_schema = 'public' AND table_name = 'feedbacks'
-- ORDER BY ordinal_position;
--
-- SELECT polname, polcmd, polroles::regrole[]
-- FROM pg_policy
-- WHERE polrelid = 'public.feedbacks'::regclass;
--
-- -- 模拟 anon 插入（应成功）：
-- SET ROLE anon;
-- INSERT INTO public.feedbacks (type, content, contact, ua_info, status)
-- VALUES ('bug', 'test from sql editor', '', '{"ip":"0.0.0.0","user_agent":"sql"}'::jsonb, 'pending');
-- RESET ROLE;
--
-- -- 模拟 anon 查询（应失败 / 0 行，因无 SELECT 权限）：
-- SET ROLE anon;
-- SELECT * FROM public.feedbacks;
-- RESET ROLE;
