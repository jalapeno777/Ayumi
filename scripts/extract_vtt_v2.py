#!/usr/bin/env python3
"""Extract content from VTT files and create formatted markdown batches."""

import re  # noqa: I001
import os
from datetime import datetime
from typing import List, Dict, Tuple


def parse_vtt_full(vtt_path: str) -> List[Dict]:
    """Parse a VTT file and extract all content with timestamps."""
    with open(vtt_path, "r", encoding="utf-8") as f:
        content = f.read()

    entries = []
    lines = content.split("\n")
    i = 0
    while i < len(lines) and "WEBVTT" not in lines[i]:
        i += 1
    i += 1

    current_text = []
    current_start = None

    while i < len(lines):
        line = lines[i].strip()

        if "-->" in line:
            timestamp_match = re.match(r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})", line)
            if timestamp_match:
                if current_start and current_text:
                    entries.append({"start": current_start, "text": " ".join(current_text)})
                current_start = timestamp_match.group(1)
                current_text = []
        elif line and not line.isdigit():
            current_text.append(line)
        elif not line and current_text:
            entries.append({"start": current_start, "text": " ".join(current_text)})
            current_text = []
        i += 1

    if current_start and current_text:
        entries.append({"start": current_start, "text": " ".join(current_text)})

    return entries


def get_session_type(filename: str) -> str:
    """Determine session type from filename."""
    fname_lower = filename.lower()
    if "asia" in fname_lower or "janet" in fname_lower:
        return "Asia Session (Live Trading with Janet)"
    elif "uk" in fname_lower or "cajun" in fname_lower:
        return "UK Session (Live Trading with Cajun)"
    elif "us" in fname_lower or "annii" in fname_lower:
        return "US Session (Live Trading with Annii)"
    elif "cabin" in fname_lower:
        return "Cabin Crew Catch-up"
    return "Live Trading"


def get_relevance(filename: str) -> str:
    """Determine relevance/priority from filename."""
    fname_lower = filename.lower()
    if "annii" in fname_lower:
        return "HIGH - Real money trades being executed"
    elif "cabin" in fname_lower:
        return "LOW - Cabin crew catch-up (2022), lower relevance"
    elif "janet" in fname_lower or "cajun" in fname_lower:
        return "MEDIUM-HIGH - Live trading session"
    return "MEDIUM"


