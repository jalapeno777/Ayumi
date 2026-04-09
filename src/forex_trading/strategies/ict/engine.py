from typing import List, Optional

from .confluence import ConfluenceEngine
from .fvg import FVGDetector
from .models import (
    ConfluenceSignal,
    FairValueGap,
    ICTMarketState,
    OrderBlock,
    TradeDirection,
)
from .order_block import OrderBlockDetector


class ICTEngine:
    def __init__(self):
        self._ob_detector = OrderBlockDetector()
        self._fvg_detector = FVGDetector()
        self._confluence_engine = ConfluenceEngine()

    def update_market_state(self, state: ICTMarketState) -> None:
        self._ob_detector.detect(state)
        self._fvg_detector.detect(state)

    def get_active_order_blocks(self, state: ICTMarketState) -> List[OrderBlock]:
        return state.active_order_blocks

    def get_active_fvgs(self, state: ICTMarketState) -> List[FairValueGap]:
        return state.active_fvgs

    def get_order_block(
        self, state: ICTMarketState, direction: TradeDirection
    ) -> Optional[OrderBlock]:
        return self._ob_detector.get_most_relevant(state, direction)

    def get_fvg(
        self, state: ICTMarketState, direction: TradeDirection, current_price: float
    ) -> Optional[FairValueGap]:
        return self._fvg_detector.get_nearest_unfilled(state, direction, current_price)

    def evaluate_confluence(self, state: ICTMarketState) -> Optional[ConfluenceSignal]:
        return self._confluence_engine.evaluate(state)

    def set_direction_bias(self, state: ICTMarketState, bias: TradeDirection) -> None:
        state.structure_bias = bias
