# sphinx\_pytest\_fixtures — Badge Demo

Visual reference for all badge permutations. Use this page to verify badge
rendering across themes, zoom levels, and light/dark modes.

Each section documents one badge combination. The index table at the top
gives a compact overview of all permutations at once.

```{py:module} spf_demo_fixtures
```

## Fixture Index

```{autofixture-index} spf_demo_fixtures
```

---

## Plain (FIXTURE badge only)

Function scope, resource kind, not autouse. Shows only the green FIXTURE badge.

```{autofixture} spf_demo_fixtures.demo_plain
```

---

## Scope badges

### Session scope

```{autofixture} spf_demo_fixtures.demo_session
```

### Module scope

```{autofixture} spf_demo_fixtures.demo_module
```

### Class scope

```{autofixture} spf_demo_fixtures.demo_class
```

---

## Kind badges

### Factory kind

Return type `type[str]` is auto-detected as factory — no explicit `:kind:` needed.

```{autofixture} spf_demo_fixtures.demo_factory
```

### Override hook

Requires explicit `:kind: override_hook` since it cannot be inferred from type.

```{autofixture} spf_demo_fixtures.demo_override_hook
:kind: override_hook
```

---

## State badges

### Autouse

```{autofixture} spf_demo_fixtures.demo_autouse
```

### Deprecated

The `deprecated` badge is set via the `:deprecated:` RST option on `py:fixture`.
The `autofixture` directive does not support `:deprecated:`; use `py:fixture` instead.

```{py:fixture} demo_deprecated
:deprecated: 1.0
:replacement: demo_plain
:return-type: str

Return a deprecated value. Use {fixture}`demo_plain` instead.
```

---

## Combinations

### Session + Factory

```{autofixture} spf_demo_fixtures.demo_session_factory
```

### Session + Autouse

```{autofixture} spf_demo_fixtures.demo_session_autouse
```
