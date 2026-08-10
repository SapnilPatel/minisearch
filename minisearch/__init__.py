"""minisearch — a concurrent web crawler and search engine.

Two independent paths run through one shared inverted index:

* the **ingest path**  — frontier -> fetch -> dedup -> extract -> analyze -> index
* the **query path**   — parse -> look up postings -> intersect -> score -> top-K

Each subpackage owns one component of that pipeline; see the module docstrings
for which milestone fills it in. Keeping the two paths mentally separate is the
key to reasoning about (and explaining) the system.
"""

__version__ = "0.1.0"
