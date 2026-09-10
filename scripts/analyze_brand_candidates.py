#!/usr/bin/env python3
"""Second-stage, streaming analysis of TWCS outbound support-account candidates."""
from __future__ import annotations

import argparse
import csv
import os
import re
import sqlite3
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

TOKEN_RE = re.compile(r"[a-z]{3,}")
STOPWORDS = frozenset("the and for are but not you with this that have from was were your all can will just get got about into please thanks thank there they their our out has had its its via".split())
NON_CONTENT_TOKENS = frozenset(("amp", "com", "http", "https", "www"))
PATTERNS = ("account", "cancel", "charge", "delivery", "delay", "error", "help", "login", "order", "password", "payment", "refund", "service")
OUT_COLUMNS = [
    "author_id", "candidate_scope_rank_by_outbound", "outbound_tweet_count",
    "associated_inbound_customer_tweets", "direct_customer_brand_reply_edges",
    "reconstructed_thread_count", "interaction_depth_p50", "interaction_depth_p90",
    "one_turn_thread_proportion", "multi_turn_thread_proportion",
    "customer_messages_with_direct_brand_response", "customer_to_brand_response_rate",
    "terminal_brand_response_proxy_count", "terminal_brand_response_proxy_rate",
    "customer_token_count", "customer_unique_terms", "unique_terms_per_100_tokens",
    "top_10_term_share", "common_support_pattern_counts", "top_terms",
    "pareto_tier", "selection_rank", "ranking_basis",
]


