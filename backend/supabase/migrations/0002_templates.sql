-- User-provided background templates (圖片模板). Run after 0001_init.sql.
-- Files live in the existing public bucket under post-images/<user_id>/templates/<uuid>.<ext>,
-- which the "upload to own folder" storage policy already allows.

create table public.templates (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  name         text not null,
  storage_path text not null,
  public_url   text not null,
  created_at   timestamptz not null default now()
);
create index templates_user_idx on public.templates (user_id, created_at desc);

alter table public.templates enable row level security;
create policy "read own templates" on public.templates
  for select to authenticated
  using (user_id = auth.uid());

-- A post that uses a template records it as its background image.
alter table public.post_images drop constraint post_images_source_check;
alter table public.post_images add constraint post_images_source_check
  check (source in ('generated', 'uploaded', 'exported', 'template'));
