# Domain packs

A domain pack is one JSON file in `domains/`. It is the only thing that decides
what your vault is *about*: which folders exist, what counts as worth keeping,
what the subject's proper nouns are, and what a good tag looks like.

The pipeline never knows what subject it is working on. Swap the pack and the
same code produces a fitness vault instead of a software one.

```bash
python savebrain.py domains                          # what is installed, * = active
python savebrain.py new-domain "urban beekeeping"    # write a new one with the model
python savebrain.py setup --domains urban-beekeeping --yes
```

## Schema

```jsonc
{
  "id": "cooking",                     // filename and CLI name, kebab-case
  "label": "Cooking & Food",           // shown in menus and note headers
  "emoji": "🍳",

  // The folders in your vault. lowercase_with_underscores.
  // The description is fed to the model, so write it as guidance, not decoration.
  "categories": {
    "recipes": "complete recipes worth cooking again",
    "technique": "knife work, heat control, doughs, sauces"
  },

  // Folders whose SHORT posts get merged into one weekly file instead of
  // getting their own note. Use for folders that collect one-line finds.
  "bucket_categories": ["equipment"],

  // Relevance. Short phrases. Be generous in `relevant`, strict in `not_relevant`.
  "relevant":     ["recipes with real quantities", "cooking technique and food science"],
  "not_relevant": ["food shown with no method", "pure eating content"],

  // The domain's proper nouns worth pulling out of every post.
  "entity_label": "dishes, ingredients, brands, chefs, restaurants",

  // What a "copyable artifact" looks like here. Drives verbatim capture.
  "artifact_examples": "a full recipe: ingredients with quantities, then numbered method",

  // What short verbatim lines matter here.
  "snippet_label": "oven temperatures, hydration ratios, timings",

  // 6-10 realistic tags. These teach the model your tagging style by example.
  "tag_examples": ["one-pan-dinners", "sourdough-hydration", "pantry-staples"],

  // OCR corrections specific to this subject.
  "cleanup_hints": ["\"table spoon\" -> \"tbsp\"", "\"sour dough\" -> \"sourdough\""]
}
```

`uncategorized` is added automatically — do not define it.

## Writing a good one

- **6–12 categories.** Fewer and everything piles into one folder; more and you
  will never remember which is which.
- **Name folders the way you would name them at 11pm** looking for that one
  thing you saved. Not an academic taxonomy.
- **`bucket_categories` is for the folders that collect links and products**, not
  explanations. A 40-word note per gadget is clutter; one weekly file is not.
- **`not_relevant` is where the noise gets killed.** Be specific about the junk
  your feed actually serves you: ads, engagement bait, results with no method.
- **`tag_examples` teach by example.** Give tags 5–20 future posts could share.

## Combining packs

```bash
python savebrain.py setup --domains cooking,fitness,wellness --yes
```

Categories, relevance rules and cleanup hints are unioned. Watch for folder
names that collide in meaning across packs (`nutrition` in `fitness` vs
`nutrition_health` in `wellness`) — if it bothers you, edit one of the packs.

## Editing an existing pack

Edit the JSON, then re-run `python savebrain.py index`. New categories create
their folders on the next ingest. Notes already written stay where they are — to
re-file them against the new folders:

```bash
python savebrain.py ingest --reset
```

That forgets what has been processed and runs the whole inbox again. The inbox is
kept, so nothing needs re-collecting, as long as the media links have not expired.

## Contributing a pack

Good packs are useful to everyone. Open a PR adding `domains/<id>.json` with:
6–12 categories, honest `not_relevant` lines, and tag examples from your own
real saves. `python savebrain.py domains` should list it cleanly.
