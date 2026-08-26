This headless note opens with a paragraph that carries no heading at all, so
every entry it produces is a freeform chunk. It exists to cover the chunking
path end to end, which no earlier fixture reached.

The second paragraph adds enough additional prose to push the note past one
dense encoder window. It talks about deterministic identifiers, the way stale
points are removed during an incremental pass, and the reuse of embeddings
whose input did not change between two runs of the indexer.

The third paragraph repeats the structure once more so the packing logic has
to close a chunk and open another one. The important property is that the
boundary lands between paragraphs and never inside a sentence.

Cardamom is the unique closing term for this note.