def ids(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    values.sort()
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


def flush_tokens(db: sqlite3.Connection, batch: dict[tuple[str, str], int]) -> None:
    if not batch:
        return
    db.executemany(
        "INSERT INTO token_stats(candidate, token, count) VALUES (?, ?, ?) "
        "ON CONFLICT(candidate, token) DO UPDATE SET count=count + excluded.count",
        [(candidate, token, count) for (candidate, token), count in batch.items()],
    )
    db.commit()
    batch.clear()


def pareto_tiers(metrics: dict[str, dict[str, float]]) -> dict[str, int]:
    """Return successive non-dominated tiers; every dimension is maximized."""
    remaining = set(metrics)
    tiers: dict[str, int] = {}
    tier = 1
    dimensions = ("associated", "follow_rate", "multi_turn", "term_diversity")
    while remaining:
        frontier = []
        for candidate in remaining:
            current = metrics[candidate]
            dominated = any(
                other != candidate
                and all(metrics[other][d] >= current[d] for d in dimensions)
                and any(metrics[other][d] > current[d] for d in dimensions)
                for other in remaining
            )
            if not dominated:
                frontier.append(candidate)
        for candidate in frontier:
            tiers[candidate] = tier
        remaining.difference_update(frontier)
        tier += 1
    return tiers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/twcs.csv"))
    parser.add_argument("--profile", type=Path, default=Path("data/processed/brand_profile.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/brand_candidate_analysis.csv"))
    parser.add_argument("--report", type=Path, default=Path("docs/brand_candidate_analysis.md"))
    parser.add_argument("--top-n", type=int, default=20, help="Number of candidates to analyze (default: 20).")
    args = parser.parse_args()
    if not args.input.is_file() or not args.profile.is_file() or args.top_n < 1:
        parser.error("input and profile must exist; --top-n must be positive")
    candidates = list(csv.DictReader(args.profile.open(encoding="utf-8")))[:args.top_n]
    if not candidates:
        parser.error("profile contains no candidates")
    candidate_order = [row["author_id"] for row in candidates]
    candidate_outbound = {row["author_id"]: int(row["outbound_tweets"]) for row in candidates}
    candidate_rank = {candidate: i + 1 for i, candidate in enumerate(candidate_order)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    before = args.input.stat()
    started = time.monotonic()
    fd, name = tempfile.mkstemp(prefix="twcs_candidate_", suffix=".sqlite3")
    os.close(fd)
    db_path = Path(name)
    db = sqlite3.connect(db_path)
    try:
        db.executescript("""
            PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE;
            CREATE TABLE tweets(tweet_id TEXT PRIMARY KEY, candidate TEXT, inbound INTEGER NOT NULL, parent_id TEXT) WITHOUT ROWID;
            CREATE TABLE token_stats(candidate TEXT, token TEXT, count INTEGER NOT NULL, PRIMARY KEY(candidate, token)) WITHOUT ROWID;
        """)
        quality: Counter[str] = Counter()
        inserts: list[tuple[str, str | None, int, str | None]] = []
        with args.input.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            expected = ["tweet_id", "author_id", "inbound", "created_at", "text", "response_tweet_id", "in_response_to_tweet_id"]
            if reader.fieldnames != expected:
                raise ValueError(f"unexpected CSV columns: {reader.fieldnames!r}")
            for row in reader:
                quality["rows"] += 1
                inbound_text = row["inbound"].strip()
                if inbound_text not in ("True", "False"):
                    quality["invalid_inbound"] += 1
                    continue
                if not row["tweet_id"]: quality["missing_tweet_id"] += 1
                if not row["author_id"]: quality["missing_author_id"] += 1
                if not row["text"]: quality["missing_text"] += 1
                if not row["created_at"]: quality["missing_created_at"] += 1
                if not row["response_tweet_id"]: quality["missing_response_field"] += 1
                if not row["in_response_to_tweet_id"]: quality["missing_parent_field"] += 1
                response_ids = ids(row["response_tweet_id"])
                quality["response_targets"] += len(response_ids)
                quality["multi_response_rows"] += len(response_ids) > 1
                parent = row["in_response_to_tweet_id"].strip() or None
                quality["self_parent"] += parent == row["tweet_id"]
                inserts.append((row["tweet_id"], row["author_id"] if row["author_id"] in candidate_outbound else None,
                                inbound_text == "True", parent))
                if len(inserts) >= 50_000:
                    db.executemany("INSERT OR IGNORE INTO tweets VALUES (?, ?, ?, ?)", inserts)
                    db.commit(); inserts.clear()
        if inserts:
            db.executemany("INSERT OR IGNORE INTO tweets VALUES (?, ?, ?, ?)", inserts); db.commit()
        stored = db.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
        quality["duplicate_tweet_ids"] = quality["rows"] - stored
        quality["missing_parent_targets"] = db.execute(
            "SELECT COUNT(*) FROM tweets t LEFT JOIN tweets p ON t.parent_id=p.tweet_id "
            "WHERE t.parent_id IS NOT NULL AND p.tweet_id IS NULL"
        ).fetchone()[0]
        db.executescript("CREATE INDEX tweets_parent ON tweets(parent_id);")
        db.executescript("""
            CREATE TABLE interactions AS
            SELECT c.candidate AS candidate, c.tweet_id AS child_id, p.tweet_id AS parent_id, 'brand_reply' AS kind
            FROM tweets c JOIN tweets p ON c.parent_id=p.tweet_id
            WHERE c.candidate IS NOT NULL AND p.inbound=1
            UNION ALL
            SELECT p.candidate AS candidate, c.tweet_id AS child_id, p.tweet_id AS parent_id, 'customer_followup' AS kind
            FROM tweets c JOIN tweets p ON c.parent_id=p.tweet_id
            WHERE c.inbound=1 AND p.candidate IS NOT NULL;
            CREATE INDEX interactions_candidate ON interactions(candidate);
            CREATE TABLE associated AS
            SELECT DISTINCT candidate, CASE WHEN kind='brand_reply' THEN parent_id ELSE child_id END AS tweet_id FROM interactions;
            CREATE INDEX associated_tweet ON associated(tweet_id);
        """)
        # A second streaming pass reads text only for inbound messages that are structurally associated with a candidate.
        token_batch: dict[tuple[str, str], int] = {}
        pattern_counts: dict[str, Counter[str]] = defaultdict(Counter)
        with args.input.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            lookup = db.cursor()
            for row in reader:
                if row["inbound"] != "True":
                    continue
                matches = lookup.execute("SELECT candidate FROM associated WHERE tweet_id=?", (row["tweet_id"],)).fetchall()
                if not matches:
                    continue
                base_terms = [term for term in TOKEN_RE.findall(row["text"].lower())
                              if term not in STOPWORDS and term not in NON_CONTENT_TOKENS]
                for (candidate,) in matches:
                    # A candidate's own handle is conversation routing metadata,
                    # not evidence of a customer problem/topic.
                    terms = [term for term in base_terms if term != candidate.lower()]
                    pattern_counts[candidate].update(pattern for pattern in PATTERNS if pattern in terms)
                    for term in terms:
                        key = (candidate, term)
                        token_batch[key] = token_batch.get(key, 0) + 1
                if len(token_batch) >= 50_000:
                    flush_tokens(db, token_batch)
        flush_tokens(db, token_batch)

        metrics: dict[str, dict[str, object]] = {}
        for candidate in candidate_order:
            interaction_rows = db.execute("SELECT child_id, parent_id, kind FROM interactions WHERE candidate=?", (candidate,)).fetchall()
            associated = db.execute("SELECT COUNT(*) FROM associated WHERE candidate=?", (candidate,)).fetchone()[0]
            brand_parent_count = db.execute("SELECT COUNT(DISTINCT parent_id) FROM interactions WHERE candidate=? AND kind='brand_reply'", (candidate,)).fetchone()[0]
            terminal = db.execute("""
                SELECT COUNT(*) FROM interactions i LEFT JOIN tweets next ON next.parent_id=i.child_id
                WHERE i.candidate=? AND i.kind='brand_reply' AND next.tweet_id IS NULL
            """, (candidate,)).fetchone()[0]
            # Trace each direct cross-direction interaction to its reply-chain root. Depth is root-to-interaction edge depth.
            roots = db.execute("""
                WITH RECURSIVE path(seed, node, parent, depth) AS (
                  SELECT child_id, child_id, parent_id, 0 FROM interactions WHERE candidate=?
                  UNION ALL
                  SELECT path.seed, t.tweet_id, t.parent_id, path.depth+1
                  FROM path JOIN tweets t ON path.parent=t.tweet_id WHERE path.depth < 100
                )
                SELECT seed, node, depth FROM path
                WHERE parent IS NULL OR NOT EXISTS (SELECT 1 FROM tweets t WHERE t.tweet_id=path.parent)
            """, (candidate,)).fetchall()
            root_by_seed = {seed: (root, depth) for seed, root, depth in roots}
            thread_edges: Counter[str] = Counter()
            depths: list[int] = []
            for child, _parent, _kind in interaction_rows:
                root, depth = root_by_seed.get(child, (child, 0))
                thread_edges[root] += 1
                depths.append(depth)
            thread_count = len(thread_edges)
            multi_threads = sum(count > 1 for count in thread_edges.values())
            token_total, unique_terms = db.execute("SELECT COALESCE(SUM(count),0), COUNT(*) FROM token_stats WHERE candidate=?", (candidate,)).fetchone()
            top_terms = db.execute("SELECT token, count FROM token_stats WHERE candidate=? ORDER BY count DESC, token ASC LIMIT 10", (candidate,)).fetchall()
            top_share = (sum(count for _, count in top_terms) / token_total) if token_total else 0.0
            follow_rate = brand_parent_count / associated if associated else 0.0
            metrics[candidate] = {
                "associated": associated, "follow_rate": follow_rate,
                "multi_turn": multi_threads / thread_count if thread_count else 0.0,
                "term_diversity": unique_terms / token_total if token_total else 0.0,
                "outbound": candidate_outbound[candidate], "edges": len(interaction_rows),
                "threads": thread_count, "p50": percentile(depths, .50), "p90": percentile(depths, .90),
                "one_turn": (thread_count - multi_threads) / thread_count if thread_count else 0.0,
                "brand_parent": brand_parent_count, "terminal": terminal, "token_total": token_total,
                "unique_terms": unique_terms, "top_share": top_share, "top_terms": top_terms,
            }
        tiers = pareto_tiers(metrics)
        # No composite score: tier is primary; stable tie-breaks favor response rate, multi-turn context, diversity, then evidence volume.
        ranked = sorted(candidate_order, key=lambda c: (tiers[c], -metrics[c]["follow_rate"], -metrics[c]["multi_turn"], -metrics[c]["term_diversity"], -metrics[c]["associated"], c))
        selection_rank = {candidate: index + 1 for index, candidate in enumerate(ranked)}
        with args.output.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=OUT_COLUMNS); writer.writeheader()
            for candidate in ranked:
                item = metrics[candidate]
                writer.writerow({
                    "author_id": candidate, "candidate_scope_rank_by_outbound": candidate_rank[candidate],
                    "outbound_tweet_count": item["outbound"], "associated_inbound_customer_tweets": item["associated"],
                    "direct_customer_brand_reply_edges": item["edges"], "reconstructed_thread_count": item["threads"],
                    "interaction_depth_p50": item["p50"], "interaction_depth_p90": item["p90"],
                    "one_turn_thread_proportion": f"{item['one_turn']:.6f}", "multi_turn_thread_proportion": f"{item['multi_turn']:.6f}",
                    "customer_messages_with_direct_brand_response": item["brand_parent"], "customer_to_brand_response_rate": f"{item['follow_rate']:.6f}",
                    "terminal_brand_response_proxy_count": item["terminal"], "terminal_brand_response_proxy_rate": f"{item['terminal'] / item['brand_parent'] if item['brand_parent'] else 0:.6f}",
                    "customer_token_count": item["token_total"], "customer_unique_terms": item["unique_terms"],
                    "unique_terms_per_100_tokens": f"{100 * item['term_diversity']:.6f}", "top_10_term_share": f"{item['top_share']:.6f}",
                    "common_support_pattern_counts": ";".join(f"{p}:{pattern_counts[candidate][p]}" for p in PATTERNS),
                    "top_terms": ";".join(f"{term}:{count}" for term, count in item["top_terms"]),
                    "pareto_tier": tiers[candidate], "selection_rank": selection_rank[candidate],
                    "ranking_basis": "pareto_no_weights",
                })
        after = args.input.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError("raw dataset changed during analysis")
        strongest = ranked[0]
        top = metrics[strongest]
        quality_lines = "\n".join(f"| {key.replace('_', ' ')} | {value:,} |" for key, value in sorted(quality.items()))
        comparison = "\n".join(
            f"| {c} | {selection_rank[c]} | {tiers[c]} | {metrics[c]['associated']:,} | {metrics[c]['follow_rate']:.3f} | {metrics[c]['multi_turn']:.3f} | {metrics[c]['unique_terms']:,} |"
            for c in ranked
        )
        elapsed = time.monotonic() - started
        report = f"""# Second-stage brand candidate analysis

## Reproducibility and scope

```powershell
python scripts/analyze_brand_candidates.py
```

The existing profile has 108 behavioral outbound-account candidates. This run
analyzes its top {args.top_n} by available outbound history to ensure sufficient
observations, but **does not select the winner by volume**. It never infers a
company from an ID: candidates are the existing `inbound=False` accounts, while
`inbound=True` messages are treated as customer-side based on the established
dataset convention. All processing is deterministic; no sampling, LLM, or
external brand information is used.

## Methodology and definitions

- A direct customer-brand interaction is a reply-link edge between a selected
  candidate and an inbound tweet. `associated_inbound_customer_tweets` is the
  distinct customer-side endpoint of those edges.
- A reconstructed thread is a distinct reply-chain root reached by tracing each
  direct interaction through `in_response_to_tweet_id`. Depth percentiles are
  root-to-direct-interaction-link depth, capped at 100 to prevent malformed
  cycles from causing unbounded traversal.
- Multi-turn means a reconstructed root has more than one direct cross-direction
  interaction edge; one-turn is exactly one. This is structural, not semantic.
- Direct response rate is the fraction of associated inbound messages that have
  an immediately child brand reply. The terminal-brand-response proxy counts
  those replies with no observed child tweet. It is **not a resolution rate**:
  a public thread ending can reflect resolution, abandonment, or a moved private
  conversation.
- Terms come only from associated inbound texts: lower-cased alphabetic tokens
  of at least three characters, excluding the listed generic stopwords, URL
  fragments, and that candidate's own handle. `top_10_term_share` measures
  concentration; pattern counts are literal word occurrences, not intent labels.

## Candidate comparison

`selection_rank` uses successive Pareto tiers with no weighted composite score.
Candidates are compared by four maximized, exposed dimensions: associated
customer history, direct response rate, multi-turn-thread proportion, and
unique-terms-per-token diversity. Within a tier, deterministic tie-breaks use
response rate, multi-turn proportion, term diversity, then associated history.

| Candidate | Rank | Pareto tier | Associated inbound | Direct response rate | Multi-turn | Unique terms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{comparison}

## Evidence for the leading candidate

The leading candidate under the no-weight Pareto ranking is **{strongest}**:
{top['associated']:,} structurally associated customer tweets, a direct response
rate of {top['follow_rate']:.3f}, multi-turn-thread proportion of
{top['multi_turn']:.3f}, and {top['unique_terms']:,} observed customer terms.
This supports substantial retrievable public interaction history and measurable
language variety. Against over-interpreting it: the dataset does not expose
company identity, private outcomes, satisfaction, or actual issue labels; its
terminal-response proxy cannot establish resolution.

## Data quality findings

| Check | Count |
| --- | ---: |
{quality_lines}

Missing parent targets are reply IDs absent from the CSV. Duplicate IDs are
computed from the exact SQLite primary-key count. The script checks raw-file
size and modification time before and after the run.

## Limitations

Only the top {args.top_n} of 108 profile candidates are deeply analyzed; this is
a scope limit, not a claim that the remaining accounts are unsuitable. Reply
links can reconstruct public structural chains but not all conversations, and
the response-link list is used only for data-quality counts because it can be
one-to-many. Text metrics are diversity proxies, not an intent classifier or
quality judgment. Elapsed time: {elapsed:.1f} seconds.
"""
        args.report.write_text(report, encoding="utf-8")
        print(f"Wrote {args.output} ({len(ranked)} candidates)")
        print(f"Wrote {args.report}")
        print(f"Leading candidate: {strongest}; elapsed: {elapsed:.1f}s")
    finally:
        db.close()
        db_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, csv.Error, sqlite3.Error, RuntimeError) as error:
        print(f"analyze_brand_candidates.py: {error}", file=sys.stderr)
        raise SystemExit(1)
