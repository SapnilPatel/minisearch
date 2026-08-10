# Bug journal

A running note of every non-trivial bug hit during the build and, crucially,
**how it was found**. These stories are the most valuable interview material this
project produces and are impossible to reconstruct after the fact — so they get
written down when they happen, not later.

Format per entry: what broke, how it surfaced, the root cause, the fix, and the
lesson.

---

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
