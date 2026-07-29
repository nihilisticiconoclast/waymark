# Voice

The editorial specification. This is the file that makes Waymark worth building rather than
bookmarking someone else's walks site, and it is the file most likely to drift. Changes here
are model changes: regenerate two existing walks and show the diff.

---

## Who this is written for

One walker. He runs trails and lifts, so he is not asking whether a hill is hard — he is
asking whether it is *sustained*, because a 200 m climb spread over three kilometres and a
200 m climb in eight hundred metres are different days out. He wants to know what is
underfoot after rain, because the Cotswold clay caps behave nothing like the limestone.

He is vegan, which is a filter question rather than an identity question: a pub at the
halfway point is only useful information if you say whether there is anything there to eat.
"Food available" is not an answer.

He photographs. Light matters, so does vantage. A west-facing escarpment edge is worth
different hours than a valley bottom, and that is a fact about the route, not a flourish.

He reads history and philosophy of a particular cast — interwar, le Carré, Lem, Næss —
and collects objects with material history. What he wants from a landscape description is
not lyricism. It is *why it looks like this*: what the rock is doing, what was made here,
what the enclosure did to the field pattern, what the mills left in the valley floor.

---

## Register

Graduate, unhurried, and confident about the difference between what is known and what is
inferred. Assume competence. He can read a map, so don't explain contours; he has walked in
weather, so don't warn him about mud as though it were news.

Prose, not bullets, in the body copy. The structured fields carry the enumerable facts; the
prose is for the things that don't fit in a field.

Evaluate. A walk that is merely fine should be described as merely fine. The corpus is more
useful with honest gradation than with fifty walks that are all "a lovely stretch". If a
route's best feature is that it is close and reliable in January, say that and nothing more.

No second-person address, no exhortation, no "you'll love". No "hidden gem", "must-see",
"stunning", "breathtaking", "nestled", "boasts", "picturesque", "gateway to". The stoplist
is in `prompts/author-system.md` and the validator checks it.

---

## Stance toward the landscape

Describe the place as a thing in itself, not as a resource for the walker. The beech hangers
on the escarpment are not "a lovely canopy for the ascent" — they are a beech hanger on a
limestone escarpment, which is why the ground beneath them is bare and why the path is loose.
The walker is a visitor to something that is not about him. Where a route passes through
working land, say what the work is.

This is not decoration. It is the difference between a description that survives a second
reading and one that doesn't.

---

## Structure of a write-up

**`summary`** — one sentence, no adjectives before the first noun. What it is and where.

**`character`** — two to four sentences. What the walk is actually like to be on. The
sustained sections, where the effort sits, what changes underfoot. This is where the
evaluation goes.

**`grain`** — exactly one sentence on why the landscape looks the way it does: the geology,
the land use, the industrial or agricultural history that shaped it. Constrained to what the
survey found plus `data/gazetteer.txt`; if there is nothing supportable, the field is null
rather than filled with plausible material. A null `grain` is a signal to widen the gazetteer,
not a defect in the walk.

**`conditions`** — when it is good and when it isn't. Season, aspect, drainage, light. What
the route does after a wet week.

**`practical`** — parking, facilities, refreshment, transport. Say what is there and say what
isn't. Vegan availability stated explicitly or stated unknown.

**`caveats`** — access uncertainty, unmapped furniture, road crossings, livestock-likely
sections. Never omitted to keep a write-up clean. A walk with no caveats has a caveats entry
saying the survey found none, which is a different claim.

---

## Honesty about the survey's limits

The survey knows what OpenStreetMap knows. It does not know about a stile that has rotted, a
permissive path withdrawn last spring, or a footbridge out since the winter. Write as though
that is understood, and say where the map is thin. A sentence like *the field-edge section
south of the lane has no surface tag, so it may be anything from a mown margin to standing
crop* is worth more than a confident guess in either direction.

This is also what `confidence.navigable` is for. If the write-up is hedging in three places,
the number should reflect it.

---

## Length

250–400 words across all prose fields. Long enough to say something, short enough that
reading twenty of them is possible. If a walk needs more than 400 words it is probably two
walks, or one walk and a note in the gazetteer.
