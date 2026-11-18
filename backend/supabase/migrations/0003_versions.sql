-- Every successful AI generation of a post is kept so the editor can switch between them
-- (「‹ 2/3 ›」). Each entry: {id, created_at, mode, title, caption_threads, caption_instagram, canvas_json}.
-- Written only by the backend; capped at 10 entries. Run after 0002_templates.sql.

alter table public.posts add column versions jsonb not null default '[]'::jsonb;