def create_batch_markdown_v2(files: List[str], source_dir: str, output_dir: str, batch_num: int) -> Tuple[str, str]:
    """Create a formatted markdown batch from multiple VTT files."""

    all_entries = []
    file_info = []

    for fname in files:
        fpath = os.path.join(source_dir, fname)
        entries = parse_vtt_full(fpath)
        all_entries.extend(entries)

        stat = os.stat(fpath)
        file_info.append(
            {
                "filename": fname,
                "session": get_session_type(fname),
                "relevance": get_relevance(fname),
                "duration": f"{len(entries)} segments",
                "size_kb": stat.st_size // 1024,
            }
        )

    full_text = " ".join([e["text"] for e in all_entries])

    md_lines = []
    md_lines.append(f"# Recording Batch: Live_Trading_batch_{batch_num:03d}")
    md_lines.append("")
    md_lines.append("**Source Files:**")
    for fi in file_info:
        md_lines.append(f"- `{fi['filename']}`")
        md_lines.append(f"  - Session: {fi['session']}")
        md_lines.append(f"  - Relevance: {fi['relevance']}")
        md_lines.append(f"  - Duration: {fi['duration']}")
    md_lines.append("")
    md_lines.append("**Batch Focus:** Real-time trade execution, entry timing, stop placement, trade management")
    md_lines.append(f"**Total Segments:** {len(all_entries)}")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

    # Extract ICT/SMC concepts
    md_lines.append("## Concepts Extracted")
    md_lines.append("")

    concepts = extract_smc_concepts(full_text, all_entries)
    for concept in concepts:
        md_lines.append(f"### {concept['title']}")
        md_lines.append(f"{concept['description']}")
        if concept.get("signals"):
            md_lines.append("")
            md_lines.append("**Signals Discussed:**")
            for signal in concept["signals"]:
                md_lines.append(f"- {signal}")
        if concept.get("application"):
            md_lines.append("")
            md_lines.append(f"**Application:** {concept['application']}")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    # Market analysis discussed
    markets = []
    if "bitcoin" in full_text.lower() or "btc" in full_text.lower():
        markets.append("Bitcoin")
    if "eth" in full_text.lower():
        markets.append("Ethereum")
    if "xrp" in full_text.lower():
        markets.append("XRP")

    if markets:
        md_lines.append("## Markets Analyzed")
        md_lines.append("")
        for market in markets:
            md_lines.append(f"- {market}")
        md_lines.append("")

    # Timeframe analysis
    timeframes = []
    tf_map = {
        "daily": "Daily",
        "four-hour": "4H",
        "4h": "4H",
        "one hour": "1H",
        "1h": "1H",
        "1 hour": "1H",
        "fifteen minute": "15M",
        "15 minute": "15M",
        "15m": "15M",
        "weekly": "Weekly",
    }
    for phrase, tf in tf_map.items():
        if phrase in full_text.lower() and tf not in timeframes:
            timeframes.append(tf)
    timeframes.reverse()  # Show biggest first

    if timeframes:
        md_lines.append("## Timeframes Analyzed")
        md_lines.append("")
        md_lines.append(f"Primary: {', '.join(timeframes[:3])}")
        md_lines.append("")

    # Key observations
    observations = extract_observations(all_entries)
    if observations:
        md_lines.append("## Key Observations")
        md_lines.append("")
        for obs in observations:
            md_lines.append(f"- {obs}")
        md_lines.append("")

    md_lines.append("---")
    md_lines.append("")
    md_lines.append(
        f"*Extracted: {datetime.now().strftime('%Y-%m-%d')} | {len(files)} files | {len(all_entries)} segments*"
    )

    content = "\n".join(md_lines)
    output_path = os.path.join(output_dir, f"Live_Trading_batch_{batch_num:03d}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path, content


def extract_smc_concepts(text: str, entries: List[Dict]) -> List[Dict]:
    """Extract ICT/SMC-specific concepts from transcript."""
    concepts = []
    text_lower = text.lower()

    # Multi-Timeframe Analysis
    if any(
        x in text_lower
        for x in [
            "multi timeframe",
            "multi-timeframe",
            "daily",
            "four-hour",
            "4h",
            "1h",
            "15 minute",
        ]
    ):
        concepts.append(
            {
                "title": "Multi-Timeframe Analysis (MTFA)",
                "description": "Analysis conducted across multiple timeframes to confirm trade setups and direction bias.",  # noqa: E501
                "signals": [
                    "Weekly establishes primary trend and 50 EMA location",
                    "Daily confirms structural levels (1, 2, 3 counts)",
                    "4H identifies entry zones and intraday structure",
                    "1H/15M provides precise entry timing",
                ],
                "application": "Start with weekly for direction, daily for level confirmation, lower timeframes for entry",  # noqa: E501
            }
        )

    # Open Interest
    if any(
        x in text_lower
        for x in [
            "open interest",
            "oi increase",
            "oi decrease",
            "longs at risk",
            "shorts at risk",
        ]
    ):
        oi_signals = []
        if "oi increase" in text_lower or "open interest increase" in text_lower:
            oi_signals.append("OI increase = new positions opening (potential trap or continuation)")
        if "longs at risk" in text_lower:
            oi_signals.append("Longs at risk = potential for short-side liquidity sweep")
        if "shorts at risk" in text_lower:
            oi_signals.append("Shorts at risk = potential for long-side liquidity sweep")
        if "round-trip" in text_lower:
            oi_signals.append("Round-tripping OI = smart money closing positions")

        concepts.append(
            {
                "title": "Open Interest (OI) Analysis",
                "description": "Tracking open interest changes to identify institutional activity and trapped traders.",
                "signals": oi_signals if oi_signals else ["OI tracking for institutional move confirmation"],
                "application": "Use OI data to confirm direction and identify potential trap scenarios",
            }
        )

    # Liquidity & Sweeps
    if any(
        x in text_lower
        for x in [
            "liquidity",
            "sweep",
            "stop hunt",
            "stops above",
            "stops below",
            "liquidity pool",
        ]
    ):
        concepts.append(
            {
                "title": "Liquidity & Stop Hunts",
                "description": "Identifying liquidity pools and understanding stop hunt mechanics.",
                "signals": [
                    "Major liquidity below key levels = potential downside target",
                    "Major liquidity above = potential upside sweep",
                    "Stops being taken = smart money activity",
                    "High OI + price near liquidity = potential reversal zone",
                ],
                "application": "Map liquidity clusters before entries; trades set up where stops are likely to be taken",  # noqa: E501
            }
        )

    # Level Counting
    if any(
        x in text_lower
        for x in [
            "level one",
            "level two",
            "level three",
            "drop one",
            "drop two",
            "rise one",
            "rise two",
        ]
    ):
        concepts.append(
            {
                "title": "Level Counting (1-2-3 Structure)",
                "description": "Structured approach to counting market moves and identifying potential reversals.",
                "signals": [
                    "Level 1 + Level 2 = Continue trend direction",
                    "Level 3 (extension) = Expect reversal, reset pattern, or consolidation",
                    "Invalidation only at peak formations (not during moves)",
                    "W/Bottom = bullish reversal at level completion",
                    "M/Top = bearish reversal at level completion",
                ],
                "application": "Count levels to anticipate when a move may be complete and expect reversal patterns",
            }
        )

    # Entry Types
    if any(x in text_lower for x in ["bcr", "vcr", "aoi", "aggressive entry", "conservative entry"]):
        concepts.append(
            {
                "title": "Entry Methodologies",
                "description": "Different entry confirmation techniques discussed in the session.",
                "signals": [
                    "BCR (Break of Candle close) = Conservative entry after level break confirmed",
                    "VCR (Vector Candle crossing EMA) = Indicator-based timing entry",
                    "AOI (Area of Interest) = Zone reference for entry planning",
                    "Aggressive entry = Entry before full confirmation",
                    "Conservative entry = Wait for pullback or confirmation",
                ],
                "application": "Choose entry type based on market structure clarity and personal risk tolerance",
            }
        )

    # EMA & Moving Averages
    if any(x in text_lower for x in ["50 ema", "200 ema", "ema crossing", "above the 50", "below the 50"]):
        concepts.append(
            {
                "title": "EMA Utilization",
                "description": "Using exponential moving averages for trend direction and entries.",
                "signals": [
                    "Price above 50 EMA = bullish bias",
                    "Price below 50 EMA = bearish bias",
                    "50 EMA crossing = potential trend change",
                    "200 EMA = longer-term dynamic support/resistance",
                ],
                "application": "Use 50 EMA as primary trend filter; entries at EMA tests with confirmation",
            }
        )

    # Pattern Recognition
    patterns = []
    if any(x in text_lower for x in ["peak formation", "top formation"]):
        patterns.append("Peak formation = potential bearish reversal")
    if any(x in text_lower for x in ["w pattern", "w-bottom", "bottom formation"]):
        patterns.append("W pattern = bullish reversal structure")
    if any(x in text_lower for x in ["m pattern", "m-top", "top formation"]):
        patterns.append("M pattern = bearish reversal structure")
    if any(x in text_lower for x in ["half batman", "batman pattern"]):
        patterns.append("Half Batman = tight consolidation, clean continuation")
    if any(x in text_lower for x in ["trapping volume", "trapping volume formation", "svc"]):
        patterns.append("Trapping Volume Formation = stop hunt pattern before reversal")

    if patterns:
        concepts.append(
            {
                "title": "Price Action Patterns",
                "description": "Recognition of reversal and continuation patterns.",
                "signals": patterns,
                "application": "Look for patterns at key levels for high-probability trade entries",
            }
        )

    # Session-specific
    sessions = []
    if any(x in text_lower for x in ["us session", "8:30", "new york"]):
        sessions.append("US Session: High volatility at 8:30 AM ET (NFP, CPI, etc.)")
    if any(x in text_lower for x in ["asia session", "asian session", "tokyo"]):
        sessions.append("Asia Session: Typically lower volatility, range-bound behavior")
    if any(x in text_lower for x in ["uk session", "london"]):
        sessions.append("UK Session: Medium volatility, overlap with US")

    if sessions:
        concepts.append(
            {
                "title": "Session Context",
                "description": "Understanding how different trading sessions affect market behavior.",
                "signals": sessions,
                "application": "Adjust expectations and strategies based on active session",
            }
        )

    return concepts


def extract_observations(entries: List[Dict]) -> List[str]:
    """Extract notable observations from entries."""
    observations = []

    keywords = [
        "risk reward",
        "high probability",
        "clean setup",
        "tight stop",
        "massive",
        "happiest of days",
        "perfect",
        "beautiful",
    ]

    for entry in entries:
        text = entry["text"]
        if any(kw in text.lower() for kw in keywords):
            if 20 < len(text) < 200:
                observations.append(text)

    return observations[:8]  # Limit to 8 best observations


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4:
        print("Usage: extract_vtt_v2.py <source_dir> <output_dir> <batch_num> [files...]")
        sys.exit(1)

    source_dir = sys.argv[1]
    output_dir = sys.argv[2]
    batch_num = int(sys.argv[3])
    files = sys.argv[4:] if len(sys.argv) > 4 else []

    if not files:
        print("No files specified")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)
    path, content = create_batch_markdown_v2(files, source_dir, output_dir, batch_num)
    print(f"Created: {path}")
