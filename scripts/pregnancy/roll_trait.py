#!/usr/bin/env python3
"""Trait roll for the Pregnancy Protocol.

CLI:
    python3 scripts/pregnancy/roll_trait.py --category <name> --state <state.json> --ledger <ledger.jsonl>
    python3 scripts/pregnancy/roll_trait.py --dry-run --category <name> --state <state.json> --ledger <ledger.jsonl>
    python3 scripts/pregnancy/roll_trait.py --verify --ledger <ledger.jsonl>
    python3 scripts/pregnancy/roll_trait.py --seed <int> --category <name> ...   # deterministic roll
    python3 scripts/pregnancy/roll_trait.py --self-test                       # exercises chain build+verify

Each non-verify, non-dry-run roll appends one record to the ledger and updates
state.json (new chain_root, new trait_lock). Categories can only be rolled once
per state; `--dry-run` prints the outcome without writing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64  # SHA-256 hex, 64 chars


def canonical(record: dict[str, Any]) -> bytes:
    """Stable JSON encoding for hashing.

    Sorts keys; splits ASCII-only; no spaces. Used both when recording and
    when verifying, so the chain is reproducible.
    """
    return json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_pool(pool_path: Path) -> dict[str, Any]:
    if not pool_path.exists():
        raise FileNotFoundError(f"trait pool not found: {pool_path}")
    raw = json.loads(pool_path.read_text(encoding="utf-8"))
    if "_meta" not in raw:
        raise ValueError(f"trait pool missing _meta: {pool_path}")
    return raw


def resolve_snapshot_pool(pool_version: str, base_pool_path: Path) -> dict[str, Any] | None:
    """Resolve a snapshot pool for a record whose `pool_version` differs from the loaded pool.

    Search order:
      1. $PREGNANCY_POOL_DIR / <pool_version> / <base_pool_path.name>
      2. <base_pool_path.parent> / pools / <pool_version> / <base_pool_path.name>

    Returns the loaded snapshot pool, or None when no usable snapshot exists.
    """
    if not pool_version or pool_version == "(absent)":
        return None
    candidates: list[Path] = []
    env_dir = os.environ.get("PREGNANCY_POOL_DIR")
    if env_dir:
        candidates.append(Path(env_dir) / pool_version / base_pool_path.name)
    candidates.append(base_pool_path.parent / "pools" / pool_version / base_pool_path.name)
    for cand in candidates:
        if cand.exists():
            try:
                return load_pool(cand)
            except (FileNotFoundError, ValueError):
                return None
    return None


def load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        # Bootstrap a fresh state on first roll.
        return {
            "chain_root": GENESIS_HASH,
            "trait_locks": {},
            "rolled": False,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_ledger(ledger_path: Path, record: dict[str, Any], raw: bytes) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    line = raw.decode("utf-8") + "\n"
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def choose_outcome(pool: dict[str, Any], category: str, rng: random.Random) -> dict[str, str]:
    options = pool.get(category)
    if not options:
        raise ValueError(f"unknown category '{category}' (not in pool)")
    if not isinstance(options, list) or not options:
        raise ValueError(f"category '{category}' has no options")
    return rng.choice(options)


def pool_version_from_pool(pool: dict[str, Any]) -> str:
    """Derive pool_version string for new rolls (Pregnancy Protocol v0.5 A9).

    Reads `_meta.version` from the loaded pool. Integer versions render as
    "v{N}.0"; string versions are used as-is (preserving any existing "v"
    prefix); floats render as their compact string form. Falls back to "v1.0"
    when the field is absent or unusable.
    """
    meta = pool.get("_meta") or {}
    version = meta.get("version")
    if version is None:
        return "v1.0"
    if isinstance(version, str):
        return version if version.startswith("v") else f"v{version}"
    if isinstance(version, bool):  # bool is an int subclass; treat defensively.
        return "v1.0"
    if isinstance(version, int):
        return f"v{version}.0"
    if isinstance(version, float):
        if version.is_integer():
            return f"v{int(version)}.0"
        return f"v{version:g}"
    return f"v{version}"


def make_record(
    *,
    index: int,
    prev_hash: str,
    seed: int,
    category: str,
    outcome: dict[str, str],
    pool_version: str,
) -> dict[str, Any]:
    return {
        "index": index,
        "prev_hash": prev_hash,
        "seed": seed,
        "category": category,
        "outcome": outcome,
        "origin": outcome.get("origin", "unknown"),
        "pool_version": pool_version,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def record_body(rec: dict[str, Any]) -> dict[str, Any]:
    """The hashable body of a record (everything except the 'hash' field).

    Used both when computing and when verifying the self-hash, so the chain is
    reproducible. The 'hash' field is the SHA-256 of canonical(body); 'prev_hash'
    references the previous record's 'hash' (or the genesis sentinel for index 0).
    """
    return {k: v for k, v in rec.items() if k != "hash"}


def record_self_hash(rec: dict[str, Any]) -> str:
    return sha256_hex(canonical(record_body(rec)))


def verify_ledger(
    ledger_path: Path,
    pool: dict[str, Any] | None = None,
    pool_path: Path | None = None,
) -> tuple[bool, str]:
    if not ledger_path.exists():
        return False, f"ledger not found: {ledger_path}"
    prev = GENESIS_HASH
    expected_index = 0
    lines = [ln for ln in ledger_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return False, "ledger is empty"
    # Per-record summary (collected during the walk; reported at the end so a
    # single trailing failure still surfaces the prior records). pool_version
    # is intentionally NOT in the required-fields list above: chain entries
    # recorded before protocol v0.5 A9 did not carry the field, and the spec
    # requires backward-compatible verification for that legacy content.
    per_record: list[tuple[int, str, str, str]] = []  # (idx, label, pool_version, hash)
    warnings: list[str] = []
    snapshot_cache: dict[str, dict[str, Any] | None] = {}
    current_pv: str | None = pool_version_from_pool(pool) if pool is not None else None
    for n, line in enumerate(lines, start=1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            return False, f"line {n}: invalid JSON ({exc})"
        for key in ("index", "prev_hash", "hash", "seed", "category", "outcome", "origin", "ts"):
            if key not in rec:
                return False, f"line {n}: missing field '{key}'"
        if rec["index"] != expected_index:
            return False, f"line {n}: bad index (expected {expected_index}, got {rec['index']})"
        if rec["origin"] != rec["outcome"].get("origin"):
            return False, (
                f"line {n}: top-level origin ({rec['origin']}) "
                f"!= outcome.origin ({rec['outcome'].get('origin')})"
            )
        if rec["prev_hash"] != prev:
            return False, f"line {n}: prev_hash mismatch (expected {prev[:12]}..., got {rec['prev_hash'][:12]}...)"
        computed = record_self_hash(rec)
        if rec["hash"] != computed:
            return False, f"line {n}: self-hash mismatch (stored {rec['hash'][:12]}..., computed {computed[:12]}...)"
        pv = rec.get("pool_version", "(absent)")
        outcome = rec["outcome"]
        label_text: str = outcome.get("label", "")
        # Version-aware label resolution (Pregnancy Protocol v0.5 A9): when a
        # record's pool_version differs from the loaded pool's version, try to
        # resolve labels via the matching snapshot pool. Verification still
        # passes on hash integrity; missing snapshots emit an explicit warning
        # line and render the label as <unresolved-label:pool_version>.
        if (
            pool is not None
            and pool_path is not None
            and pv not in ("(absent)",)
            and current_pv is not None
            and pv != current_pv
        ):
            if pv not in snapshot_cache:
                snapshot_cache[pv] = resolve_snapshot_pool(pv, pool_path)
            snapshot = snapshot_cache[pv]
            if snapshot is None:
                unresolved = f"<unresolved-label:{pv}>"
                label_text = unresolved
                warnings.append(
                    f"warning: line {n}: snapshot pool for pool_version={pv} not found "
                    f"(searched $PREGNANCY_POOL_DIR/{pv}/* and {pool_path.parent}/pools/{pv}/*); "
                    f"label rendered as {unresolved}"
                )
            else:
                options = snapshot.get(rec["category"]) or []
                match = next((opt for opt in options if opt.get("id") == outcome.get("id")), None)
                if match is None:
                    unresolved = f"<unresolved-label:{pv}>"
                    label_text = unresolved
                    warnings.append(
                        f"warning: line {n}: snapshot pool {pv} loaded but category "
                        f"'{rec['category']}' or outcome id '{outcome.get('id')}' not present; "
                        f"label rendered as {unresolved}"
                    )
                else:
                    label_text = match.get("label", "") or label_text
        per_record.append((rec["index"], label_text, pv, rec["hash"]))
        prev = rec["hash"]
        expected_index += 1
    summary = f"chain verified: {expected_index} record(s), root={prev[:12]}..."
    detail_lines: list[str] = list(warnings)
    detail_lines.extend(
        f"  [{idx}] {label:<22} pool_version={pv:<10} hash={h[:12]}..."
        for (idx, label, pv, h) in per_record
    )
    return True, f"{summary}\n" + "\n".join(detail_lines)


def cmd_roll(args: argparse.Namespace, pool: dict[str, Any]) -> int:
    state_path = Path(args.state)
    ledger_path = Path(args.ledger)
    state = load_state(state_path)
    trait_locks = state.setdefault("trait_locks", {})
    if trait_locks.get(args.category) is not None:
        print(f"refusing roll: category '{args.category}' already locked", file=sys.stderr)
        return 2

    seed = args.seed if args.seed is not None else random.SystemRandom().randint(0, 2**32 - 1)  # noqa: S311
    rng = random.Random(seed)  # noqa: S311
    outcome = choose_outcome(pool, args.category, rng)
    next_index = state.get("next_index", 0)
    record = make_record(
        index=next_index,
        prev_hash=state["chain_root"],
        seed=seed,
        category=args.category,
        outcome=outcome,
        pool_version=pool_version_from_pool(pool),
    )
    # Self-hash: SHA-256 of canonical(body) — body excludes the 'hash' field.
    record["hash"] = record_self_hash(record)
    raw = canonical(record)
    new_root = record["hash"]

    if args.dry_run:
        print(json.dumps(
            {
                "dry_run": True,
                "would_record": json.loads(raw.decode("utf-8")),
                "new_chain_root": new_root,
            },
            indent=2,
        ))
        return 0

    append_ledger(ledger_path, record, raw)
    trait_locks[args.category] = {
        "id": outcome["id"],
        "label": outcome.get("label", ""),
        "origin": outcome.get("origin", "unknown"),
        "index": next_index,
        "hash": new_root,
    }
    state["chain_root"] = new_root
    state["next_index"] = next_index + 1
    state["rolled"] = True
    save_state(state_path, state)
    # Print the canonical JSON (matching what's on disk) so callers/tests can parse it.
    print(raw.decode("utf-8"))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    pool_path = Path(args.pool)
    pool: dict[str, Any] | None = None
    if pool_path.exists():
        try:
            pool = load_pool(pool_path)
        except (FileNotFoundError, ValueError):
            pool = None
    ok, msg = verify_ledger(Path(args.ledger), pool=pool, pool_path=pool_path)
    print(msg)
    return 0 if ok else 1


def cmd_self_test(args: argparse.Namespace, pool: dict[str, Any]) -> int:
    """Exercise: build a chain in /tmp, verify it, fail loudly if anything breaks."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        s = Path(td) / "state.json"
        ledger_p = Path(td) / "ledger.jsonl"
        ns = argparse.Namespace(
            category="voice_tone",
            state=str(s),
            ledger=str(ledger_p),
            seed=42,
            dry_run=False,
        )
        rc = cmd_roll(ns, pool)
        if rc != 0:
            print(f"self-test: roll 1 failed rc={rc}", file=sys.stderr)
            return rc
        ns.category = "aesthetic"
        ns.seed = 7
        rc = cmd_roll(ns, pool)
        if rc != 0:
            print(f"self-test: roll 2 failed rc={rc}", file=sys.stderr)
            return rc
        # duplicate guard
        ns.category = "voice_tone"
        rc = cmd_roll(ns, pool)
        if rc != 2:
            print(f"self-test: duplicate guard failed rc={rc}", file=sys.stderr)
            return 1
        v = argparse.Namespace(ledger=str(ledger_p), pool=args.pool)
        rc = cmd_verify(v)
        if rc != 0:
            print(f"self-test: verify failed rc={rc}", file=sys.stderr)
            return rc
        # Tamper detection: rewrite the first record's self-hash to a dummy.
        # Verifier must refuse (self-hash mismatch).
        lines = ledger_p.read_text(encoding="utf-8").splitlines()
        lines = [ln for ln in lines if ln.strip()]
        first = json.loads(lines[0])
        first["hash"] = "0" * 64  # wrong hash → should fail verify
        lines[0] = json.dumps(first, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        ledger_p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rc = cmd_verify(v)
        if rc == 0:
            print("self-test: tamper detection failed (verify still ok)", file=sys.stderr)
            return 1
    print("self-test: ok (chain built, duplicate guard, verify, tamper detect)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pregnancy Protocol trait roll with hash-chained ledger")
    # Default --pool is anchored to the script's repo (resolved relative to __file__).
    _script_dir = Path(__file__).resolve().parent
    _repo_root = _script_dir.parents[1]  # .../scripts/pregnancy -> repo root
    p.add_argument("--pool", default=str(_repo_root / "memory" / "pregnancy" / "trait_pool_harem_v1.json"), type=Path)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--category", help="trait category to roll (e.g. voice_tone)")
    g.add_argument("--verify", action="store_true", help="walk the ledger and verify the chain")
    g.add_argument("--self-test", action="store_true", help="run a self-contained chain test")
    p.add_argument("--state", default=str(_repo_root / "memory" / "pregnancy" / "state.json"), help="path to state.json")  # noqa: E501
    p.add_argument("--ledger", default=str(_repo_root / "memory" / "pregnancy" / "ledger.jsonl"), help="path to ledger.jsonl")  # noqa: E501
    p.add_argument("--seed", type=int, default=None, help="deterministic seed (default: system entropy)")
    p.add_argument("--dry-run", action="store_true", help="print the would-be record without writing")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    pool: dict[str, Any] | None = None
    if not args.verify and not args.self_test:
        # Roll path: pool must exist and load.
        pool = load_pool(args.pool)
    elif args.self_test:
        # Self-test needs the pool to validate options exist.
        pool = load_pool(args.pool)

    if args.verify:
        return cmd_verify(args)
    if args.self_test:
        assert pool is not None  # loaded above
        return cmd_self_test(args, pool)
    if not args.category:
        parser.error("either --category, --verify, or --self-test is required")
    if pool is None:
        pool = load_pool(args.pool)
    return cmd_roll(args, pool)


if __name__ == "__main__":
    sys.exit(main())
