# Bug journal

A running note of every non-trivial bug hit during the build and, crucially,
**how it was found**. These stories are the most valuable interview material this
project produces and are impossible to reconstruct after the fact — so they get
written down when they happen, not later.

Format per entry: what broke, how it surfaced, the root cause, the fix, and the
lesson.

---

## M3 — delay-spacing is not per-host concurrency 1

- **What broke:** nothing visibly — a silent design gap. The M2 frontier
  rescheduled a host `delay` seconds after the *pop*. If a response takes longer
  than the delay, a second request to the same host starts while the first is
  still in flight, violating the "per-host concurrency 1" promise.
- **How it surfaced:** writing the M3 worker pool. The worker code had nowhere
  to say "this host's fetch finished" — which exposed that the frontier never
  needed to know, and therefore couldn't be enforcing serialization.
- **The fix:** an explicit protocol — `pop_ready` locks the host (busy set);
  the caller must call `host_done(host, now)` on completion, and only then does
  the politeness clock start. Two new tests pin the guarantee: a host stays
  locked despite an elapsed delay, and the delay counts from completion, not
  start.
- **Lesson:** rate-limiting request *starts* and limiting *concurrency* are
  different guarantees. Integrating a consumer is what reveals which one your
  API actually provides.

## M3 — macOS hid the venv's `.pth` file from Python 3.13

- **What broke:** `python scripts/bench_crawl.py` failed with
  `ModuleNotFoundError: No module named 'minisearch'` — while `pytest` and
  `python -c "import minisearch"` from the project root worked fine.
- **How it surfaced:** first attempt to run anything as a plain script from the
  editable install. `python -v` revealed the smoking gun:
  `Skipping hidden .pth file: ... __editable__.minisearch-0.1.0.pth`.
- **Root cause:** two things stacked. (1) macOS applies the `UF_HIDDEN` flag to
  the dot-named `.venv` directory and files created inside inherit it. (2)
  Python 3.13's `site.py` deliberately skips *hidden* `.pth` files (a security
  hardening change). So the editable-install hook never ran. pytest had masked
  the problem the whole time by putting the project root on `sys.path` itself.
- **The fix:** `chflags -R nohidden .venv`.
- **Lesson:** "it works under pytest" proves nothing about imports — the test
  runner rewrites `sys.path`. And when imports behave inconsistently,
  `python -v` shows what `site` actually did rather than what you assume it did.

## M0 — `@dataclass(slots=True)` default read back a slot descriptor

- **What broke:** `Config.from_env()` returned `fetcher_workers` as a `<member
  'fetcher_workers' ...>` descriptor object instead of `8` when the env var was
  unset.
- **How it surfaced:** `test_defaults_when_env_empty` failed on the very first
  `pytest` run — before the code ever ran "for real." Tests-first caught it.
- **Root cause:** with `slots=True`, a dataclass stores field defaults in
  `__dataclass_fields__`, *not* as ordinary class attributes — the class
  attribute becomes a slot descriptor. My `from_env` used `cls.fetcher_workers`
  as the fallback default, so an unset env var passed the descriptor through
  untouched.
- **The fix:** stop duplicating defaults. Env helpers now return `None` when a
  var is absent, and `from_env` omits those keys so the dataclass supplies the
  one canonical default. Fewer places to be wrong.
- **Lesson:** with slotted dataclasses, read defaults via
  `dataclasses.fields()` / `field.default`, never `cls.<field>`. Better yet,
  don't restate a default you've already declared.
