# SpotifyCares conversation reconstruction

Run from the repository root:

```powershell
python scripts/reconstruct_spotify_conversations.py
```

The script streams the raw CSV into a temporary on-disk SQLite reply graph. A
conversation is a root-based connected reply component containing at least one
`SpotifyCares` tweet: roots are found by walking each Spotify tweet's parent
chain, then all descendants of those roots are included. Records are written in
deterministic root and timestamp/tweet-ID order.

Missing parents terminate the chain at the last present tweet and are retained
with `missing_parent` / `orphaned_parent_reference` flags. Duplicate IDs are
ignored after their first CSV occurrence and counted; malformed self-parent or
invalid-direction records are counted. Original `response_tweet_id` lists are
preserved verbatim as parsed IDs; derived child IDs come from parent links and
may differ because response lists are one-to-many metadata.

Limitations: public links do not capture private conversations. The reconstructed
component can include messages from non-Spotify accounts sharing its root.
