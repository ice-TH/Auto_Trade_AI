"""
Playbook Compiler Module
Aggregates modular rules (playbook_core.md + playbooks/*.md) into a unified master playbook.md
Provides targeted rule retrieval per asset (get_asset_playbook) for lightweight AI context loading.
"""

import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict

MEMORY_DIR = Path(__file__).resolve().parent.parent.parent / "memory"
PLAYBOOK_DIR = MEMORY_DIR / "playbooks"
CORE_PLAYBOOK_FILE = MEMORY_DIR / "playbook_core.md"
MASTER_PLAYBOOK_FILE = MEMORY_DIR / "playbook.md"

SYMBOL_ASSET_MAP: Dict[str, str] = {
    "XAUUSD": "xauusd_gold.md",
    "XAUUSDM": "xauusd_gold.md",
    "GOLD": "xauusd_gold.md",
    "BTCUSD": "btc_crypto.md",
    "BTCUSDM": "btc_crypto.md",
    "BTC": "btc_crypto.md",
    "AAPL": "us_equities.md",
    "MSFT": "us_equities.md",
    "NVDA": "us_equities.md",
    "AMZN": "us_equities.md",
    "GOOGL": "us_equities.md",
    "META": "us_equities.md",
    "TSLA": "us_equities.md",
}

def compile_playbook(output_file: Optional[Path] = None) -> str:
    """
    Renders the unified master playbook.md from:
    1. memory/playbook_core.md (Global Safety & Risk Rules)
    2. memory/playbooks/*.md (Asset-specific modules)
    Automatically updates the Table of Contents and Last Compiled timestamp.
    """
    if output_file is None:
        output_file = MASTER_PLAYBOOK_FILE

    bkk_time = datetime.now(timezone.utc) + timedelta(hours=7)
    timestamp_str = bkk_time.strftime("%Y-%m-%d %H:%M:%S")

    sections = []

    # 1. Master Header
    header = f"""# Antigravity Active Trading Playbook (Master Unified View)
*Automated AI Knowledge Base - รวมศูนย์กฎความปลอดภัยกลางและคู่มือเทรดเฉพาะสินทรัพย์*

- **Last Compiled:** {timestamp_str} (BKK UTC+7)
- **Target Environment:** Exness MT5 (Local IPC)
- **Architecture:** Modular Playbook (Core Safety + Asset Extensions)

---

## 📑 สารบัญรวม (Table of Contents)
1. [Core Safety & Global Risk Rules (กฎความปลอดภัยกลางสากล)](#core-safety--risk-policy-กฎความปลอดภัยกลางสากล)
2. [XAU/USD (Gold) Strategy Playbook (คู่มือการเทรดทองคำ)](#xauusd-gold-strategy-playbook-คู่มือการเทรดทองคำ)
3. [BTC/USD (Bitcoin) Strategy Playbook (คู่มือการเทรดบิตคอยน์)](#btcusd-bitcoin-strategy-playbook-คู่มือการเทรดบิตคอยน์)
4. [US Equities Strategy Playbook (คู่มือการเทรดหุ้นสหรัฐฯ 7 ตัว)](#us-equities-strategy-playbook-คู่มือการเทรดหุ้นสหรัฐฯ-7-ตัว)

---
"""
    sections.append(header)

    # 2. Core Safety Rules
    if CORE_PLAYBOOK_FILE.exists():
        with open(CORE_PLAYBOOK_FILE, "r", encoding="utf-8") as f:
            sections.append(f.read().strip())
    else:
        sections.append("<!-- Warning: playbook_core.md not found -->")

    sections.append("\n\n---\n")

    # 3. Asset Modules in specific order
    asset_files = [
        ("xauusd_gold.md", "XAU/USD Gold Module"),
        ("btc_crypto.md", "BTC/USD Crypto Module"),
        ("us_equities.md", "US Equities Module")
    ]

    for filename, label in asset_files:
        asset_path = PLAYBOOK_DIR / filename
        if asset_path.exists():
            with open(asset_path, "r", encoding="utf-8") as f:
                sections.append(f.read().strip())
            sections.append("\n\n---\n")
        else:
            sections.append(f"<!-- Warning: {filename} ({label}) not found -->\n\n---\n")

    compiled_content = "\n".join(sections).strip() + "\n"

    # Write atomic output
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(compiled_content)
    except Exception as e:
        print(f"Warning: Failed to write compiled playbook to {output_file}: {e}")

    return compiled_content


def get_asset_playbook(symbol: str) -> str:
    """
    Returns only Core Rules + Asset Specific rules for targeted AI analysis.
    Prevents token bloat and cross-asset rule interference.
    """
    clean_sym = symbol.upper().replace("/", "").strip()
    target_filename = SYMBOL_ASSET_MAP.get(clean_sym)

    parts = []

    # Always include core safety rules
    if CORE_PLAYBOOK_FILE.exists():
        with open(CORE_PLAYBOOK_FILE, "r", encoding="utf-8") as f:
            parts.append(f.read().strip())

    if target_filename:
        asset_file = PLAYBOOK_DIR / target_filename
        if asset_file.exists():
            with open(asset_file, "r", encoding="utf-8") as f:
                parts.append(f.read().strip())

    return "\n\n---\n\n".join(parts) if parts else "No playbook rules found for this asset."


if __name__ == "__main__":
    content = compile_playbook()
    print(f"Successfully compiled playbook. Total length: {len(content)} characters.")
