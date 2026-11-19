# Rollback points

## Before the new homepage film (2026-11-19)

The homepage film was changed from the old brand film (and a Vimeo page link
saved in Admin → Content → Hero) to the owner's "MH Brand Film – Wide version"
in four device-specific versions. To return to the exact previous website:

**Backup of the code:** branch `backup/before-new-hero-film-2026-11-19`
(commit `ef82c0c`, the version that was live just before the change).

**Backup of the admin content:** `backups/2026-11-19-hero-admin-content-before-new-film.json`
— the homepage `page_content` rows of section `hero` at that time
(`video` = `https://vimeo.com/1195103113`, `tagline` = "Fragrance is not worn. It is lived.").

### Restore (developer, ~5 minutes)
1. Code: deploy the backup branch — either merge/revert on `main`
   (`git revert <commits after ef82c0c>`), or point the Railway Dockerfile clone at
   the branch: `git clone --depth 1 -b backup/before-new-hero-film-2026-11-19 …`,
   with a new `CACHEBUST` (see `docs/DEPLOY.md`).
2. Admin content: in Admin → Content → Main page → Hero, paste back the old
   `video` value from the JSON file and Save (or upsert the rows from the JSON
   into `page_content`). The extra fields added by the change
   (`video_mobile`, `video_tablet`, `video_phone`, `poster*`) are simply ignored
   by the old code.
3. The old film files are untouched: `assets/videos/web/brand-film-silent.{mp4,webm}`,
   `brand-film-audio.m4a`, and Supabase `page-media/defaults/main-hero-brand-film.mp4`.

The new film files live in Supabase Storage `page-media/hero/` and can stay.
