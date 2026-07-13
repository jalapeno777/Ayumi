# Backtesting Strategy Runbook

## FTMO Guard

The `FTMOGuard` class (`backtest/ftmo_guard.py`) models FTMO Challenge
loss rules for backtesting and paper trading. It enforces the two
critical constraints that cause most challenge failures:

### Challenge Types

| Type | Daily Loss | Max Loss | Floor Behavior |
|------|-----------|----------|----------------|
| 1-Step | 3% of initial | 10% trailing | Floor rises with highest midnight balance, never decreases |
| 2-Step | 5% of initial | 10% static | Floor is always 90% of initial balance |

### Usage in Backtesting

```python
from backtest.ftmo_guard import FTMOGuard

# Create guard for 1-Step challenge
guard = FTMOGuard(
    initial_balance=10_000,
    track_id="FTMO-001",
    challenge_type="1-step",
)

# At each CET midnight, record the balance
guard.record_midnight_balance(current_balance)

# Before opening a position, check if entry is allowed.
# planned_risk_dollars is the loss at the stop-loss.
if not guard.check_entry(planned_risk_dollars, balance=current_balance, open_pnl=open_pnl):
    # Skip new entries — would breach daily or total loss limit
    continue

# Check remaining headroom
remaining = guard.remaining_total_loss(current_balance)
daily_remaining = guard.remaining_daily_loss(current_balance, open_pnl)
```

### Integration with Portfolio Blend

The `inventory_strategies_on_data` function accepts an optional
`ftmo_guard` parameter. When provided, it skips opening new positions
when the account balance is below the guard's floor.

### Walk-Through: Day 15 Breach

The trailing floor is the #1 killer of FTMO challenges:

```
Day  1: balance $10,000 → floor $9,000  (headroom $1,000)
Day  5: balance $10,800 → floor $9,720  (headroom $1,080)
Day  9: balance $11,200 → floor $10,080 (headroom $1,120)
Day 12: balance $11,000 → floor $10,080 (headroom $920, floor unchanged)
Day 15: balance $10,050 → BREACH       ($10,050 < $10,080)
```

Even though the account is still profitable (+0.5%), the trailing floor
has risen to $10,080 and the balance dropped below it. Without the
guard, a strategy would keep trading unaware that the challenge is
already failed.
