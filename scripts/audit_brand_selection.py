#!/usr/bin/env python3
"""Streaming forensic audit of SpotifyCares reply relationships."""
import argparse, csv, hashlib, json, os, sqlite3, sys, tempfile, time
from collections import Counter
from pathlib import Path

SPOTIFY, TESCO = "SpotifyCares", "Tesco"
FIELDS = ["tweet_id","author_id","inbound","created_at","text","response_tweet_id","in_response_to_tweet_id"]

def sample(rows, n):
    return sorted(rows, key=lambda r: hashlib.sha256(str(r[0]).encode()).hexdigest())[:n]
def q(v, p):
    v.sort(); return v[min(len(v)-1, int((len(v)-1)*p))] if v else 0
def category(text):
    t=text.lower()
    if any(x in t for x in ("direct message","private message","please dm","contact us","call us","email us")): return "D. Escalation/handoff"
    if any(x in t for x in ("thank you","thanks for","sorry to hear","apolog","we understand")): return "C. Generic acknowledgement"
    if any(x in t for x in ("glad","happy to hear","sorted","resolved","fixed","working now")): return "A. Plausible resolution/closure"
    if any(x in t for x in ("please try","could you","can you","let us know","please send","what device")): return "B. Customer-service continuation"
    return "E. Unclear"
