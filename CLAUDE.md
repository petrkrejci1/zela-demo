# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Build a crate natively (local testing)
cargo build -p <crate_name>

# Build for WASM deployment
cargo build -p <crate_name> --target wasm32-wasip2 --release

# Run tests (hit Solana mainnet RPC — requires network)
cargo test -p <crate_name> -- --nocapture

# Lint / format
cargo clippy -p <crate_name>
cargo fmt

# Deploy and execute a procedure
ZELA_PROJECT_KEY_ID=<key> ZELA_PROJECT_KEY_SECRET=<secret> \
  ./run-procedure.sh 'procedure#commit_hash' '{"json":"params"}'
```

WASM artifacts land in `target/wasm32-wasip2/release/<crate_name>.wasm`.

## Architecture

This is a **Cargo workspace** of four independent Zela custom procedures. Each crate compiles to a WebAssembly library (`cdylib`) that runs on the Zela platform.

### Procedure Pattern

Every crate follows the same structure:
1. A struct implementing the `CustomProcedure` trait from `zela-std`
2. `Input` / `Output` structs derived with `serde`
3. An async `run()` method as the entry point
4. A `zela_custom_procedure!()` macro invocation to register the WASM binding

### Dual-Target Compilation

All crates with Solana RPC calls use conditional compilation:
- `#[cfg(not(target_arch = "wasm32"))]` — uses `solana_client` for local/test builds
- `#[cfg(target_arch = "wasm32")]` — uses `zela_std::rpc_client` (Zela's proxied RPC) for deployment

This lets you run `cargo test` locally against Solana mainnet while producing a standalone WASM binary for Zela.

### `leader_routing` Crate

The most complex procedure. Maps the current Solana slot leader to the nearest Zela region (Frankfurt / Dubai / NewYork / Tokyo) using a three-layer strategy:

1. **Precomputed CSV lookup** (`data/validator_regions.csv`, embedded at compile time via `include_str!`) — maps ~774 validator pubkeys to `(country, region)`. Regenerate with `scripts/precompute_regions.py`.
2. **IP → RIR fallback** — fetches the leader's gossip IP via `getClusterNodes`, then maps to a region using hardcoded RIR first-octet ranges.
3. **Unknown fallback** — returns `leader_geo: "UNKNOWN"` and defaults `closest_region` to `"Frankfurt"`.

The country → region mapping logic lives inline in `leader_routing/src/lib.rs`. Africa is split at 30°E longitude (west → Frankfurt, east → Dubai).

### Workspace Dependencies

`zela-std` is a git dependency (locked to a specific commit hash in `Cargo.lock`). It provides `CustomProcedure`, `RpcClient`, `zela_custom_procedure!`, and `RpcError`. All other workspace-level deps (`serde`, `log`) are inherited by each crate.

### Crates Overview

| Crate | Purpose | Input | Output |
|---|---|---|---|
| `hello_world` | Minimal template | `{first_number, second_number}` | `{sum}` |
| `block_time` | Solana RPC latency probe | none | block time + latency μs |
| `leader_routing` | Current leader → closest Zela region | none | slot, leader pubkey, geo, region |
| `priority_fees` | Average priority fee over N blocks | `{block_count}` or `{blocks: [...]}` | avg fee in lamports |

### `scripts/`

Python tooling — not compiled or deployed. `precompute_regions.py` regenerates `leader_routing/data/validator_regions.csv` by querying validator IPs and geolocating them. See `scripts/SCRIPTS_DOCS.md` for usage.
