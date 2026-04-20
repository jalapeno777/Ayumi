from dataclasses import dataclass

from core.pip import PipCalculator


@dataclass(frozen=True)
class SpreadModel:
    spread_pips: float
    slippage_pips: float = 0.0

    def adjust_entry_long(self, price: float) -> float:
        return price + self._total_spread_price(price)

    def adjust_entry_short(self, price: float) -> float:
        return price - self._total_spread_price(price)

    def _total_spread_price(self, price: float) -> float:
        return PipCalculator.pips_to_price(price, self.spread_pips + self.slippage_pips)