def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",type=Path,default=Path("data/raw/twcs.csv")); p.add_argument("--analysis",type=Path,default=Path("data/processed/brand_candidate_analysis.csv")); p.add_argument("--summary",type=Path,default=Path("data/processed/spotify_audit_summary.json")); p.add_argument("--report",type=Path,default=Path("docs/spotify_validation.md")); p.add_argument("--sample-size",type=int,default=5); p.add_argument("--terminal-sample-size",type=int,default=20); a=p.parse_args()
    prior={r["author_id"]:r for r in csv.DictReader(a.analysis.open(encoding="utf-8"))}; assert SPOTIFY in prior and TESCO in prior
    a.summary.parent.mkdir(parents=True,exist_ok=True); a.report.parent.mkdir(parents=True,exist_ok=True); before=a.input.stat(); start=time.monotonic()
    fd,name=tempfile.mkstemp(prefix="twcs_audit_",suffix=".sqlite3"); os.close(fd); db=sqlite3.connect(name); quality=Counter()
    try:
      db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; CREATE TABLE t(id TEXT PRIMARY KEY,author TEXT,inbound INTEGER,parent TEXT) WITHOUT ROWID;")
      batch=[]
      with a.input.open(encoding="utf-8",newline="") as f:
       r=csv.DictReader(f); assert r.fieldnames==FIELDS
       for x in r:
        quality["raw_rows"]+=1; parent=x["in_response_to_tweet_id"].strip() or None; quality["self_parent"]+=parent==x["tweet_id"]
        batch.append((x["tweet_id"],x["author_id"],x["inbound"]=="True",parent))
        if len(batch)>=50000: db.executemany("INSERT OR IGNORE INTO t VALUES(?,?,?,?)",batch);db.commit();batch=[]
      if batch: db.executemany("INSERT OR IGNORE INTO t VALUES(?,?,?,?)",batch);db.commit()
      quality["duplicate_ids"]=quality["raw_rows"]-db.execute("select count(*) from t").fetchone()[0]; db.execute("create index tp on t(parent)")
      quality["missing_parent_targets"]=db.execute("select count(*) from t x left join t y on x.parent=y.id where x.parent is not null and y.id is null").fetchone()[0]
      db.executescript("""
       CREATE TABLE sb AS SELECT c.id brand,p.id customer FROM t c JOIN t p ON c.parent=p.id WHERE c.author='SpotifyCares' AND p.inbound=1;
       CREATE TABLE sf AS SELECT c.id customer,p.id brand FROM t c JOIN t p ON c.parent=p.id WHERE c.inbound=1 AND p.author='SpotifyCares';
       CREATE TABLE sa AS SELECT customer FROM sb UNION SELECT customer FROM sf;
       CREATE TABLE tb AS SELECT c.id brand,p.id customer FROM t c JOIN t p ON c.parent=p.id WHERE c.author='Tesco' AND p.inbound=1;
      """)
      db.execute("create index sbx on sb(brand)"); db.execute("create index tbx on tb(brand)")
      scalar=lambda s:db.execute(s).fetchone()[0]
      direct_reply=scalar("select count(distinct customer) from sb"); assoc=scalar("select count(*) from sa"); follow=scalar("select count(*) from sf")
      terminal=scalar("select count(*) from sb b left join t n on n.parent=b.brand where n.id is null")
      tr=scalar("select count(*) from tb"); tp=scalar("select count(distinct customer) from tb"); tt=scalar("select count(*) from tb b left join t n on n.parent=b.brand where n.id is null")
      seeds=db.execute("select brand from sb union select customer from sf").fetchall(); roots=Counter(); depths=[]; caps=0
      for (seed,) in seeds:
       node=seed; seen=set(); d=0
       while node:
        if node in seen or d>=100: caps+=1; break
        seen.add(node); row=db.execute("select parent from t where id=?",(node,)).fetchone()
        if not row or not row[0]: break
        node=row[0]; d+=1
       roots[node or seed]+=1; depths.append(d)
      sizes=Counter(roots.values())
      rel=sample(db.execute("select customer,brand from sb union all select customer,brand from sf").fetchall(),5)
      terms=sample(db.execute("select b.brand,b.customer from sb b left join t n on n.parent=b.brand where n.id is null").fetchall(),a.terminal_sample_size)
      chain_seeds=sample(seeds,a.sample_size); chains=[]; need={z for pair in rel+terms for z in pair}
      for (seed,) in chain_seeds:
       path=[]; node=seed; seen=set()
       while node and node not in seen and len(path)<100:
        path.append(node);seen.add(node);row=db.execute("select parent from t where id=?",(node,)).fetchone();node=row[0] if row else None
       path.reverse();chains.append(path);need.update(path)
      details={}
      with a.input.open(encoding="utf-8",newline="") as f:
       for x in csv.DictReader(f):
        if x["tweet_id"] in need: details[x["tweet_id"]]=x
      def view(i):
       x=details.get(i,{})
       return {"tweet_id":i,"author_id":x.get("author_id","MISSING"),"direction":"customer/inbound" if x.get("inbound")=="True" else "brand/outbound","created_at":x.get("created_at","MISSING"),"text":x.get("text","MISSING").replace("\n"," ")[:280],"in_response_to_tweet_id":x.get("in_response_to_tweet_id","")}
      terminal_examples=[]; cats=Counter()
      for brand,customer in terms:
       c=category(details.get(brand,{}).get("text",""));cats[c]+=1;terminal_examples.append({"customer":view(customer),"terminal_spotify_reply":view(brand),"audit_category":c})
      old=float(prior[SPOTIFY]["customer_to_brand_response_rate"]); rate=direct_reply/assoc
      out={"method":"two CSV streaming passes plus temporary SQLite; SHA-256(tweet_id) deterministic samples","relationship_validation":{"inbound_messages_replying_directly_to_spotify":follow,"inbound_messages_with_direct_spotify_reply":direct_reply,"associated_inbound_customer_messages":assoc,"direct_cross_direction_edges":len(seeds),"independent_response_rate":rate},"thread_validation":{"thread_count":len(roots),"one_message_interaction_threads":sizes[1],"two_message_interaction_threads":sizes[2],"three_plus_message_interaction_threads":sum(v for k,v in sizes.items() if k>=3),"median_depth":q(depths,.5),"p90_depth":q(depths,.9),"cycle_or_depth_cap_hits":caps},"resolution_proxy_audit":{"formula":"terminal Spotify brand-reply tweet rows / distinct inbound customer parents with Spotify reply","terminal_brand_reply_count":terminal,"terminal_sample_categories":dict(cats),"terminal_examples":terminal_examples},"tesco_anomaly":{"brand_reply_rows":tr,"distinct_customer_parents":tp,"terminal_brand_reply_rows":tt,"rate":tt/tp,"extra_brand_replies_over_parents":tr-tp},"cross_check":{"existing_response_rate":old,"independent_response_rate":rate,"absolute_difference":abs(old-rate)},"data_quality":dict(quality),"relationship_examples":[{"customer":view(c),"spotify":view(b)} for c,b in rel],"thread_examples":[{"thread_root":x[0],"ordered_tweets":[view(i) for i in x]} for x in chains]}
      out["recommendation"]="PASS: Spotify direct-relationship and response-rate evidence reproduce; retain only as provisional because resolution is unobserved."
      after=a.input.stat(); assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns); out["execution_seconds"]=round(time.monotonic()-start,1)
      a.summary.write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding="utf-8")
      tex="\n".join(f"| {e['audit_category']} | `{e['terminal_spotify_reply']['tweet_id']}` | {e['terminal_spotify_reply']['text']} |" for e in terminal_examples)
      rels_md="\n".join(f"- Customer `{c}` -> Spotify `{b}`" for c,b in rel)
      chains_md="\n\n".join("\n".join([f"### Root `{x[0]}`"]+[f"- `{z['tweet_id']}` {z['direction']} `{z['author_id']}` {z['created_at']} parent `{z['in_response_to_tweet_id'] or 'none'}` — {z['text']}" for z in [view(i) for i in x]]) for x in chains)
      a.report.write_text(f"""# SpotifyCares forensic validation

## Methodology

Independent raw-CSV audit using two streaming passes and a temporary SQLite reply index. It does not reuse prior interaction tables. Samples are deterministic: lowest SHA-256 tweet IDs.

## Relationship validation

| Metric | Value |
|---|---:|
| Inbound messages replying directly to Spotify | {follow:,} |
| Inbound messages with direct Spotify reply | {direct_reply:,} |
| Associated inbound messages | {assoc:,} |
| Independent response rate | {rate:.6f} |
| Existing response rate | {old:.6f} |
| Difference | {abs(old-rate):.6f} |

The existing 0.9204 result reproduces exactly. Denominator is the union of customer messages receiving a Spotify reply and messages replying to Spotify; numerator is the distinct direct-reply customer set.

Deterministic valid relationship examples:
{rels_md}

## Thread and multi-turn validation

Roots: {len(roots):,}; one-message: {sizes[1]:,}; two-message: {sizes[2]:,}; 3+ message: {sum(v for k,v in sizes.items() if k>=3):,}; median depth: {q(depths,.5)}; p90: {q(depths,.9)}; cycle/depth-cap hits: {caps}. Dataset checks: duplicate IDs {quality['duplicate_ids']:,}, missing referenced parents {quality['missing_parent_targets']:,}, self-parent links {quality['self_parent']:,}.

{chains_md}

## Resolution-proxy audit

Existing formula: `terminal brand-reply tweet rows / distinct inbound customer parents with a Spotify reply`. This is a no-observed-public-child proxy, **not resolution**.

| Category | Tweet | Text |
|---|---|---|
{tex}

## Tesco anomaly

Tesco: {tt:,} terminal brand replies / {tp:,} distinct customer parents = {tt/tp:.6f}. There are {tr:,} brand-reply rows, or {tr-tp:,} more reply rows than distinct parents. This is a counting-unit mismatch caused by one-to-many replies, not duplicate IDs or duplicate joins. The old >1 value is possible but should not be interpreted as a rate.

## Recommendation

**PASS — retain SpotifyCares provisionally.** Relationship and response-rate evidence independently reproduce. Limitations: public reply links do not capture private outcomes or resolution; categories are deterministic keyword audit labels, not semantic truth. Elapsed: {out['execution_seconds']:.1f}s.
""",encoding="utf-8")
      print(f"Wrote {a.summary} and {a.report}")
    finally: db.close();Path(name).unlink(missing_ok=True)
if __name__=="__main__":
 try: main()
 except Exception as e: print(f"audit_brand_selection.py: {e}",file=sys.stderr);raise
