"""Measure the bloom filter's actual false-positive rate against theory.

Inserts n member URLs, probes with a large set of distinct non-members, and
compares the measured FP rate with the predicted (1 - e^(-kn/m))^k at several
load levels — including overload, where the filter degrades exactly as the
formula says it should. Also compares memory against a plain set of the same
URLs, which is the entire argument for the data structure.

Deterministic (BLAKE2b, fixed inputs): repeated runs give identical numbers, so
unlike the timing benchmarks this needs no run-3-times protocol.

Usage:  python scripts/measure_bloom_fpr.py
"""

import sys

from minisearch.dedup import BloomFilter

CAPACITY = 100_000
TARGET_FPR = 0.01
PROBES = 200_000


def measure(load_fraction: float) -> tuple[int, float, float]:
    n = int(CAPACITY * load_fraction)
    bf = BloomFilter(expected_items=CAPACITY, target_fpr=TARGET_FPR)
    for i in range(n):
        bf.add(f"http://member.example.com/page/{i}")
    fp = sum(
        1 for i in range(PROBES) if f"http://nonmember.example.com/page/{i}" in bf
    )
    return n, fp / PROBES, bf.theoretical_fpr()


def set_memory_bytes(n: int) -> int:
    urls = {f"http://member.example.com/page/{i}" for i in range(n)}
    return sys.getsizeof(urls) + sum(sys.getsizeof(u) for u in urls)


def main() -> None:
    bf = BloomFilter(expected_items=CAPACITY, target_fpr=TARGET_FPR)
    print(
        f"filter: capacity={CAPACITY:,} target_fpr={TARGET_FPR} "
        f"m={bf.num_bits:,} bits k={bf.num_hashes} "
        f"({bf.num_bits / CAPACITY:.2f} bits/element, {bf.size_bytes / 1024:.0f} KiB)"
    )
    print(f"probes per measurement: {PROBES:,} distinct non-members\n")

    print(f"{'load':>6} {'items':>9} {'measured FPR':>13} {'theoretical':>12} {'ratio':>6}")
    for load in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0):
        n, measured, theoretical = measure(load)
        ratio = measured / theoretical if theoretical else float("inf")
        print(f"{load:>5.0%} {n:>9,} {measured:>13.5f} {theoretical:>12.5f} {ratio:>6.2f}")

    set_bytes = set_memory_bytes(CAPACITY)
    print(
        f"\nmemory at {CAPACITY:,} URLs: set={set_bytes / 1024 / 1024:.1f} MiB  "
        f"bloom={bf.size_bytes / 1024:.0f} KiB  "
        f"({set_bytes / bf.size_bytes:.0f}x reduction)"
    )


if __name__ == "__main__":
    main()
