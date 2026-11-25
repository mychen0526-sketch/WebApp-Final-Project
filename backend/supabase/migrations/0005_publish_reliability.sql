-- Publishing reliability, account authorization state and persisted preferences. Run after 0004.
--
-- 1. publications.error_code: why a platform failed (sensitive / not_connected / auth / transient /
--    uncertain / rejected / internal). "uncertain" means the post may already be live, so the
--    backend searches the platform before retrying instead of posting twice.
-- 2. social_accounts.auth_error: set when a platform says the token was revoked or is invalid;
--    the account then counts as "needs reconnect" until the user connects again.
--    access_token now holds an encrypted value ("enc:v1:…", see app/services/tokens.py).
-- 3. user_settings.default_platforms: the default publish targets (偏好設定 → 預設發布目的地).
-- 4. Indexes for the scheduler's sweeps (stuck publishing posts, tokens about to expire).

alter table public.publications add column if not exists error_code text
  check (error_code is null or error_code in
    ('sensitive', 'not_connected', 'auth', 'transient', 'uncertain', 'rejected', 'internal'));

alter table public.social_accounts add column if not exists auth_error text;

alter table public.user_settings add column if not exists default_platforms text[];

create index if not exists posts_status_updated_idx on public.posts (status, updated_at);
create index if not exists social_accounts_expires_idx on public.social_accounts (token_expires_at);
create index if not exists generation_feedback_user_idx on public.generation_feedback (user_id, created_at desc);
