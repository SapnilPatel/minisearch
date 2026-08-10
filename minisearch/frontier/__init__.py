"""The URL frontier — a priority queue with politeness (Milestone 2).

A min-heap keyed by score (shallower depth = higher priority) plus a per-host map
of nextAllowedTime. Pop the best URL whose host is currently allowed; defer the
rest. Not a plain FIFO: it must crawl important pages first AND never hammer one
host."""
