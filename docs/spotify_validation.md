# SpotifyCares forensic validation

## Methodology

Independent raw-CSV audit using two streaming passes and a temporary SQLite reply index. It does not reuse prior interaction tables. Samples are deterministic: lowest SHA-256 tweet IDs.

## Relationship validation

| Metric | Value |
|---|---:|
| Inbound messages replying directly to Spotify | 15,096 |
| Inbound messages with direct Spotify reply | 41,585 |
| Associated inbound messages | 45,180 |
| Independent response rate | 0.920429 |
| Existing response rate | 0.920429 |
| Difference | 0.000000 |

The existing 0.9204 result reproduces exactly. Denominator is the union of customer messages receiving a Spotify reply and messages replying to Spotify; numerator is the distinct direct-reply customer set.

Deterministic valid relationship examples:
- Customer `2886004` -> Spotify `2886003`
- Customer `2047773` -> Spotify `2047772`
- Customer `2047773` -> Spotify `2047774`
- Customer `1952178` -> Spotify `1952177`
- Customer `1952178` -> Spotify `1952179`

## Thread and multi-turn validation

Roots: 28,277; one-message: 19,006; two-message: 1,718; 3+ message: 7,553; median depth: 2; p90: 5; cycle/depth-cap hits: 0. Dataset checks: duplicate IDs 0, missing referenced parents 3,862, self-parent links 0.

### Root `680593`
- `680593` customer/inbound `282399` Thu Oct 05 16:47:47 +0000 2017 parent `none` — @SpotifyCares do you have an Apple Watch app?
- `680592` brand/outbound `SpotifyCares` Thu Oct 05 17:32:35 +0000 2017 parent `680593` — @282399 1: Hi there! We're afraid we don't have an app on the Apple Watch. We suggest checking out the official idea and add your vote...

### Root `2621333`
- `2621333` customer/inbound `740670` Fri Nov 17 15:23:29 +0000 2017 parent `none` — @SpotifyCares hello yes i’d like to know why you’re taking money out of my account when i don’t even have any premium set up
- `2621332` brand/outbound `SpotifyCares` Fri Nov 17 16:09:45 +0000 2017 parent `2621333` — @740670 Hey there! Can you DM us your account's email address and username? We'll take a look backstage /KL https://t.co/ldFdZRiNAt

### Root `1759164`
- `1759164` customer/inbound `529512` Tue Nov 07 17:24:44 +0000 2017 parent `none` — @SpotifyCares I have 2 different accounts and I paid the wrong one how do I switch my premium to my other account?
- `1759163` brand/outbound `SpotifyCares` Tue Nov 07 17:32:23 +0000 2017 parent `1759164` — @529512 Hey, help's here! We've just replied to your DM. Check it out. Let's carry on chatting there 🙂 /MC

### Root `2751307`
- `2751307` customer/inbound `738107` Tue Nov 21 00:34:07 +0000 2017 parent `none` — Can we start calling developers out on that crap app update notes macro "we're always making improvements"?   Lookin at you, @115888.
- `2751306` brand/outbound `SpotifyCares` Tue Nov 21 00:43:40 +0000 2017 parent `2751307` — @738107 Hey! We're taking in your comments, and we'll be sure to pass them on to the right team /AR

### Root `2047775`
- `2047775` customer/inbound `605597` Thu Oct 05 12:27:38 +0000 2017 parent `none` — .@115888 So, your idea of “shuffle” is to play all songs on my playlist by the same artist in a row, then do the same for the next artist?
- `2047774` brand/outbound `SpotifyCares` Thu Oct 05 12:43:45 +0000 2017 parent `2047775` — @605597 Hi Alex! We’ve recently made some improvements to our shuffle algorithm. We’d love to hear your feedback here: https://t.co/T3vZnSL3od /GK
- `2047773` customer/inbound `605597` Thu Oct 05 13:39:22 +0000 2017 parent `2047774` — @SpotifyCares You made changed in Feb of 2016.  I’ve only been using Spotify since March of 2017, so that change was already implemented.

## Resolution-proxy audit

