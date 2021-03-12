import asyncio
import itertools

from typing import List

from ready_trader_one import BaseAutoTrader, Instrument, Lifespan, Side

VOLUME_LIMIT = 200
LOT_SIZE = 10
POSITION_LIMIT = 1000
TICK_SIZE_IN_CENTS = 100


class AutoTrader(BaseAutoTrader):
    """
    When it starts this auto-trader places ten-lot bid and ask orders at the
    current best-bid and best-ask prices respectively. Thereafter, if it has
    a long position (it has bought more lots than it has sold) it reduces its
    bid and ask prices. Conversely, if it has a short position (it has sold
    more lots than it has bought) then it increases its bid and ask prices.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, team_name: str, secret: str):
        """Initialise a new instance of the AutoTrader class."""
        super().__init__(loop, team_name, secret)
        self.order_ids = itertools.count(1)
        self.bids = [0,0]
        self.bids_vol = [0,0]
        self.asks = [0,0]
        self.asks_vol = [0,0]
        self.ask_price = self.bid_price = self.position = 0

    def on_error_message(self, client_order_id: int, error_message: bytes) -> None:
        """Called when the exchange detects an error.

        If the error pertains to a particular order, then the client_order_id
        will identify that order, otherwise the client_order_id will be zero.
        """
        self.logger.warning("error with order %d: %s", client_order_id, error_message.decode())
        if client_order_id != 0:
            self.on_order_status_message(client_order_id, 0, 0, 0)

    def on_order_book_update_message(self, instrument: int, sequence_number: int, ask_prices: List[int],
                                     ask_volumes: List[int], bid_prices: List[int], bid_volumes: List[int]) -> None:
        """Called periodically to report the status of an order book.

        The sequence number can be used to detect missed or out-of-order
        messages. The five best available ask (i.e. sell) and bid (i.e. buy)
        prices are reported along with the volume available at each of those
        price levels.
        """
        if instrument == Instrument.FUTURE:
            new_bid_price = bid_prices[0] if bid_prices[0] != 0 else 0
            new_ask_price = ask_prices[0] if ask_prices[0] != 0 else 0

            if self.bids[0] != 0 and new_bid_price not in (self.bid_price, 0):
                if new_bid_price == self.bid_price - TICK_SIZE_IN_CENTS:
                    self.send_cancel_order(self.bids[0])
                    self.bids[0] = self.bids[1]
                    self.bids_vol[0] = self.bids_vol[1]
                    self.bids[1] = 0
                    self.bids_vol[1] = 0
                    self.bid_price = new_bid_price
                elif new_bid_price == self.bid_price + TICK_SIZE_IN_CENTS:
                    self.send_cancel_order(self.bids[1])
                    self.bids[1] = self.bids[0]
                    self.bids_vol[1] = self.bids_vol[0]
                    self.bids[0] = 0
                    self.bids_vol[0] = 0

                else:
                    self.send_cancel_order(self.bids[0])
                    self.send_cancel_order(self.bids[1])

            if self.asks[0] != 0 and new_ask_price not in (self.ask_price, 0):
                if new_ask_price == self.ask_price + TICK_SIZE_IN_CENTS:
                    self.send_cancel_order(self.asks[0])
                    self.asks[0] = self.asks[1]
                    self.asks_vol[0] = self.asks_vol[1]
                    self.asks[1] = 0
                    self.asks_vol[1] = 0
                    self.ask_price = new_ask_price
                elif new_ask_price == self.ask_price - TICK_SIZE_IN_CENTS:
                    self.send_cancel_order(self.asks[1])
                    self.asks[1] = self.asks[0]
                    self.asks_vol[1] = self.asks_vol[0]
                    self.asks[0] = 0
                    self.asks_vol[0] = 0
                else:
                    self.send_cancel_order(self.asks[0])
                    self.send_cancel_order(self.asks[1])

            new_bid_volume = LOT_SIZE if self.position > 0 else min(max(LOT_SIZE, abs(self.position)),
                                                                    int(self.get_remaining_volume()/2) - LOT_SIZE)
            new_ask_volume = LOT_SIZE if self.position < 0 else min(max(LOT_SIZE, abs(self.position)),
                                                                    int(self.get_remaining_volume()/2) - LOT_SIZE)

            if self.bids[0] == 0 and new_bid_price != 0 \
                    and self.position + new_bid_volume + sum(self.bids_vol) < POSITION_LIMIT:
                self.bids[0] = next(self.order_ids)
                self.bid_price = new_bid_price
                self.send_insert_order(self.bids[0], Side.BUY, new_bid_price, new_bid_volume, Lifespan.GOOD_FOR_DAY)
                self.bids_vol[0] = new_bid_volume

            if self.bids[1] == 0 and new_bid_price != 0 \
                    and self.position + new_bid_volume + sum(self.bids_vol) < POSITION_LIMIT:
                self.bids[1] = next(self.order_ids)
                self.send_insert_order(self.bids[1], Side.BUY, new_bid_price - TICK_SIZE_IN_CENTS, new_bid_volume,
                                       Lifespan.GOOD_FOR_DAY)
                self.bids_vol[0] = new_bid_volume

            if self.asks[0] == 0 and new_ask_price != 0 \
                    and self.position - new_ask_volume - sum(self.asks_vol) > -POSITION_LIMIT:
                self.asks[0] = next(self.order_ids)
                self.ask_price = new_ask_price
                self.send_insert_order(self.asks[0], Side.SELL, new_ask_price, new_ask_volume, Lifespan.GOOD_FOR_DAY)
                self.asks_vol[0] = new_ask_volume

            if self.asks[1] == 0 and new_ask_price != 0 \
                    and self.position - new_ask_volume - sum(self.asks_vol) > -POSITION_LIMIT:
                self.asks[1] = next(self.order_ids)
                self.send_insert_order(self.asks[1], Side.SELL, new_ask_price + TICK_SIZE_IN_CENTS, new_ask_volume,
                                       Lifespan.GOOD_FOR_DAY)
                self.asks_vol[1] = new_ask_volume

    def get_remaining_volume(self):
        volume = 0
        for i in range(len(self.bids_vol)):
            volume += self.bids_vol[i]
            volume += self.asks_vol[i]
        return VOLUME_LIMIT - volume

    def on_order_filled_message(self, client_order_id: int, price: int, volume: int) -> None:
        """Called when when of your orders is filled, partially or fully.

        The price is the price at which the order was (partially) filled,
        which may be better than the order's limit price. The volume is
        the number of lots filled at that price.
        """
        if client_order_id in self.bids:
            self.position += volume
            for i in range(2):
                if client_order_id == self.bids[i]:
                    self.bids_vol[i] -= volume
                    break
        elif client_order_id in self.asks:
            self.position -= volume
            for i in range(2):
                if client_order_id == self.asks[i]:
                    self.asks_vol[i] -= volume
                    break

    def on_order_status_message(self, client_order_id: int, fill_volume: int, remaining_volume: int,
                                fees: int) -> None:
        """Called when the status of one of your orders changes.

        The fill_volume is the number of lots already traded, remaining_volume
        is the number of lots yet to be traded and fees is the total fees for
        this order. Remember that you pay fees for being a market taker, but
        you receive fees for being a market maker, so fees can be negative.

        If an order is cancelled its remaining volume will be zero.
        """
        if remaining_volume == 0:
            if client_order_id in self.bids:
                if client_order_id == self.bids[0]:
                    self.bids[0] = 0
                    self.bids_vol[0] = 0
                else:
                    self.bids[1] = 0
                    self.bids_vol[1] = 0
            elif client_order_id in self.asks:
                if client_order_id == self.asks[0]:
                    self.asks[0] = 0
                    self.asks_vol[0] = 0
                else:
                    self.asks[1] = 0
                    self.asks_vol[1] = 0
