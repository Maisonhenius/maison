# Nano Banana asset workflow

Referenced from `CLAUDE.md`. Only needed when editing brand images via the `nano-banana`
skill, which is itself explicitly invoked — so the full workflow lives here rather than in
the auto-loaded CLAUDE.md.

## Workflow

1. **Pass the existing image as input** — never generate from scratch when editing. The skill needs the original to preserve composition.
2. **Save with a distinct filename** (e.g. `patchouli-green.webp`, `card-parisian-v2.webp`). Never overwrite the original.
3. **Verify dimensions + format** — Nano Banana sometimes returns JPEG bytes with a `.webp` extension. Run `webpinfo` (or `sips`) to check, re-encode with `cwebp -q 78 -resize WIDTH 0` if wrong.
4. **Promote to canonical name** by renaming after approval: `mv original.webp original-backup.webp && mv new.webp original.webp`. The `-backup` suffix is descriptive (e.g. `coffee-beans.webp`, `card-parisian-original.webp`). Backups stay in git as fallback.
5. **Path renaming preserves Jinja captions**: templates like `products/detail.html` build the ingredient name from the filename via `{{ img | replace('-', ' ') | title }}`. So `patchouli-green.webp` renders as "Patchouli Green" — promote to canonical `patchouli.webp` to keep "Patchouli" as the display name.
6. **Editing product hero/card images** (e.g. swapping props): Pass the existing bottle/card image as input and describe what to replace. Preserves the bottle, cap, composition, and lighting while swapping ingredients. Always regenerate BOTH bottle hero AND card image when props change.

## Current AI-edited assets (with backups available)

`patchouli.webp` (backup: `patchouli-wilted.webp`, 4K source: `patchouli-fresh-4k.webp`), `aldehydes.webp` (4K source: `aldehydes-nolabel-4k.webp`), `cool-spices.webp` (4K source: `cool-spices-4k.webp`), `coffee-with-cream.webp` (copy of `coffee.webp`), `moldavian-rose.webp` (copy of `rose.webp`), `coffee.webp` (backup: `coffee-beans.webp`), `card-parisian.webp` (backup: `card-parisian-original.webp`), `card-out-of-control.webp` (backup: `card-out-of-control-star-anise.webp`), `bottle-out-of-control.webp` (backup: `bottle-out-of-control-star-anise.webp`), `Maison Henius - universe.webp` (sibling of original `Maison Henius.webp`), `Story.webp` (backup: `Story-original.webp`, 4K source: `Story-edited.webp`), `craft-collection.webp` (4K source: `big-bottle-design-4k.webp`), **`bottle-{slug}.webp` × 5** for all products (4K JPEG masters at `bottle-{slug}-hero-4k.png`, gitignored; fallback is the original bottle-alone `{Product Name}.webp` still in folder).

The bottle heroes were generated with the existing bottle as input-1 and `big-bottle-design-4k.webp` as the style-reference input-2 — that two-image pattern is what locked the Ionic cap + label fidelity while replacing the backdrop and adding travertine pedestal + ingredient props.
