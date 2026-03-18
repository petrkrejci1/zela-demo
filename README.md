# Zela Custom Procedures — Example Repository

This repository contains example **custom procedures** built on the [Zela](https://zela.io) platform. Each procedure is an independent Rust crate compiled to WebAssembly.

---

## Repository Structure

```
.
├── block_time/           # Procedure: BlockTime
├── hello_world/          # Procedure: HelloWorld
├── leader_routing/       # Procedure: LeaderRouting
│   └── data/
│       └── validator_regions.csv   # precomputed validator → region map
├── priority_fees/        # Procedure: PriorityFees
├── scripts/              # Offline tooling (not deployed)
│   ├── precompute_regions.py       # regenerates validator_regions.csv
│   └── SCRIPTS_DOCS.md
├── Cargo.toml
├── Cargo.lock
├── run-procedure.sh
├── shell.nix
└── .gitignore
```

---

## Executing a Procedure

All procedures are called via JSON-RPC over HTTPS. The steps below apply to every procedure in this repository.

### Step 1 — Get a project key

In the [Zela Dashboard](https://zela.io) go to your project → **Settings → Keys** and create a key. Fill in `.env` using `.env.example` as a template.

### Step 2 — Obtain a JWT

```bash
source .env

JWT=$(curl -s \
  --user "$ZELA_PROJECT_KEY_ID:$ZELA_PROJECT_KEY_SECRET" \
  --data 'grant_type=client%5Fcredentials' \
  --data 'scope=zela%2Dexecutor%3Acall' \
  https://auth.zela.io/realms/zela/protocol/openid-connect/token \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

The token is valid for 1 hour. You can reuse it for multiple calls within that window.

### Step 3 — Call the executor

```bash
curl --header "authorization: Bearer $JWT" \
     --header "Content-Type: application/json" \
     --data '{"jsonrpc":"2.0","id":1,"method":"zela.PROCEDURE_NAME#COMMIT_HASH","params":PARAMS}' \
     https://executor.zela.io
```

Where:
- `PROCEDURE_NAME` — the Cargo package name (e.g. `leader_routing`)
- `COMMIT_HASH` — the full git commit hash of the build shown in the Zela Dashboard
- `PARAMS` — procedure input as JSON (`null` for procedures with no inputs)

The first call after a deployment may take a few seconds while the executor loads the WASM into memory. Subsequent calls use the cached instance.

### Using the helper script

`run-procedure.sh` wraps steps 2 and 3 in one command:

```bash
source .env
./run-procedure.sh "PROCEDURE_NAME#COMMIT_HASH" 'PARAMS'
```

---

## Procedures

### 1. `hello_world`

A minimal example demonstrating how to accept input parameters, perform computation, and return a result (or an error).

**Input**

| Field           | Type  | Description    |
| --------------- | ----- | -------------- |
| `first_number`  | `i32` | First operand  |
| `second_number` | `i32` | Second operand |

**Output**

| Field | Type  | Description                  |
| ----- | ----- | ---------------------------- |
| `sum` | `i32` | Sum of the two input numbers |

**Error case**

If `first_number` is `0`, the procedure returns an error:

```json
{
  "code": 400,
  "message": "Example of an error -- number cannot be 0.",
  "data": null
}
```

---

### 2. `block_time`

Queries the Solana blockchain to retrieve the latest block time and block hash, then compares it against the system clock to measure RPC latency.

**Input**

None — this procedure takes no parameters (pass an empty object `{}`).

**Output**

| Field          | Type     | Description                                                    |
| -------------- | -------- | -------------------------------------------------------------- |
| `block_time`   | `i64`    | Unix timestamp of the latest confirmed block (seconds)         |
| `block_hash`   | `string` | Base58-encoded hash of the latest block                        |
| `system_time`  | `i64`    | System clock timestamp at the start of the call (milliseconds) |
| `time_elapsed` | `i64`    | Total RPC round-trip time in **microseconds**                  |

**Example response**

```json
{
  "block_time": 1712000000,
  "block_hash": "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d",
  "system_time": 1712000000123,
  "time_elapsed": 340210
}
```

---

### 3. `leader_routing`

Answers: **"Which Zela server region should handle my request right now, to be closest to the current Solana leader?"**

The procedure fetches the current slot and its leader from Solana mainnet, maps the leader to a coarse geographic location, and returns the nearest Zela region.

**Input**

None — pass `"params":null`.

**Output**

| Field            | Type     | Description                                                                                 |
| ---------------- | -------- | ------------------------------------------------------------------------------------------- |
| `slot`           | `u64`    | Current Solana slot                                                                         |
| `leader`         | `string` | Identity pubkey of the current slot leader                                                  |
| `leader_geo`     | `string` | Coarse location of the leader (ISO 3166-1 alpha-2 country code, e.g. `"DE"`) or `"UNKNOWN"` |
| `closest_region` | `string` | Nearest Zela region: `Frankfurt` \| `Dubai` \| `NewYork` \| `Tokyo`                         |

**Example call**

```bash
# Get JWT first — see "Executing a Procedure" section above
curl --header "authorization: Bearer $JWT" \
     --header "Content-Type: application/json" \
     --data '{"jsonrpc":"2.0","id":1,"method":"zela.leader_routing#bd54645dfa3eb4afc2063d9f19b8453cd5bee1da","params":null}' \
     https://executor.zela.io
```

**Example response**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "slot": 407045388,
    "leader": "2AKKnirWVZMhnzuwqpizw9SwfZjGpRFLx2zCCNtPWpbc",
    "leader_geo": "SG",
    "closest_region": "Tokyo"
  }
}
```

**How to build**

```bash
# native (for local testing)
cargo build -p leader_routing

# run the integration test against Solana mainnet
cargo test -p leader_routing -- --nocapture

# WASM artifact (for Zela deployment)
cargo build -p leader_routing --target wasm32-wasip2 --release
# artifact: target/wasm32-wasip2/release/leader_routing.wasm
```

**Geo mapping rule**

The procedure maps each leader to a Zela region using a two-step lookup:

1. **Precomputed map** (primary): `leader_routing/data/validator_regions.csv` is embedded at compile time. It was generated offline by `scripts/precompute_regions.py`, which resolved every active validator's gossip IP via [ip-api.com](https://ip-api.com) and applied the country-to-region table below.

2. **RIR-based IP fallback** (for validators not in the map): fetches the leader's gossip address from `getClusterNodes` and maps the IP using Regional Internet Registry (RIR) first-octet ranges.

3. **Final fallback**: if the leader is offline or completely unresolvable, returns `leader_geo: "UNKNOWN"` and defaults `closest_region` to `"Frankfurt"`.

| Countries                                          | → Zela Region |
| -------------------------------------------------- | ------------- |
| Europe (DE, FR, NL, GB, SE, FI, PL, …)             | **Frankfurt** |
| Middle East + Central Asia (AE, SA, TR, IL, KZ, …) | **Dubai**     |
| North + West Africa (EG, MA, DZ, NG, …)            | **Frankfurt** |
| East + South Africa (KE, ZA, ET, TZ, …)            | **Dubai**     |
| Americas (US, CA, BR, MX, …)                       | **NewYork**   |
| Asia-Pacific + Oceania (JP, SG, KR, AU, IN, …)     | **Tokyo**     |

**Assumptions, failure modes, and anti-flapping**

The precomputed map covers all active Solana validators at the time of generation (~774 validators). A validator not in the map triggers the IP fallback, which uses coarse RIR-based first-octet ranges — accurate enough for the large cloud providers (Hetzner, AWS, OVH) that host the majority of validators.

The region assignment is **deterministic**: the same validator always maps to the same region regardless of when or how often the procedure is called, so there is no flapping. The only scenario where `closest_region` could change for a validator is if they physically migrate their node to a different region, which is a deliberate infrastructure event — not noise. The CSV should be regenerated periodically (e.g. weekly) to keep the primary map current; see `scripts/SCRIPTS_DOCS.md` for instructions.

Possible failure modes: `getSlot` or `getSlotLeaders` returning an error (e.g. RPC unavailability) causes the procedure to return a JSON-RPC error with code `1` and a human-readable message. A missing cluster-node entry for an offline leader is handled gracefully by falling back to Frankfurt rather than failing.

---

### 4. `priority_fees`

Scans one or more Solana blocks and computes the average priority fee paid by non-voting transactions.

The procedure supports two input modes — you must pass **exactly one** of them.

**Input: Latest N blocks**

```json
{
  "block_count": 10
}
```

| Field         | Type    | Description                                    |
| ------------- | ------- | ---------------------------------------------- |
| `block_count` | `usize` | Number of most recent confirmed blocks to scan |

**Input: Specific blocks**

```json
{
  "blocks": [295000000, 295000001, 295000005]
}
```

| Field    | Type    | Description                           |
| -------- | ------- | ------------------------------------- |
| `blocks` | `[u64]` | List of specific slot numbers to scan |

**Output**

| Field                           | Type    | Description                                                           |
| ------------------------------- | ------- | --------------------------------------------------------------------- |
| `total_transactions`            | `usize` | Total number of transactions scanned across all blocks                |
| `vote_transactions`             | `usize` | Number of transactions skipped because they are voting transactions   |
| `latest_block`                  | `u64`   | Slot number of the last processed block                               |
| `average_priority_fee_lamports` | `u64`   | Average priority fee (in lamports) across all non-voting transactions |

> **Note:** Priority fee = total fee − base fee (5000 lamports). Transactions with a fee below the base fee are skipped with an error log.

---
