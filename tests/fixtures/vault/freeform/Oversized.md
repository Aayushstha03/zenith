# Oversized Reference

## Migration Notes

The first paragraph explains why the storage layer moved from a single flat
collection into an aliased pair, and why the alias switch happens only after
the temporary collection validates. This paragraph alone carries enough prose
to occupy a large part of the dense encoder window on its own.

The second paragraph continues the same section without a new heading. It
describes the rollback path, the way a failed rebuild leaves the previous
alias untouched, and the diagnostics that report a partially written temporary
collection so an operator can remove it safely and try the rebuild again.

The third paragraph closes the section by describing the saffron measurement
recorded during the kitchen trial, which is deliberately placed at the end so
a truncation regression is visible: if this text is reachable by semantic
search then the section was chunked instead of silently cut short.

## Short Section

One short paragraph that fits the budget and must stay a single entry.
