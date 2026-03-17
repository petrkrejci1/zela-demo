# Scripts

## precompute_regions.py

### What it does

Generates `leader_routing/data/validator_regions.csv` — a precomputed map of
Solana validator identity pubkeys to their approximate geographic region.

This file is **embedded at compile time** into the `leader_routing` WASM
procedure (via Rust's `include_str!`). The procedure uses it as its primary
lookup table to answer "which Zela region is closest to the current leader?"

### How it works

1. Fetches all active Solana mainnet validators from `getVoteAccounts` and
   their gossip IPs from `getClusterNodes`.
2. Batch-queries [ip-api.com](https://ip-api.com) (free, no token required) to
   resolve each unique IP to a country code. Retries failed batches with
   exponential backoff.
3. Maps each country code to the nearest Zela region using a hardcoded table.
4. Writes a sorted CSV: `pubkey,country,region`.

### Region mapping rule

| Countries | → Zela Region |
|---|---|
| Europe (DE, FR, NL, GB, SE, FI, PL, …) | **Frankfurt** |
| Middle East + Central Asia (AE, SA, TR, IL, KZ, …) | **Dubai** |
| North + West Africa (EG, MA, DZ, NG, GH, …) | **Frankfurt** |
| East + South Africa (KE, ZA, ET, TZ, …) | **Dubai** |
| Americas (US, CA, BR, MX, …) | **NewYork** |
| Asia-Pacific + Oceania (JP, SG, KR, AU, IN, …) | **Tokyo** |

The North/West Africa split uses longitude as the deciding factor: countries
west of roughly 30°E are closer to Frankfurt; east of that threshold are closer
to Dubai.

### Requirements

```
pip install requests
```

### Usage

```bash
python3 scripts/precompute_regions.py
```

Output is written to `leader_routing/data/validator_regions.csv`. The script
prints a region distribution summary to stderr when it finishes.

Expected runtime: ~2–3 minutes for ~800 validators (ip-api.com rate limit is
~15 batch requests/min; the script is conservative at ~12/min).

### Reproducibility

The validator set and their IPs change over time as validators join, leave, or
migrate hosting. Re-running the script regenerates the map from the current
mainnet state. The region assignment for a given IP is deterministic given the
static country→region table in the script.

**To reproduce:**
1. Install `requests` (`pip install requests`)
2. Run `python3 scripts/precompute_regions.py`
3. The script self-contains everything — no API token, no extra config

### What happens with unknown leaders at runtime

The precomputed CSV covers all **currently active** validators. At runtime, a
newly joined or recently rotated validator may not be in the CSV. The procedure
handles this with a two-step fallback:

1. **IP fallback**: looks up the leader's gossip address via `getClusterNodes`,
   then maps the IP using a coarse RIR-based table embedded in the Rust code.
2. **Final fallback**: if the validator is offline (not in gossip), returns
   `leader_geo: "UNKNOWN"` and defaults `closest_region` to `"Frankfurt"` —
   the most common region for Solana validators (~60% of stake).

The CSV should be refreshed periodically (e.g. monthly) to keep the primary
lookup current.
