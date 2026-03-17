import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Region mapping
# ---------------------------------------------------------------------------

# ISO 3166-1 alpha-2 country code → Zela region.
# Rule: nearest Zela server by geography.
#   Europe                    → Frankfurt
#   Middle East + E. Africa   → Dubai
#   N. Africa + W. Africa     → Frankfurt  (closer than Dubai)
#   Americas                  → NewYork
#   Asia-Pacific + Oceania    → Tokyo
COUNTRY_TO_REGION: dict[str, str] = {
    # ── Europe → Frankfurt ──────────────────────────────────────────────────
    "DE": "Frankfurt",
    "FR": "Frankfurt",
    "NL": "Frankfurt",
    "GB": "Frankfurt",
    "SE": "Frankfurt",
    "FI": "Frankfurt",
    "NO": "Frankfurt",
    "DK": "Frankfurt",
    "PL": "Frankfurt",
    "CZ": "Frankfurt",
    "AT": "Frankfurt",
    "CH": "Frankfurt",
    "BE": "Frankfurt",
    "IE": "Frankfurt",
    "ES": "Frankfurt",
    "IT": "Frankfurt",
    "PT": "Frankfurt",
    "RO": "Frankfurt",
    "HU": "Frankfurt",
    "BG": "Frankfurt",
    "HR": "Frankfurt",
    "SK": "Frankfurt",
    "SI": "Frankfurt",
    "LT": "Frankfurt",
    "LV": "Frankfurt",
    "EE": "Frankfurt",
    "UA": "Frankfurt",
    "RU": "Frankfurt",
    "RS": "Frankfurt",
    "GR": "Frankfurt",
    "BY": "Frankfurt",
    "MD": "Frankfurt",
    "LU": "Frankfurt",
    "MT": "Frankfurt",
    "CY": "Frankfurt",
    "IS": "Frankfurt",
    "AL": "Frankfurt",
    "MK": "Frankfurt",
    "BA": "Frankfurt",
    "ME": "Frankfurt",
    "XK": "Frankfurt",
    "GE": "Frankfurt",
    "AM": "Frankfurt",
    "AZ": "Frankfurt",
    # ── Middle East / Gulf → Dubai ──────────────────────────────────────────
    "AE": "Dubai",
    "SA": "Dubai",
    "QA": "Dubai",
    "KW": "Dubai",
    "BH": "Dubai",
    "OM": "Dubai",
    "YE": "Dubai",
    "JO": "Dubai",
    "IL": "Dubai",
    "LB": "Dubai",
    "TR": "Dubai",
    "IQ": "Dubai",
    "IR": "Dubai",
    "SY": "Dubai",
    "PK": "Dubai",
    "AF": "Dubai",
    "KZ": "Dubai",
    "UZ": "Dubai",
    "TM": "Dubai",
    "TJ": "Dubai",
    "KG": "Dubai",
    # ── Africa ──────────────────────────────────────────────────────────────
    # North + West Africa → Frankfurt (longitude closer to Europe)
    "MA": "Frankfurt",
    "DZ": "Frankfurt",
    "TN": "Frankfurt",
    "LY": "Frankfurt",
    "NG": "Frankfurt",
    "GH": "Frankfurt",
    "SN": "Frankfurt",
    "CI": "Frankfurt",
    "CM": "Frankfurt",
    "EG": "Frankfurt",
    # East + South Africa → Dubai
    "ZA": "Dubai",
    "KE": "Dubai",
    "ET": "Dubai",
    "TZ": "Dubai",
    "UG": "Dubai",
    "MZ": "Dubai",
    "ZW": "Dubai",
    "MG": "Dubai",
    # ── Americas → NewYork ──────────────────────────────────────────────────
    "US": "NewYork",
    "CA": "NewYork",
    "MX": "NewYork",
    "BR": "NewYork",
    "AR": "NewYork",
    "CO": "NewYork",
    "CL": "NewYork",
    "PE": "NewYork",
    "VE": "NewYork",
    "EC": "NewYork",
    "BO": "NewYork",
    "PY": "NewYork",
    "UY": "NewYork",
    "CR": "NewYork",
    "PA": "NewYork",
    "GT": "NewYork",
    "HN": "NewYork",
    "SV": "NewYork",
    "NI": "NewYork",
    "DO": "NewYork",
    "CU": "NewYork",
    "JM": "NewYork",
    "TT": "NewYork",
    "PR": "NewYork",
    # ── Asia-Pacific + Oceania → Tokyo ───────────────────────────────────────
    "JP": "Tokyo",
    "SG": "Tokyo",
    "KR": "Tokyo",
    "TW": "Tokyo",
    "HK": "Tokyo",
    "CN": "Tokyo",
    "AU": "Tokyo",
    "NZ": "Tokyo",
    "IN": "Tokyo",
    "TH": "Tokyo",
    "VN": "Tokyo",
    "ID": "Tokyo",
    "MY": "Tokyo",
    "PH": "Tokyo",
    "BD": "Tokyo",
    "LK": "Tokyo",
    "MM": "Tokyo",
    "KH": "Tokyo",
    "MN": "Tokyo",
    "NP": "Tokyo",
    "MV": "Tokyo",
}

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
IP_API_BATCH_URL = "http://ip-api.com/batch"
# ip-api.com free tier: 100 IPs per batch, ~15 batches/min
BATCH_SIZE = 100
BATCH_SLEEP_SECONDS = 5.0  # conservative: ~12 batches/min
MAX_RETRIES = 3

