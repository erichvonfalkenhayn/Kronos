import unittest
from datetime import datetime, timedelta
from bitget_futures_grid_bot import BitgetFuturesGridBot

class TestBitgetFuturesGridBot(unittest.TestCase):

    def test_default_parameters(self):
        bot = BitgetFuturesGridBot()
        self.assertEqual(bot.investment_usdt, 10.63)
        self.assertEqual(bot.leverage, 25)
        self.assertEqual(bot.duration_days, 3.0)
        self.assertEqual(bot.symbol, "BTC/USDT:USDT")
        self.assertTrue(bot.dry_run)

    def test_grid_calculation(self):
        bot = BitgetFuturesGridBot(
            investment_usdt=10.63,
            leverage=25,
            grid_levels=5,
            lower_price=60000.0,
            upper_price=70000.0
        )
        current_price = 65000.0
        prices, amount_per_grid = bot.calculate_grid(current_price)

        self.assertEqual(len(prices), 5)
        self.assertEqual(prices[0], 60000.0)
        self.assertEqual(prices[-1], 70000.0)
        self.assertEqual(prices[2], 65000.0)

        # Capital total notionnel = 10.63 * 25 = 265.75 USDT
        # Notionnel par niveau = 265.75 / 5 = 53.15 USDT
        # Quantité BTC = 53.15 / 65000 = 0.00081769...
        expected_notional = 10.63 * 25
        expected_notional_per_grid = expected_notional / 5
        expected_amount = expected_notional_per_grid / current_price

        self.assertAlmostEqual(amount_per_grid, expected_amount, places=6)

    def test_order_placement_dry_run(self):
        bot = BitgetFuturesGridBot(dry_run=True)
        order_id = bot.place_order(side="buy", price=62000.0, amount=0.001)
        self.assertIsNotNone(order_id)
        self.assertTrue(order_id.startswith("sim_buy_62000.0_"))
        self.assertIn(62000.0, bot.open_orders)
        self.assertEqual(bot.open_orders[62000.0]['side'], 'buy')

    def test_duration_timer(self):
        bot = BitgetFuturesGridBot(duration_days=3.0)
        start_time = datetime.now()
        end_time = start_time + timedelta(days=bot.duration_days)
        time_diff = end_time - start_time
        self.assertEqual(time_diff.total_seconds(), 3 * 24 * 3600)

if __name__ == "__main__":
    unittest.main()
