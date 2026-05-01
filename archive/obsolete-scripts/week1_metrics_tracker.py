#!/usr/bin/env python3
"""Week 1 Community Growth Sprint — Metrics Tracker

This script tracks key metrics for the Week 1 Community Growth Sprint.
Run daily to collect and report on growth metrics.
"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from crypto.services.repository import TradeRepository


def print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_metric(label: str, value: str, target: str = "") -> None:
    target_text = f" (Target: {target})" if target else ""
    print(f"  {label:<35} {value:>15}{target_text}")


def print_section(title: str) -> None:
    print(f"\n{title}")
    print(f"{'-' * 60}")


def calculate_day_of_week() -> int:
    """Calculate which day of the sprint (1-14)."""
    now = datetime.now(timezone.utc)
    sprint_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (now - sprint_start).days + 1


def main():
    repo = TradeRepository()
    day_of_week = calculate_day_of_week()

    print_header(f"WEEK 1 COMMUNITY GROWTH SPRINT — DAY {day_of_week} METRICS")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # Acquisition Metrics
    print_section("ACQUISITION METRICS")

    # Get total users count
    with repo._connect() as conn:
        total_users = conn.execute("SELECT COUNT(*) as count FROM users").fetchone()[
            "count"
        ]
        free_users = conn.execute(
            "SELECT COUNT(*) as count FROM users WHERE subscription_tier = 'free'"
        ).fetchone()["count"]
        pro_users = conn.execute(
            "SELECT COUNT(*) as count FROM users WHERE subscription_tier = 'pro'"
        ).fetchone()["count"]
        vip_users = conn.execute(
            "SELECT COUNT(*) as count FROM users WHERE subscription_tier = 'vip'"
        ).fetchone()["count"]

    print_metric("Total Users", str(total_users), "25+")
    print_metric("Free Tier Users", str(free_users), "")
    print_metric("Pro Tier Users", str(pro_users), "5+")
    print_metric("VIP Tier Users", str(vip_users), "1+")

    # New signups today
    with repo._connect() as conn:
        today = datetime.now(timezone.utc).date()
        today_signups = conn.execute(
            "SELECT COUNT(*) as count FROM users WHERE DATE(created_at) = ?",
            (str(today),),
        ).fetchone()["count"]

    print_metric("New Signups Today", str(today_signups), "3-5")

    # Referral Metrics
    print_section("REFERRAL METRICS")

    with repo._connect() as conn:
        total_referral_codes = conn.execute(
            "SELECT COUNT(*) as count FROM referral_codes WHERE is_active = TRUE"
        ).fetchone()["count"]
        total_clicks = conn.execute(
            "SELECT COUNT(*) as count FROM referral_clicks"
        ).fetchone()["count"]
        total_conversions = conn.execute(
            "SELECT COUNT(*) as count FROM referral_conversions WHERE conversion_type = 'signup'"
        ).fetchone()["count"]

        # Get conversion rate
        conversion_rate = (
            (total_conversions / total_clicks * 100) if total_clicks > 0 else 0.0
        )

    print_metric("Active Referral Codes", str(total_referral_codes), "10+")
    print_metric("Total Referral Clicks", str(total_clicks), "50+")
    print_metric("Referral Conversions", str(total_conversions), "10+")
    print_metric("Conversion Rate", f"{conversion_rate:.1f}%", "10%+")

    # Payout Metrics
    print_section("COMMISSION METRICS")

    with repo._connect() as conn:
        pending_payouts = conn.execute(
            "SELECT COUNT(*) as count FROM referral_payouts WHERE status = 'pending'"
        ).fetchone()["count"]

        paid_payouts = conn.execute(
            "SELECT COUNT(*) as count FROM referral_payouts WHERE status = 'paid'"
        ).fetchone()["count"]

        total_pending_amount = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM referral_payouts WHERE status = 'pending'"
        ).fetchone()["total"]

    print_metric("Pending Payouts", str(pending_payouts), "")
    print_metric("Paid Payouts", str(paid_payouts), "")
    print_metric("Pending Commissions", f"${total_pending_amount:.2f}", "$50+")

    # Provider Metrics
    print_section("PROVIDER/LEADERBOARD METRICS")

    leaderboard = repo.get_leaderboard(limit=10)
    if leaderboard:
        top_provider = leaderboard[0]
        print_metric("Total Providers", str(len(leaderboard)), "5+")
        print_metric("Top Provider", top_provider["provider_name"], "")
        print_metric("Top Provider Followers", str(top_provider["followers_count"]), "")
        print_metric("Top Provider Win Rate", f"{top_provider['win_rate']}%", "")
        print_metric("Top Provider Profit", f"${top_provider['total_profit']:.2f}", "")

    # Signal Metrics
    print_section("SIGNAL METRICS")

    signals = repo.get_recent_signals(limit=100)
    signals_this_week = [
        s
        for s in signals
        if datetime.fromisoformat(s["signal_time"])
        >= datetime.now(timezone.utc) - timedelta(days=7)
    ]

    print_metric("Total Signals", str(len(signals)), "")
    print_metric("Signals This Week", str(len(signals_this_week)), "")

    if signals_this_week:
        symbol_counts = {}
        for signal in signals_this_week:
            symbol = signal["symbol"]
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

        top_symbol = max(symbol_counts, key=symbol_counts.get)
        print_metric("Top Symbol", top_symbol, "")

    # Progress Assessment
    print_section("WEEK 1 PROGRESS ASSESSMENT")

    # Calculate progress vs targets
    signup_progress = min((total_users / 25) * 100, 100)
    conversion_progress = min((total_conversions / 10) * 100, 100)
    referral_code_progress = min((total_referral_codes / 10) * 100, 100)
    commission_progress = min((total_pending_amount / 50) * 100, 100)

    overall_progress = (
        signup_progress
        + conversion_progress
        + referral_code_progress
        + commission_progress
    ) / 4

    print_metric("Signup Target Progress", f"{signup_progress:.0f}%", "25 users")
    print_metric(
        "Conversion Target Progress", f"{conversion_progress:.0f}%", "10 conversions"
    )
    print_metric(
        "Referral Code Progress", f"{referral_code_progress:.0f}%", "10 active codes"
    )
    print_metric(
        "Commission Target Progress", f"{commission_progress:.0f}%", "$50 pending"
    )
    print_metric("OVERALL WEEK 1 PROGRESS", f"{overall_progress:.0f}%", "")

    # Daily Targets
    print_section(f"DAY {day_of_week} TARGETS")

    day_target_map = {
        1: "Post referral announcement to Discord",
        2: "Create Telegram bot and channel",
        3: "Post initial 3 Telegram messages",
        4: "Configure email onboarding sequence",
        5: "Set up Discord-Telegram bridge",
        6: "Configure metrics dashboard",
        7: "Day 3 checkpoint: 10+ referrers, 25+ Telegram members",
        8: "Continue Telegram content posting",
        9: "Monitor engagement metrics",
        10: "Optimize content based on data",
        11: "Continue Telegram content posting",
        12: "Analyze top-performing content",
        13: "Prepare Week 2 optimization plan",
        14: "Week 1 final report and metrics",
    }

    if day_of_week in day_target_map:
        print(f"  Priority: {day_target_map[day_of_week]}")

    # Recommendations
    print_section("RECOMMENDATIONS")

    recommendations = []

    if signup_progress < 50:
        recommendations.append(
            "• Boost user acquisition: Share referral link across all channels"
        )

    if conversion_rate < 5.0:
        recommendations.append(
            "• Improve referral conversion: Test CTA placement, messaging"
        )

    if len(leaderboard) < 5:
        recommendations.append(
            "• Recruit more providers: Reach out to top traders in community"
        )

    if pending_payouts > 20:
        recommendations.append(
            "• Process pending payouts: Ensure timely commission payments"
        )

    if not recommendations:
        recommendations.append("• Week 1 on track: Continue current execution strategy")

    for rec in recommendations:
        print(f"  {rec}")

    print(f"\n{'=' * 60}\n")


if __name__ == "__main__":
    main()