Existing formula: `terminal brand-reply tweet rows / distinct inbound customer parents with a Spotify reply`. This is a no-observed-public-child proxy, **not resolution**.

| Category | Tweet | Text |
|---|---|---|
| E. Unclear | `680592` | @282399 1: Hi there! We're afraid we don't have an app on the Apple Watch. We suggest checking out the official idea and add your vote... |
| B. Customer-service continuation | `2621332` | @740670 Hey there! Can you DM us your account's email address and username? We'll take a look backstage /KL https://t.co/ldFdZRiNAt |
| E. Unclear | `1759163` | @529512 Hey, help's here! We've just replied to your DM. Check it out. Let's carry on chatting there 🙂 /MC |
| E. Unclear | `2751306` | @738107 Hey! We're taking in your comments, and we'll be sure to pass them on to the right team /AR |
| E. Unclear | `2320573` | @672479 We've just sent a DM your way. Let's carry on chatting there /SV |
| C. Generic acknowledgement | `124143` | @143765 Hey Katie, sorry to hear that! Check out the steps under “Downloads unexpectedly removed” at https://t.co/38J7tFlIBF. They should help with this /NS |
| E. Unclear | `1142188` | @153724 @116130 Hi! We've just replied to your DM. We'll carry on helping there /MQ |
| C. Generic acknowledgement | `2407014` | @199409 We understand. We've already passed on the suggestion for more offers to the relevant folks. Fingers crossed we'll have one for you /PB |
| B. Customer-service continuation | `1795073` | @539411 Hey there! We don't have Filipino support, but we'd be happy to help in English. Can you DM us your account's email address? /JN https://t.co/ldFdZRiNAt |
| B. Customer-service continuation | `369359` | @203507 Hey, help's here! Can you let us know more about what you have in mind? We'll see what we can suggest /JS |
| E. Unclear | `2504231` | @714183 Hey! We have more info about this here: https://t.co/pXBCq8GlsI. Give us a shout if you have any questions /DN |
| B. Customer-service continuation | `1001237` | @357039 Hey Tracy! We have some important info to share. Can you send us a DM? /AR https://t.co/ldFdZR1cbT |
| A. Plausible resolution/closure | `1853350` | @554588 Hi Dawson, sorry for the delay! We're glad to hear that you were helped out. If you need us again, just... https://t.co/AUc7DGJpgF /JQ |
| C. Generic acknowledgement | `2822723` | @786590 Thanks for the heads-up. We've passed on your feedback to the right team. Let us know if we can help with anything else 🙂 /AY |
| B. Customer-service continuation | `2731517` | @765734 Hey Richard! Can you DM us your account's email address? We'll take a look backstage /SJ https://t.co/ldFdZRiNAt |
| B. Customer-service continuation | `829611` | @317565 Can you DM us your account's email address? We'll take a look backstage /KC https://t.co/ldFdZR1cbT |
| B. Customer-service continuation | `466067` | @225888 Hey Megan! Could you send us a DM with your account's email address? We'll take a look backstage /FR https://t.co/ldFdZRiNAt |
| C. Generic acknowledgement | `2917856` | @807638 Hey, thanks for the report! We had a little hiccup earlier, but everything should be running just fine now /JS |
| B. Customer-service continuation | `2251332` | @655859 Cool! Let us know if you ever need us again. We'd be... https://t.co/LgAM6ky9Vv 💚 /NG |
| B. Customer-service continuation | `1265339` | @172878 Hey Andy! Can you let us know what's happening exactly? We'll see what we can suggest /PL |

## Tesco anomaly

Tesco: 27,424 terminal brand replies / 25,282 distinct customer parents = 1.084724. There are 38,468 brand-reply rows, or 13,186 more reply rows than distinct parents. This is a counting-unit mismatch caused by one-to-many replies, not duplicate IDs or duplicate joins. The old >1 value is possible but should not be interpreted as a rate.

## Recommendation

**PASS — retain SpotifyCares provisionally.** Relationship and response-rate evidence independently reproduce. Limitations: public reply links do not capture private outcomes or resolution; categories are deterministic keyword audit labels, not semantic truth. Elapsed: 28.6s.
