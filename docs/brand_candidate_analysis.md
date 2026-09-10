# Second-stage brand candidate analysis

## Reproducibility and scope

```powershell
python scripts/analyze_brand_candidates.py
```

The existing profile has 108 behavioral outbound-account candidates. This run
analyzes its top 20 by available outbound history to ensure sufficient
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
| SpotifyCares | 1 | 1 | 45,180 | 0.920 | 0.328 | 26,519 |
| AppleSupport | 2 | 1 | 119,895 | 0.889 | 0.298 | 50,733 |
| hulu_support | 3 | 1 | 24,556 | 0.874 | 0.361 | 13,947 |
| Delta | 4 | 1 | 41,529 | 0.870 | 0.393 | 27,592 |
| sainsburys | 5 | 1 | 20,660 | 0.858 | 0.535 | 23,058 |
| SouthwestAir | 6 | 1 | 33,211 | 0.852 | 0.305 | 26,817 |
| ChipotleTweets | 7 | 1 | 21,887 | 0.848 | 0.322 | 18,144 |
| AskPlayStation | 8 | 1 | 22,185 | 0.841 | 0.425 | 13,556 |
| Tesco | 9 | 1 | 30,093 | 0.840 | 0.673 | 27,721 |
| Uber_Support | 10 | 1 | 65,924 | 0.837 | 0.325 | 32,902 |
| AmazonHelp | 11 | 1 | 189,132 | 0.819 | 0.601 | 100,587 |
| AmericanAir | 12 | 1 | 45,314 | 0.805 | 0.402 | 31,230 |
| VirginTrains | 13 | 1 | 33,851 | 0.776 | 0.603 | 19,289 |
| comcastcares | 14 | 2 | 34,175 | 0.889 | 0.306 | 20,910 |
| TMobileHelp | 15 | 2 | 38,782 | 0.872 | 0.307 | 20,770 |
| British_Airways | 16 | 2 | 29,255 | 0.823 | 0.528 | 21,956 |
| sprintcare | 17 | 2 | 24,364 | 0.822 | 0.400 | 14,826 |
| XboxSupport | 18 | 2 | 25,842 | 0.782 | 0.528 | 16,246 |
| GWRHelp | 19 | 2 | 24,504 | 0.755 | 0.622 | 15,111 |
| Ask_Spectrum | 20 | 3 | 28,921 | 0.864 | 0.300 | 16,822 |

## Evidence for the leading candidate

The leading candidate under the no-weight Pareto ranking is **SpotifyCares**:
45,180 structurally associated customer tweets, a direct response
rate of 0.920, multi-turn-thread proportion of
0.328, and 26,519 observed customer terms.
This supports substantial retrievable public interaction history and measurable
language variety. Against over-interpreting it: the dataset does not expose
company identity, private outcomes, satisfaction, or actual issue labels; its
terminal-response proxy cannot establish resolution.

## Data quality findings

| Check | Count |
| --- | ---: |
| duplicate tweet ids | 0 |
| missing parent field | 794,335 |
| missing parent targets | 3,862 |
| missing response field | 1,040,629 |
| multi response rows | 222,426 |
| response targets | 2,186,077 |
| rows | 2,811,774 |
| self parent | 0 |

Missing parent targets are reply IDs absent from the CSV. Duplicate IDs are
computed from the exact SQLite primary-key count. The script checks raw-file
size and modification time before and after the run.

## Limitations

Only the top 20 of 108 profile candidates are deeply analyzed; this is
a scope limit, not a claim that the remaining accounts are unsuitable. Reply
links can reconstruct public structural chains but not all conversations, and
the response-link list is used only for data-quality counts because it can be
one-to-many. Text metrics are diversity proxies, not an intent classifier or
quality judgment. Elapsed time: 109.3 seconds.
