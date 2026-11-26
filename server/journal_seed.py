"""The six launch articles of the Maison Henius Journal.

Used twice:
  1. `migrations/013_blog_posts.sql` is generated from this list
     (`python migrations/gen_013_seed.py`) so the database starts with them.
  2. If the blog_posts table is not reachable, the public Journal shows these
     so the page never appears empty.
After launch the database is the source of truth: edit articles in
Admin -> Journal, not here.
"""

L = "/static/assets/pictures/Jordan%20Landscape/"
C = "/static/assets/pictures/Collection%20%26%20Fragrances/"
I = "/static/assets/pictures/ingredients/"

SEED_POSTS = [
    {
        "slug": "jordanian-niche-perfume-wadi-rum",
        "title": "The Minute the Desert Exhales",
        "category": "Origins",
        "excerpt": "Maison Henius began with one smell: warm Wadi Rum stone letting go of the day into cool evening air. This is the story of that minute.",
        "hero_image": L + "Wadi%20Rum.webp",
        "hero_alt": "Wadi Rum desert at dusk, the inspiration for a Jordanian niche perfume",
        "hero_caption": "Wadi Rum, southern Jordan.",
        "seo_title": "Jordanian Niche Perfume Born in Wadi Rum",
        "meta_description": "How Wadi Rum's warm stone at dusk became a Jordanian niche perfume house. The origin story of Maison Henius and its artisan fragrances.",
        "focus_keyword": "Jordanian niche perfume",
        "secondary_keywords": "niche perfume Jordan, artisan perfume, Wadi Rum scent, Arabian niche fragrance",
        "tags": "Wadi Rum, Jordan, origin story, artisan perfume",
        "related_products": "velvet-waterfall, oud-passion",
        "cta_label": "Discover Velvet Waterfall",
        "cta_url": "/products/velvet-waterfall",
        "social_caption": "There is a minute in Wadi Rum when the desert exhales. Warm stone, cool air, the edge of dusk. Maison Henius was born from that minute. Read the story on our Journal, link in bio.\n\n#MaisonHenius #NichePerfume #WadiRum #Jordan #ArtisanPerfume #PerfumeLovers #FragranceCommunity",
        "is_featured": True,
        "published_at": "2026-11-24T09:00:00+00:00",
        "body": """There is a minute in Wadi Rum that most visitors miss. It is where our Jordanian niche perfume house began.

The sun has gone, but the sky has not yet decided to be night. The sandstone has held the heat of the whole day. Then the air turns cool, and the stone lets go. Warmth rises from the rock into the evening. For a moment, the desert exhales.

Maison Henius was born from that minute.

## One smell, chased for years

The founder did not set out to build a perfume house. The founder set out to keep one smell: warm stone releasing into cool air, at the edge of dusk.

It cannot be bottled directly. There is no "essence of Wadi Rum" on any perfumer's shelf. So it had to be built, note by note, from materials that carry the same feeling: mineral, warm, quiet, lasting.

That search became a method. Every Maison Henius fragrance still begins the same way. Not with a trend. With a memory.

![Red sandstone canyon walk in Wadi Rum](""" + L + """universe-canyon.webp "The canyon walk, where stone holds the warmth of the day.")

## Why the desert, and why the garden

Jordan holds two worlds a few hours apart. In the north, the Jordan Valley is green, with fig trees, wild herbs and soft evening scents. In the south, Wadi Rum is ochre sand and mineral silence.

The house lives between the two. Lush and arid. Fleeting and lasting. Intimacy and infinity. You will find both sides in every bottle: a garden that opens first, a desert that stays.

![A Jordan Valley garden at evening](""" + L + """universe-garden.webp "The garden: the other half of every Maison Henius fragrance.")

## Memory over product

We make our fragrances in France, with French craftsmanship. But the first idea of each one is always Jordanian: a place, a light, a moment worth returning to.

This is why we put memory before product, and emotion before visibility. A perfume that only impresses is forgotten by evening. A perfume that resonates is remembered years later.

> We do not seek to impress. We seek to resonate.

## Begin where we began

If you want to smell the desert at dusk, start with [Velvet Waterfall](/products/velvet-waterfall): saffron, incense and pepper over cedarwood and vetiver. Born from stillness. Felt in motion.

Or [read our full story](/story) in the Universe of Maison Henius.""",
    },
    {
        "slug": "the-scent-of-a-place",
        "title": "The Scent of a Place: When Memories Become Fragrance",
        "category": "Philosophy",
        "excerpt": "The scent of a place can bring it back in seconds. How Maison Henius turns memories of Jordan into niche perfume you can wear.",
        "hero_image": L + "Story.webp",
        "hero_alt": "The scent of a place: the Jordan landscape behind Maison Henius niche perfume",
        "hero_caption": "",
        "seo_title": "The Scent of a Place: Memory & Niche Perfume",
        "meta_description": "The scent of a place can bring it back in seconds. How Maison Henius turns memories of Jordan into niche perfume you can wear.",
        "focus_keyword": "scent of a place",
        "secondary_keywords": "scent memory perfume, niche perfume, memory fragrance, perfume inspired by places, Jordanian perfume",
        "tags": "scent and memory, philosophy, Jordan, niche perfume",
        "related_products": "velvet-waterfall, parisian, out-of-control",
        "cta_label": "Enter the collection",
        "cta_url": "/shop",
        "social_caption": "Close your eyes and think of a place you love. Chances are, you smell it before you see it. That is the power of scent memory, and the reason Maison Henius exists. New on the Journal.\n\n#MaisonHenius #ScentMemory #NichePerfume #PerfumeInspiredByPlaces #Jordan #FragranceLovers",
        "is_featured": False,
        "published_at": "2026-11-24T08:00:00+00:00",
        "body": """Close your eyes and think of a place you love, and notice what returns first: the scent of a place.

Chances are, you do not see it first. You smell it. Jasmine on a warm wall. Coffee in a grandmother's kitchen. Rain on dry stone. Before the picture arrives, the scent is already there.

This is the quiet power every niche perfume house works with. At Maison Henius, it is the whole reason we exist.

## Why smell remembers better than sight

Of all our senses, smell has the most direct road to memory and emotion. It does not stop to explain itself. It simply takes you back.

This is why a scent can return you to a street you walked twenty years ago, in a single breath. You do not remember the place. You are there again.

A photograph shows you a memory. A fragrance lets you live inside it.

![The perfumer's atelier](""" + L + """universe-atelier.webp "The atelier, where memories are rebuilt note by note.")

## Building a place, note by note

You cannot bottle a place. There is no ready-made "smell of Wadi Rum" or "smell of a Paris morning". So a memory has to be rebuilt from raw materials that carry the same feeling.

This is how we work:

1. **Start with one moment, not an idea.** One light, one hour, one breath of air.
2. **Find what it felt like.** Warm or cool? Still or moving? Sweet or mineral?
3. **Choose materials that carry that feeling.** Saffron and incense for desert warmth. Fig for a garden at evening. Coffee and croissant for a morning far from home.
4. **Let it unfold slowly.** A memory does not arrive all at once, so neither does our fragrance.

![Fresh fig](""" + I + """fig.webp "Fig, the heart of Out of Control.")

## Five places, five memories

Every fragrance in our Beyond Borders collection is a place you can wear.

- [Velvet Waterfall](/products/velvet-waterfall): the stillness of the desert, and the calm of the camel crossing it.
- [Oud Passion](/products/oud-passion): a rose garden at first light, deepening into oud and leather.
- [Oh My Dear!](/products/oh-my-dear): the closeness of skin, and a memory you keep like a jewel.
- [Parisian](/products/parisian): a Jordanian morning, remembered through a Parisian window.
- [Out of Control](/products/out-of-control): fig, coconut and spice under a night that is already yours.

## Why memory makes a better perfume

Mass fragrance is designed to be liked by everyone in ten seconds. Niche perfume is designed to mean something to someone for years.

A fragrance built on a memory has a story under it. You feel it even if no one tells you. That is why we put memory before product, and emotion before visibility.

> We do not seek to impress. We seek to resonate.

## Your place, your scent

Which place would you carry with you, if you could? Find the fragrance that remembers it, or [read our story](/story).""",
    },
    {
        "slug": "niche-perfume-collection-beyond-borders",
        "title": "Between Garden and Desert: Jordan in Five Fragrances",
        "category": "The Collection",
        "excerpt": "Five niche eaux de parfum made in France and rooted in Jordan. Meet Oud Passion, Oh My Dear!, Velvet Waterfall, Parisian and Out of Control.",
        "hero_image": C + "craft-collection.webp",
        "hero_alt": "Beyond Borders niche perfume collection by Maison Henius",
        "hero_caption": "The Beyond Borders collection.",
        "seo_title": "Niche Perfume Collection: Beyond Borders, Jordan",
        "meta_description": "Meet our niche perfume collection: five eaux de parfum made in France, rooted in Jordan, with oud, saffron, suede, coffee and fig.",
        "focus_keyword": "niche perfume collection",
        "secondary_keywords": "oud perfume, saffron perfume, luxury eau de parfum",
        "tags": "Beyond Borders, collection, oud, saffron",
        "related_products": "oud-passion, oh-my-dear, velvet-waterfall, parisian, out-of-control",
        "cta_label": "Enter the collection",
        "cta_url": "/shop",
        "social_caption": "Five fragrances. Five journeys. One house rooted in Jordan and made in France. Meet the Beyond Borders collection on our Journal.\n\n#MaisonHenius #BeyondBorders #NichePerfume #OudPerfume #SaffronPerfume #LuxuryPerfume #PerfumeCollection",
        "is_featured": False,
        "published_at": "2026-11-24T07:00:00+00:00",
        "body": """A collection is a journey. Our niche perfume collection begins in Jordan and does not stop at its borders.

We called it **Beyond Borders** because each of its five fragrances starts somewhere specific, a valley, a desert, a window in Paris, and then travels. Made in France. Rooted in Jordan. Worn anywhere.

Five niche eaux de parfum. Here they are, one by one.

## Oud Passion: the one that commands without speaking

![Mood of Oud Passion](""" + C + """mood-oud-passion.webp)

It opens bright: grapefruit, bergamot, passion fruit. Then it deepens. Moldavian rose absolute, harvested at first light, thousands of blooms for a single gram. Patchouli and vetiver. At the base, sandalwood, leather and oud.

Powerful. Sophisticated. Magnetic. Some fragrances are chosen. This one recognises its wearer. [Discover Oud Passion](/products/oud-passion).

## Oh My Dear!: the one that is remembered

![Mood of Oh My Dear!](""" + C + """mood-oh-my-dear.webp)

Oud and saffron, lifted by luminous aldehydes. A heart of rose and leather, held together by cypriol. Then amber, vetiver, cedarwood and vanilla, and a soft suede accord that feels like skin.

Intimate. Graceful. Sentimental. Some scents are worn. This one is remembered. [Discover Oh My Dear!](/products/oh-my-dear).

## Velvet Waterfall: the one born from stillness

![Mood of Velvet Waterfall](""" + C + """mood-velvet-waterfall.webp)

Inspired by the camel: calm, resilient, elegant in the desert. Pepper, saffron and incense open with a mineral warmth. Rose, violet and lily of the valley bring light. Musk, cedarwood, moss and vetiver leave a warm trail.

Flowing. Sensual. Luminous. Born from stillness. Felt in motion. [Discover Velvet Waterfall](/products/velvet-waterfall).

## Parisian: the one that carries home

![Mood of Parisian](""" + C + """mood-parisian.webp)

A Jordanian morning, remembered through a Parisian window. Coffee with cream, grapefruit and red berries. Rose, peony and jasmine. A base of croissant, almond and musk.

Worldly. Still. Rooted. [Discover Parisian](/products/parisian).

## Out of Control: the one that has already claimed the night

![Mood of Out of Control](""" + C + """mood-out-of-control.webp)

Lemon, nutmeg and cool spices open fast. Then fig, with coconut and freesia, creamy and unexpected. Patchouli, sandalwood and fruity musk make the trail impossible to ignore.

Bold. Daring. Provocative. [Discover Out of Control](/products/out-of-control).

## Five journeys, one house

Each is an Eau de Parfum in 100 ml. Each is built around its raw materials, with nothing added to distract. Each develops slowly, made for a quiet, lasting presence rather than a loud first minute.

A Discovery Collection of all five is coming. Until then, choose the journey that feels like yours.""",
    },
    {
        "slug": "luxury-perfume-bottle-amber-brass",
        "title": "The Weight of Amber: Inside the Maison Henius Bottle",
        "category": "Craft",
        "excerpt": "Thick amber glass, an embossed brass crest and a golden cap shaped like an Ionic column. Why every detail of our bottle is deliberate.",
        "hero_image": C + "bottle-oud-passion.webp",
        "hero_alt": "Luxury perfume bottle in amber glass with a brass crest",
        "hero_caption": "",
        "seo_title": "Luxury Perfume Bottle Design: Amber, Brass & Craft",
        "meta_description": "A luxury perfume bottle made like the scent inside it: thick amber glass, a brass crest and an Ionic-column cap. Inside the Maison Henius bottle.",
        "focus_keyword": "luxury perfume bottle",
        "secondary_keywords": "artisan perfume craftsmanship, niche perfume made in France",
        "tags": "bottle, craftsmanship, design, made in France",
        "related_products": "oud-passion, velvet-waterfall",
        "cta_label": "Hold one yourself",
        "cta_url": "/shop",
        "social_caption": "Hold it once and you understand. Amber glass that turns from sand to twilight, a brass crest, a golden cap shaped like an ancient column. Inside the Maison Henius bottle, on the Journal.\n\n#MaisonHenius #PerfumeBottle #LuxuryPerfume #NichePerfume #Craftsmanship #MadeInFrance",
        "is_featured": False,
        "published_at": "2026-11-24T06:00:00+00:00",
        "body": """Hold it once and you understand why a luxury perfume bottle matters.

The glass has weight. The cap has resistance. The brass is cool under your thumb. Nothing about the bottle is accidental, because we believe a fragrance begins before the first spray.

## The glass: from sand to twilight

Our bottle is thick amber glass. Look closely and you will see a gradient. Golden amber at the base. Deep darkness at the shoulder.

It is the desert at the end of the day: warm sand below, twilight above. The same minute the house was born from, held in your hand.

![Amber gradient glass, golden base to dark shoulder](""" + C + """bottle-velvet-waterfall.webp "Velvet Waterfall: golden amber at the base, twilight at the shoulder.")

## The plate: a crest in brass

There is no paper label. Instead, an embossed brass plate carries the Maison crest, with serif lettering in deep orange.

Brass ages. It warms with touch and softens with time. Like the fragrance inside, it is made to live with you, not to stay new.

## The cap: a column from antiquity

The cap is custom golden Zamac, shaped after the ancient Ionic column. The house name is engraved around the neck.

We wanted a cap that carried a sense of time: classical, steady, built to last.

![Golden Ionic column cap engraved with the house name](""" + C + """bottle-parisian.webp "The golden Zamac cap, shaped after the Ionic column.")

## Inside: the material comes first

The same rule applies to the juice, and it is what makes this niche perfume rather than mass fragrance. Each composition is built around the essence of its raw materials, with nothing added to distract and nothing softened to please. Saffron. Moldavian rose absolute. Oud. Incense. Fig.

Our fragrances are made in France and develop slowly on the skin. They were never designed for the first ten seconds. They were designed for the hours after.

## Five pillars, one object

Elegance, never loud. Exclusivity, selective rather than secretive. Warmth, from ochre and amber. Timelessness, beyond trends. Cultural depth, in quiet references to heritage and travel.

The bottle is where all five meet. [Discover the craft](/story).""",
    },
    {
        "slug": "parisian-not-french-gourmand-niche-perfume",
        "title": "Parisian Is Not French: A Gourmand Niche Perfume",
        "category": "Fragrance Notes",
        "excerpt": "Coffee with cream, rose, peony and a warm croissant accord. Parisian is a Jordanian morning remembered through a Parisian window.",
        "hero_image": C + "mood-parisian.webp",
        "hero_alt": "Coffee and croissant mood of Parisian, a gourmand niche perfume",
        "hero_caption": "",
        "seo_title": "Parisian Is Not French: A Gourmand Niche Perfume",
        "meta_description": "A gourmand niche perfume of coffee, croissant, almond and rose. Parisian is a Jordanian morning remembered through a Parisian window.",
        "focus_keyword": "gourmand niche perfume",
        "secondary_keywords": "coffee perfume, croissant perfume, floral gourmand eau de parfum",
        "tags": "Parisian, gourmand, coffee, croissant",
        "related_products": "parisian",
        "cta_label": "Discover Parisian",
        "cta_url": "/products/parisian",
        "social_caption": "The name says Paris. The heart says Jordan. Coffee with cream, rose, peony and a warm croissant. Why Parisian is not French, on our Journal.\n\n#MaisonHenius #Parisian #GourmandPerfume #CoffeePerfume #NichePerfume #PerfumeOfTheDay",
        "is_featured": False,
        "published_at": "2026-11-24T05:00:00+00:00",
        "body": """The name says Paris. The heart says Jordan. In between: a gourmand niche perfume of coffee, croissant and rose.

Parisian is the one fragrance in our house named after a city outside Jordan. People ask why. The answer is a single morning.

## Cold blue light

It was early. The light through the window was cold and blue, the way Paris light is in the hour before the city wakes. On the table, dark coffee, unhurried. Beside it, a warm croissant.

And the smell of that croissant did something unexpected. It did not smell of France. It smelled of home: of bread baked in a Jordanian kitchen, of mornings long before Paris.

For one morning, a foreign city became home. Parisian is that feeling, kept.

## The notes, as the morning unfolds

![Coffee with cream](""" + I + """coffee-with-cream.webp)

**First, the table.** Coffee with cream, bright grapefruit and red berries. Fresh, awake, with a soft gourmand edge.

![Peony](""" + I + """peony.webp)

**Then, the window.** Rose, peony and jasmine. A romantic bouquet, like flowers on a Paris balcony catching first light.

![Warm croissant](""" + I + """croissant.webp)

**Finally, home.** Croissant, almond and musk. Creamy, comforting and warm. This is the part that stays on your skin through the day.

## When to wear it

Parisian is a morning fragrance first. Wear it with the first coffee of the day, on a slow weekend, or on a journey far from home. The coffee and grapefruit open bright and awake. By afternoon, the almond and musk settle close to the skin, soft and warm, like a kitchen you remember.

## Who wears Parisian

The worldly, who know elegance needs no announcement. The still, who find beauty in unhurried moments. The rooted, who carry home wherever they go.

If you have ever been far away and suddenly felt you belonged, you already know this fragrance.

## A Jordanian morning, remembered through a Parisian window

Parisian is a niche Floral-Gourmand Eau de Parfum, 100 ml. Made in France. Remembered from Jordan. [Discover Parisian](/products/parisian).""",
    },
    {
        "slug": "how-to-choose-a-niche-perfume",
        "title": "Which Fragrance Will Recognise You?",
        "category": "Guides",
        "excerpt": "Bold or still? Day or night? A short guide to finding which of the five Beyond Borders eaux de parfum was made for you, and how to wear it.",
        "hero_image": C + "beyond-borders-collection.webp",
        "hero_alt": "How to choose a niche perfume: the five Beyond Borders fragrances",
        "hero_caption": "",
        "seo_title": "How to Choose a Niche Perfume | Maison Henius Guide",
        "meta_description": "How to choose a niche perfume: bold or still, day or night? A simple guide to the five Maison Henius eaux de parfum, and how to wear them.",
        "focus_keyword": "how to choose a niche perfume",
        "secondary_keywords": "niche fragrance guide, oud perfume, signature scent",
        "tags": "guide, signature scent, how to wear perfume",
        "related_products": "oud-passion, oh-my-dear, velvet-waterfall, parisian, out-of-control",
        "cta_label": "Enter the collection",
        "cta_url": "/shop",
        "social_caption": "How do you enter a room? Quietly, warmly, or late with the night already yours? Three questions to find the Maison Henius fragrance that recognises you. On the Journal now.\n\n#MaisonHenius #SignatureScent #NichePerfume #PerfumeGuide #FragranceTips #PerfumeCollection",
        "is_featured": False,
        "published_at": "2026-11-24T04:00:00+00:00",
        "body": """How to choose a niche perfume? Not the way you choose a shirt. You notice which one feels familiar. Which one already sounds like you.

Three questions will take you there.

## 1. How do you enter a room?

- **Quietly, and everyone still notices.** [Oud Passion](/products/oud-passion). Powerful, sophisticated, magnetic.
- **Warmly, close to the people you love.** [Oh My Dear!](/products/oh-my-dear) Intimate, graceful, sentimental.
- **Calmly, moving at your own pace.** [Velvet Waterfall](/products/velvet-waterfall). Flowing, sensual, luminous.
- **Unhurried, at home anywhere.** [Parisian](/products/parisian). Worldly, still, rooted.
- **Late, and the night is already yours.** [Out of Control](/products/out-of-control). Bold, daring, provocative.

## 2. Which notes do you love?

- **Oud, leather and a fresh citrus opening:** Oud Passion (Woody-Amber, Oud).
- **Suede, saffron, vanilla and amber:** Oh My Dear! (Woody-Amber).
- **Saffron, incense, rose and cedarwood:** Velvet Waterfall (Floral-Woody).
- **Coffee, almond and soft florals:** Parisian (Floral-Gourmand).
- **Fig, coconut, lemon and sandalwood:** Out of Control (Fruity-Floral).

## 3. When will you wear it?

- **Daytime, everyday elegance:** Parisian or Velvet Waterfall.
- **Evenings and close moments:** Oh My Dear!
- **Important days, when presence matters:** Oud Passion.
- **Nights out:** Out of Control.

![Oh My Dear! eau de parfum](""" + C + """card-oh-my-dear.webp)

## How to wear a Maison Henius fragrance

Our fragrances are built to develop slowly. Give them time.

1. Spray on pulse points: wrists, neck, behind the ears.
2. Do not rub. Let the top notes open on their own.
3. Judge it after an hour, not after a minute. The heart and base are where each story really lives.

## Try it on skin, not on paper

A paper strip shows you the first minute. Your skin shows you the story. Spray one fragrance on each wrist, then live your day. The one you keep returning to in the evening is usually the one that has already chosen you.

## Still undecided?

[Write to us](/#contact). Tell us a place you love, or a memory you return to, and we will suggest the fragrance that carries it. A Discovery Collection of all five is also on its way.""",
    },
]
