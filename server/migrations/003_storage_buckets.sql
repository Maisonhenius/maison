-- Migration 003: storage buckets for admin-uploaded media.
-- product-images: hero/card/mood/explore/bottle/ingredient images for products.
-- page-media:     editable images/videos for the Main + Universe pages (CMS).

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'product-images',
  'product-images',
  true,
  10485760,  -- 10 MB per file
  ARRAY['image/webp', 'image/jpeg', 'image/png']
)
ON CONFLICT (id) DO UPDATE
SET public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'page-media',
  'page-media',
  true,
  52428800,  -- 50 MB per file (videos)
  ARRAY['image/webp', 'image/jpeg', 'image/png', 'video/mp4', 'video/webm']
)
ON CONFLICT (id) DO UPDATE
SET public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

-- Public read for both buckets so the front-end can render uploaded media
-- without needing auth tokens. Writes still require service-role (which the
-- backend uses) — no anon/authenticated user can upload directly.
DROP POLICY IF EXISTS "product images public read" ON storage.objects;
CREATE POLICY "product images public read"
  ON storage.objects FOR SELECT
  USING (bucket_id = 'product-images');

DROP POLICY IF EXISTS "page media public read" ON storage.objects;
CREATE POLICY "page media public read"
  ON storage.objects FOR SELECT
  USING (bucket_id = 'page-media');
