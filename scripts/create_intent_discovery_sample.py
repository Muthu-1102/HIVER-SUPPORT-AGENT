#!/usr/bin/env python3
"""
Deterministic Stratified Sampling for SpotifyCares Intent Discovery.

Produces data/processed/intent_discovery_sample.jsonl containing ~400 representative
conversations for qualitative intent taxonomy development.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

def get_customer_text(conv):
    """Concatenate text from all inbound customer messages in thread."""
    msgs = [m['text'] for m in conv.get('ordered_messages', []) if m.get('inbound')]
    return " ".join(msgs) if msgs else ""

def sample_conversations(input_path, output_path, target_size=400, seed=42, n_clusters=8):
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Reading conversations from {input_path}...")
    convs = []
    with input_path.open('r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                convs.append(json.loads(line))

    print(f"Total conversations loaded: {len(convs)}")
    
    # Filter valid conversations
    valid_convs = [c for c in convs if c.get('contains_customer_and_spotify', False)]
    print(f"Valid Customer+Spotify conversations: {len(valid_convs)}")

    # 1. Categorize into Turn Strata
    # Strata target allocation: Single-Turn (50% = 200), Short Multi-Turn (30% = 120), Deep Multi-Turn (20% = 80)
    strata = {
        'single_turn': [],     # turns == 1
        'short_multi_turn': [],# turns in [2, 3]
        'deep_multi_turn': []  # turns >= 4
    }

    for c in valid_convs:
        turns = c.get('customer_brand_interaction_turn_count', 1)
        if turns == 1:
            strata['single_turn'].append(c)
        elif turns in [2, 3]:
            strata['short_multi_turn'].append(c)
        else:
            strata['deep_multi_turn'].append(c)

    print("Turn Strata Counts:")
    for k, v in strata.items():
        print(f"  - {k}: {len(v)}")

    # Strata target quotas
    quotas = {
        'single_turn': int(target_size * 0.50),      # 200
        'short_multi_turn': int(target_size * 0.30), # 120
        'deep_multi_turn': target_size - (int(target_size * 0.50) + int(target_size * 0.30)) # 80
    }

    # 2. Topic Stratification using TF-IDF + KMeans across all customer texts
    customer_texts = [get_customer_text(c) for c in valid_convs]
    vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
    X = vectorizer.fit_transform(customer_texts)

    kmeans = KMeans(n_clusters=n_clusters, random_state=seed, n_init=10)
    cluster_labels = kmeans.fit_predict(X)

    # Attach cluster label to each conversation
    for conv, label in zip(valid_convs, cluster_labels):
        conv['_topic_cluster'] = int(label)

    # 3. Stratified Deterministic Selection
    sampled_convs = []

    for stratum_name, stratum_convs in strata.items():
        quota = quotas[stratum_name]
        # Group by topic cluster within stratum
        by_cluster = {}
        for c in stratum_convs:
            cid = c['_topic_cluster']
            by_cluster.setdefault(cid, []).append(c)

        # Distribute quota proportionally across clusters
        cluster_quotas = {}
        allocated = 0
        clusters_present = sorted(by_cluster.keys())
        for cid in clusters_present:
            prop = len(by_cluster[cid]) / len(stratum_convs)
            c_quota = max(1, int(round(quota * prop)))
            cluster_quotas[cid] = c_quota
            allocated += c_quota

        # Adjust allocated quota to match exact stratum quota
        diff = quota - allocated
        idx = 0
        while diff != 0 and clusters_present:
            cid = clusters_present[idx % len(clusters_present)]
            if diff > 0:
                cluster_quotas[cid] += 1
                diff -= 1
            elif diff < 0 and cluster_quotas[cid] > 1:
                cluster_quotas[cid] -= 1
                diff += 1
            idx += 1

        # Deterministic sampling within (Stratum, Cluster) via SHA-256 hash of thread_id
        for cid in clusters_present:
            c_list = by_cluster[cid]
            c_quota = cluster_quotas[cid]
            # Deterministic sort using sha256 hash
            c_list_sorted = sorted(
                c_list,
                key=lambda x: hashlib.sha256(
                    f"{seed}_{stratum_name}_{cid}_{x['conversation_thread_id']}".encode('utf-8')
                ).hexdigest()
            )
            sampled_convs.extend(c_list_sorted[:c_quota])

    # Remove temporary internal cluster tag before saving
    for c in sampled_convs:
        c.pop('_topic_cluster', None)

    # Save to output file
    with output_path.open('w', encoding='utf-8') as f:
        for c in sampled_convs:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')

    print(f"\nSuccessfully created deterministic sample: {output_path}")
    print(f"Sample Size: {len(sampled_convs)}")

    # Audit & Distribution Check
    single_turn_cnt = sum(1 for c in sampled_convs if c.get('customer_brand_interaction_turn_count') == 1)
    multi_turn_cnt = sum(1 for c in sampled_convs if c.get('customer_brand_interaction_turn_count', 1) > 1)
    depths = Counter(c.get('conversation_depth', 0) for c in sampled_convs)

    print("\nSample Turn Distribution:")
    print(f"  - Single-Turn (1 turn): {single_turn_cnt} ({single_turn_cnt/len(sampled_convs)*100:.1f}%)")
    print(f"  - Multi-Turn (>1 turns): {multi_turn_cnt} ({multi_turn_cnt/len(sampled_convs)*100:.1f}%)")
    print("\nConversation Depth Summary (Top 5):", depths.most_common(5))

    return len(sampled_convs)

def main():
    parser = argparse.ArgumentParser(description="Deterministic sampling for intent discovery")
    parser.add_argument("--input", type=Path, default=Path("data/processed/spotify_conversations.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/intent_discovery_sample.jsonl"))
    parser.add_argument("--sample-size", type=int, default=400)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-clusters", type=int, default=8)
    args = parser.parse_args()

    sample_conversations(
        input_path=args.input,
        output_path=args.output,
        target_size=args.sample_size,
        seed=args.seed,
        n_clusters=args.n_clusters
    )

if __name__ == "__main__":
    main()
