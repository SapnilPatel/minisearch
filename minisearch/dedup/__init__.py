"""Deduplication — bloom filter + content hashing (Milestone 4).

Two separate questions: "have I seen this URL?" (a hand-rolled bloom filter over
normalized URLs) and "have I seen this content before under a different URL?"
(a hash of the extracted text). False negatives are impossible, which is what
makes the bloom filter safe here.
"""

from minisearch.dedup.bloom import BloomFilter
from minisearch.dedup.content import ContentDeduper

__all__ = ["BloomFilter", "ContentDeduper"]
