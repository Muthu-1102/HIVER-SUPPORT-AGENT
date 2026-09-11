import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/"scripts"))
from scripts.reconstruct_spotify_conversations import reconstruct

HEADER="tweet_id,author_id,inbound,created_at,text,response_tweet_id,in_response_to_tweet_id\n"
def row(i,a,inb,text,parent="",responses=""):
 return f'{i},{a},{inb},Tue Oct 31 22:10:4{i%10} +0000 2017,"{text}","{responses}","{parent}"\n'
def run(tmp_path, rows):
 raw=tmp_path/"in.csv";raw.write_text(HEADER+"".join(rows),encoding="utf-8");out=tmp_path/"out.jsonl";stats=tmp_path/"stats.json";reconstruct(raw,out,stats);return [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()],json.loads(stats.read_text())
def test_parent_child_chronology_and_multimessage(tmp_path):
 records,stats=run(tmp_path,[row(1,"u",True,"need help",responses="2"),row(2,"SpotifyCares",False,"reply",1,responses="3"),row(3,"u",True,"more",2)])
 r=records[0]; assert [m["tweet_id"] for m in r["ordered_messages"]]==["1","2","3"];assert r["customer_brand_interaction_turn_count"]==2;assert r["contains_two_or_more_customer_brand_interaction_turns"];assert r["ordered_messages"][1]["derived_child_tweet_ids"]==["3"];assert stats["three_or_more_message_threads"]==1
def test_orphan_duplicate_and_determinism(tmp_path):
 rows=[row(1,"SpotifyCares",False,"orphan",99),row(1,"SpotifyCares",False,"duplicate",99)]
 a,sa=run(tmp_path,rows);b,sb=run(tmp_path,rows);assert a==b;assert sa["duplicate_count"]==1;assert sa["orphan_count"]==1;assert a[0]["ordered_messages"][0]["reconstruction_flags"]==["missing_parent"]
