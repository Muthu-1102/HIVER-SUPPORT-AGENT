#!/usr/bin/env python3
"""Reconstruct root-based public TWCS conversation components containing SpotifyCares."""
from __future__ import annotations
import argparse, csv, json, os, sqlite3, sys, tempfile, time
from collections import Counter
from datetime import datetime
from pathlib import Path

FIELDS=["tweet_id","author_id","inbound","created_at","text","response_tweet_id","in_response_to_tweet_id"]
SPOTIFY="SpotifyCares"
def epoch(value):
    try: return int(datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y").timestamp())
    except ValueError: return -1
def ids(value): return [x.strip() for x in (value or "").split(",") if x.strip()]
def percentile(v,p):
    v.sort(); return v[min(len(v)-1,int((len(v)-1)*p))] if v else 0

def reconstruct(input_path, output_path, stats_path):
    before=input_path.stat(); started=time.monotonic(); output_path.parent.mkdir(parents=True,exist_ok=True); stats_path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix="twcs_spotify_conversations_",suffix=".sqlite3");os.close(fd); db=sqlite3.connect(name); db.row_factory=sqlite3.Row; quality=Counter()
    try:
      db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE; CREATE TABLE tweets(id TEXT PRIMARY KEY,author TEXT,inbound INTEGER,created TEXT,stamp INTEGER,text TEXT,response TEXT,parent TEXT) WITHOUT ROWID;")
      batch=[]
      with input_path.open(encoding="utf-8",newline="") as source:
       reader=csv.DictReader(source)
       if reader.fieldnames!=FIELDS: raise ValueError("unexpected CSV schema")
       for r in reader:
        quality["raw_rows"]+=1; parent=r["in_response_to_tweet_id"].strip() or None
        quality["malformed_relationship_count"]+=r["inbound"] not in ("True","False") or parent==r["tweet_id"]
        batch.append((r["tweet_id"],r["author_id"],r["inbound"]=="True",r["created_at"],epoch(r["created_at"]),r["text"],r["response_tweet_id"],parent))
        if len(batch)>=50000: db.executemany("INSERT OR IGNORE INTO tweets VALUES(?,?,?,?,?,?,?,?)",batch);db.commit();batch=[]
      if batch: db.executemany("INSERT OR IGNORE INTO tweets VALUES(?,?,?,?,?,?,?,?)",batch);db.commit()
      quality["duplicate_count"]=quality["raw_rows"]-db.execute("SELECT count(*) FROM tweets").fetchone()[0]; db.execute("CREATE INDEX parent_idx ON tweets(parent)")
      quality["missing_parent_count"]=db.execute("SELECT count(*) FROM tweets a LEFT JOIN tweets b ON a.parent=b.id WHERE a.parent IS NOT NULL AND b.id IS NULL").fetchone()[0]
      db.executescript("CREATE TABLE seeds AS SELECT id FROM tweets WHERE author='SpotifyCares';")
      # Ascend only Spotify seeds. Missing parents terminate at the last present message; cycles/deep chains fall back to the seed.
      db.executescript("""
       CREATE TABLE root_map AS
       WITH RECURSIVE a(seed,node,parent,depth) AS (
         SELECT s.id,t.id,t.parent,0 FROM seeds s JOIN tweets t ON t.id=s.id
         UNION ALL SELECT a.seed,t.id,t.parent,a.depth+1 FROM a JOIN tweets t ON t.id=a.parent WHERE a.depth<100
       ) SELECT seed,node AS root FROM a WHERE parent IS NULL OR NOT EXISTS(SELECT 1 FROM tweets x WHERE x.id=a.parent);
       CREATE TABLE roots AS SELECT DISTINCT root FROM root_map;
       CREATE TABLE selected AS
       WITH RECURSIVE d(root,id,depth) AS (
         SELECT root,root,0 FROM roots UNION ALL
         SELECT d.root,t.id,d.depth+1 FROM d JOIN tweets t ON t.parent=d.id WHERE d.depth<100
       ) SELECT * FROM d;
       CREATE INDEX selected_root ON selected(root);
      """)
      mapped=db.execute("SELECT count(*) FROM root_map").fetchone()[0]; seed_count=db.execute("SELECT count(*) FROM seeds").fetchone()[0]
      quality["cycle_or_depth_cap_count"]=seed_count-mapped
      quality["orphan_count"]=db.execute("SELECT count(*) FROM selected s JOIN tweets t ON t.id=s.id LEFT JOIN tweets p ON p.id=t.parent WHERE t.parent IS NOT NULL AND p.id IS NULL").fetchone()[0]
      stats=Counter({"total_reconstructed_threads":0,"usable_customer_support_threads":0,"one_message_threads":0,"two_message_threads":0,"three_or_more_message_threads":0}); depths=[]
      with output_path.open("w",encoding="utf-8",newline="") as out:
       for (root,) in db.execute("SELECT root FROM roots ORDER BY CAST(root AS INTEGER),root"):
        rows=db.execute("SELECT t.*,s.depth FROM selected s JOIN tweets t ON t.id=s.id WHERE s.root=? ORDER BY t.stamp,t.id",(root,)).fetchall()
        messages=[]; cross=0; has_spotify=False; has_customer=False
        byid={r["id"]:r for r in rows}
        for r in rows:
         children=[x[0] for x in db.execute("SELECT id FROM tweets WHERE parent=? ORDER BY CAST(id AS INTEGER),id",(r["id"],))]
         parent=byid.get(r["parent"])
         if parent and ((r["author"]==SPOTIFY) != (parent["author"]==SPOTIFY)): cross+=1
         has_spotify|=r["author"]==SPOTIFY; has_customer|=bool(r["inbound"])
         messages.append({"tweet_id":r["id"],"author_id":r["author"],"inbound":bool(r["inbound"]),"created_at":r["created"],"text":r["text"],"parent_tweet_id":r["parent"],"response_tweet_ids":ids(r["response"]),"derived_child_tweet_ids":children,"conversation_depth":r["depth"],"reconstruction_flags":(["missing_parent"] if r["parent"] and r["parent"] not in byid else [])})
        flags=[]
        if any(m["reconstruction_flags"] for m in messages): flags.append("orphaned_parent_reference")
        if root not in {r["root"] for r in db.execute("SELECT root FROM root_map WHERE root=?",(root,))}: flags.append("cycle_or_depth_cap")
        record={"conversation_thread_id":f"spotify_root_{root}","thread_root_tweet_id":root,"ordered_messages":messages,"conversation_depth":max((m["conversation_depth"] for m in messages),default=0),"contains_customer_and_spotify":bool(has_customer and has_spotify),"customer_brand_interaction_turn_count":cross,"contains_two_or_more_customer_brand_interaction_turns":cross>=2,"reconstruction_flags":flags}
        out.write(json.dumps(record,ensure_ascii=False)+"\n"); stats["total_reconstructed_threads"]+=1; depths.append(record["conversation_depth"])
        if has_customer and has_spotify: stats["usable_customer_support_threads"]+=1
        if len(messages)==1: stats["one_message_threads"]+=1
        elif len(messages)==2: stats["two_message_threads"]+=1
        else: stats["three_or_more_message_threads"]+=1
      stats.update(quality); stats["depth_distribution"]={"median":percentile(depths,.5),"p90":percentile(depths,.9),"max":max(depths,default=0)}; stats["execution_seconds"]=round(time.monotonic()-started,1)
      after=input_path.stat()
      if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise RuntimeError("raw CSV changed during reconstruction")
      stats_path.write_text(json.dumps(dict(stats),indent=2),encoding="utf-8")
      return stats
    finally: db.close();Path(name).unlink(missing_ok=True)
def main():
 p=argparse.ArgumentParser();p.add_argument("--input",type=Path,default=Path("data/raw/twcs.csv"));p.add_argument("--output",type=Path,default=Path("data/processed/spotify_conversations.jsonl"));p.add_argument("--stats",type=Path,default=Path("data/processed/spotify_conversation_stats.json"));a=p.parse_args()
 if not a.input.is_file():p.error("input does not exist")
 s=reconstruct(a.input,a.output,a.stats);print(f"Wrote {a.output} ({s['total_reconstructed_threads']} threads)")
if __name__=="__main__": main()
