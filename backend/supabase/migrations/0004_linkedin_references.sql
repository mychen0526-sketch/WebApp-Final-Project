-- LinkedIn publishing + real news pictures on cards. Run after 0003_versions.sql.
--
-- 1. LinkedIn becomes a third platform: its own caption, account binding and publication rows.
-- 2. A news picture found by 趨勢情報 search is stored as post_images.source = 'reference'.
--    The article itself (title, url, source, image_url) lives in posts.canvas_json.reference.

alter table public.posts add column caption_linkedin text;

alter table public.social_accounts drop constraint social_accounts_platform_check;
alter table public.social_accounts add constraint social_accounts_platform_check
  check (platform in ('threads', 'instagram', 'linkedin'));

alter table public.publications drop constraint publications_platform_check;
alter table public.publications add constraint publications_platform_check
  check (platform in ('threads', 'instagram', 'linkedin'));

alter table public.post_images drop constraint post_images_source_check;
alter table public.post_images add constraint post_images_source_check
  check (source in ('generated', 'uploaded', 'exported', 'template', 'reference'));