OUTPUT_PATH = (
    Path(__file__).parent.parent / "leader_routing" / "data" / "validator_regions.csv"
)


def rpc(method: str, params=None) -> object:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    r = requests.post(SOLANA_RPC, json=payload, timeout=30)
    r.raise_for_status()
    result = r.json()
    if "error" in result:
        raise RuntimeError(f"RPC error: {result['error']}")
    return result["result"]


def fetch_validators() -> dict[str, str]:
    """Returns {identity_pubkey: gossip_ip} for all cluster nodes that have a gossip address."""
    print("Fetching cluster nodes...", file=sys.stderr)
    nodes = rpc("getClusterNodes")
    pubkey_to_ip: dict[str, str] = {}
    for node in nodes:
        gossip = node.get("gossip")
        if gossip:
            ip = gossip.split(":")[0]
            # skip private / loopback addresses — they won't resolve geographically
            if not (
                ip.startswith("10.")
                or ip.startswith("192.168.")
                or ip.startswith("172.")
                or ip == "127.0.0.1"
            ):
                pubkey_to_ip[node["pubkey"]] = ip
    print(f"  {len(pubkey_to_ip)} nodes with public gossip IPs", file=sys.stderr)
    return pubkey_to_ip


def fetch_active_pubkeys() -> set[str]:
    """Returns identity pubkeys of all currently active (voting) validators."""
    print("Fetching vote accounts...", file=sys.stderr)
    result = rpc("getVoteAccounts")
    pubkeys = {v["nodePubkey"] for v in result.get("current", [])}
    print(f"  {len(pubkeys)} active validators", file=sys.stderr)
    return pubkeys


def geo_lookup(ips: list[str], max_retries: int = MAX_RETRIES) -> dict[str, str]:
    """Batch-queries ip-api.com with retry. Returns {ip: country_code}."""
    ip_to_country: dict[str, str] = {}
    unique_ips = list(dict.fromkeys(ips))  # deduplicate, preserve order
    print(
        f"Looking up {len(unique_ips)} unique IPs in batches of {BATCH_SIZE}...",
        file=sys.stderr,
    )

    for i in range(0, len(unique_ips), BATCH_SIZE):
        batch = unique_ips[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(unique_ips) + BATCH_SIZE - 1) // BATCH_SIZE
        payload = [{"query": ip, "fields": "status,countryCode,query"} for ip in batch]

        for attempt in range(1, max_retries + 1):
            try:
                r = requests.post(IP_API_BATCH_URL, json=payload, timeout=30)
                r.raise_for_status()
                for entry in r.json():
                    if entry.get("status") == "success":
                        ip_to_country[entry["query"]] = entry["countryCode"]
                print(
                    f"  Batch {batch_num}/{total_batches} ({len(batch)} IPs) OK",
                    file=sys.stderr,
                )
                break
            except Exception as e:
                wait = 2**attempt * 5
                print(
                    f"  Batch {batch_num} attempt {attempt} failed: {e}. Retrying in {wait}s...",
                    file=sys.stderr,
                )
                time.sleep(wait)
        else:
            print(
                f"  Batch {batch_num}: giving up after {max_retries} attempts",
                file=sys.stderr,
            )

        if i + BATCH_SIZE < len(unique_ips):
            time.sleep(BATCH_SLEEP_SECONDS)

    return ip_to_country


def main() -> None:
    # 1. Fetch data from Solana
    pubkey_to_ip = fetch_validators()
    active_pubkeys = fetch_active_pubkeys()

    # Only process validators that are both active (voting) and have a public IP
    relevant = {pk: ip for pk, ip in pubkey_to_ip.items() if pk in active_pubkeys}
    print(
        f"\n{len(relevant)} active validators with public gossip IPs", file=sys.stderr
    )

    # 2. Geo-lookup all unique IPs
    unique_ips = list(dict.fromkeys(relevant.values()))
    ip_to_country = geo_lookup(unique_ips)

    # 3. Build output rows
    rows: list[tuple[str, str, str]] = []
    unknown_count = 0
    region_counts: dict[str, int] = {}

    for pubkey, ip in relevant.items():
        country = ip_to_country.get(ip, "")
        region = COUNTRY_TO_REGION.get(country, "UNKNOWN")
        if region == "UNKNOWN":
            unknown_count += 1
        region_counts[region] = region_counts.get(region, 0) + 1
        rows.append((pubkey, country, region))

    # 4. Write CSV
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w") as f:
        f.write("pubkey,country,region\n")
        for pubkey, country, region in sorted(rows):
            f.write(f"{pubkey},{country},{region}\n")

    # 5. Summary
    print(f"\nWrote {len(rows)} rows to {OUTPUT_PATH}", file=sys.stderr)
    print("Region distribution:", file=sys.stderr)
    for region, count in sorted(region_counts.items(), key=lambda x: -x[1]):
        print(f"  {region:12s} {count:4d}", file=sys.stderr)
    if unknown_count:
        print(
            f"\n  {unknown_count} validators could not be mapped (UNKNOWN)",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
