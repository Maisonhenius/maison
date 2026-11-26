# Journal (blog)

Public pages: `/journal` (featured story + grid + theme filter + email sign-up),
`/journal/{slug}` (one article), `/journal/feed.xml` (RSS). Admin: **Admin → Journal**.
Code: `server/journal.py` (text-to-HTML renderer, validation), routes at the end of
`server/app.py`, templates in `server/templates/journal/` and `server/templates/admin/journal*.html`.

## One-time setup (before or right after the first deploy)

The articles live in the Supabase table `blog_posts`, created by migration 013.
Until it is run, the public Journal shows the six launch articles from
`server/journal_seed.py`, and saving in Admin → Journal shows
"The Journal database is not set up yet".

Easiest way (no tools needed):

1. Open Supabase → project `rmliognhrimbcwbyjikf` → **SQL Editor** → **New query**.
2. Paste the whole of `server/migrations/013_blog_posts.sql` and press **Run**.
3. Open Admin → Journal. The six articles appear and can now be edited.

Or from a computer with the project: `cd server && python migrations/run_migration.py 013_blog_posts.sql`
(use the session pooler host, see CLAUDE.md → Gotchas). The file is safe to run twice:
the table is only created once, and an article whose web address already exists is skipped.

## Writing articles (Admin → Journal)

- **No limit** on the number of articles. Each article is a draft until its
  status is set to Published. A Published article with a future date is
  **scheduled**: it appears on the site automatically on that date.
- Article text uses simple marks (shown under the text box in the editor):
  `## Heading`, `### Smaller heading`, `**bold**`, `*italic*`, `[link text](/products/parisian)`,
  `- bullet`, `1. numbered`, `> quote`, `---` divider, and
  `![picture description](picture-link "caption")` on its own line. The **＋ Picture**
  button uploads a picture and writes this line for you. Typed HTML is shown as text,
  never run, so nothing pasted can break the page.
- Pictures upload to Supabase Storage (`page-media` bucket). Use landscape pictures,
  about 1600 × 900 px, WebP or JPEG, under 300 KB.
- **SEO**: SEO title (≤ 60 characters), meta description (≤ 155), focus keyword and
  secondary keywords. Empty fields fall back to the title / summary.
- **Social media**: share picture (defaults to the main picture) and a ready-to-paste
  caption for Instagram and TikTok.
- **Related fragrances**: product cards shown at the end of the article.

## What the site does automatically

- Each live article is added to `/sitemap.xml` (with its last-changed date) and to
  the RSS feed `/journal/feed.xml`.
- Each article page has its own title, meta description, canonical link, Open Graph
  and X/Twitter tags (big picture previews on WhatsApp, Facebook, LinkedIn, X, Pinterest),
  and `BlogPosting` + `BreadcrumbList` structured data for Google.
- Share buttons on each article (phone share sheet, WhatsApp, Facebook, X, Pinterest,
  LinkedIn, email, copy link). The Journal's email sign-up saves to Admin → Messages.

## After launch

- Submit `https://www.maisonhenius.com/sitemap.xml` in Google Search Console once,
  so new articles are found quickly.
- `server/journal_seed.py` is only the fallback / first content. After migration 013
  the database is the source of truth: edit articles in the admin, not in the file.
  If you change the seed file, regenerate the SQL with `python migrations/gen_013_seed.py`.
