-- 跨平台 AI 社群圖文生成與發布平台 — initial schema
-- Paste into the Supabase SQL Editor and run once.
-- Based on the Notion spec §5, plus: scheduling, title/audience/platforms on posts,
-- permalink on publications, user_settings, generation_feedback.
--
-- Writes all go through the FastAPI backend (service role key, bypasses RLS).
-- The frontend (anon key + user JWT) can only READ its own rows, and can never read social_accounts.

-- ============ shared: auto-update updated_at ============
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ============ 1. social_accounts ============
create table public.social_accounts (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references auth.users(id) on delete cascade,
  platform         text not null check (platform in ('threads', 'instagram')),
  platform_user_id text not null,
  username         text,
  access_token     text not null,            -- backend only; encrypting with Supabase Vault is a later extension
  token_expires_at timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (user_id, platform)
);

-- ============ 2. posts ============
create table public.posts (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references auth.users(id) on delete cascade,
  title             text,                    -- card headline, used in lists (P7)
  goal              text not null,
  tone              text,
  audience          text,
  prompt_candidates jsonb,                   -- the 3 candidates shown on P3
  selected_prompt   jsonb,                   -- {title, angle, hook}
  caption_threads   text,
  caption_instagram text,
  canvas_json       jsonb,                   -- editor canvas: layout, style, image, texts[]
  platforms         text[] not null default '{}',  -- chosen at submit
  status            text not null default 'generating' check (status in (
                      'generating', 'generation_failed', 'editing',
                      'pending_review', 'approved', 'scheduled', 'publishing',
                      'published', 'partially_published', 'publish_failed')),
  generation_error  text,
  approved_at       timestamptz,
  scheduled_at      timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  check (status <> 'scheduled' or scheduled_at is not null)
);
create index posts_user_updated_idx on public.posts (user_id, updated_at desc);   -- P7 list
create index posts_scheduled_idx on public.posts (scheduled_at) where status = 'scheduled';  -- scheduler

-- ============ 3. post_images ============
create table public.post_images (
  id           uuid primary key default gen_random_uuid(),
  post_id      uuid not null references public.posts(id) on delete cascade,
  source       text not null check (source in ('generated', 'uploaded', 'exported')),
  storage_path text not null,
  public_url   text not null,
  created_at   timestamptz not null default now()
);
create index post_images_post_idx on public.post_images (post_id);

-- ============ 4. publications: one row per post + platform ============
create table public.publications (
  id               uuid primary key default gen_random_uuid(),
  post_id          uuid not null references public.posts(id) on delete cascade,
  platform         text not null check (platform in ('threads', 'instagram')),
  status           text not null default 'pending' check (status in ('pending', 'success', 'failed')),
  container_id     text,
  external_post_id text,
  permalink        text,                     -- link shown on P6
  error_message    text,
  published_at     timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (post_id, platform)
);

-- ============ 5. user_settings ============
create table public.user_settings (
  user_id          uuid primary key references auth.users(id) on delete cascade,
  brand_name       text,
  default_tone     text,
  default_audience text,
  sensitive_words  text[] not null default '{未公開產品,內部代號,機密客戶}',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

-- ============ 6. generation_feedback ============
create table public.generation_feedback (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  post_id    uuid not null references public.posts(id) on delete cascade,
  rating     text not null check (rating in ('like', 'neutral', 'dislike')),
  created_at timestamptz not null default now()
);
create index generation_feedback_post_idx on public.generation_feedback (post_id);

-- ============ updated_at triggers ============
create trigger social_accounts_updated_at before update on public.social_accounts
  for each row execute function public.set_updated_at();
create trigger posts_updated_at before update on public.posts
  for each row execute function public.set_updated_at();
create trigger publications_updated_at before update on public.publications
  for each row execute function public.set_updated_at();
create trigger user_settings_updated_at before update on public.user_settings
  for each row execute function public.set_updated_at();

-- ============ RLS: frontend reads its own rows; all writes go through the backend ============
alter table public.social_accounts     enable row level security;  -- no policies: tokens never reach the frontend
alter table public.posts               enable row level security;
alter table public.post_images         enable row level security;
alter table public.publications        enable row level security;
alter table public.user_settings       enable row level security;
alter table public.generation_feedback enable row level security;

create policy "read own posts" on public.posts
  for select to authenticated
  using (user_id = auth.uid());

create policy "read own post images" on public.post_images
  for select to authenticated
  using (exists (select 1 from public.posts p where p.id = post_id and p.user_id = auth.uid()));

create policy "read own publications" on public.publications
  for select to authenticated
  using (exists (select 1 from public.posts p where p.id = post_id and p.user_id = auth.uid()));

create policy "read own settings" on public.user_settings
  for select to authenticated
  using (user_id = auth.uid());

create policy "read own feedback" on public.generation_feedback
  for select to authenticated
  using (user_id = auth.uid());

-- ============ Storage: public image bucket (Threads / IG fetch images from public URLs) ============
insert into storage.buckets (id, name, public)
values ('post-images', 'post-images', true)
on conflict (id) do nothing;

-- The frontend may only upload under post-images/<own user id>/...
create policy "upload to own folder" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'post-images' and (storage.foldername(name))[1] = auth.uid()::text);
