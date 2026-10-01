import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta
import ccxt

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bitget_grid_bot.log", encoding="utf-8")
    ]
)

class BitgetFuturesGridBot:
    """
    Bot Grid Futures pour Bitget BTC/USDT.
    Caractéristiques:
    - Symbole: BTC/USDT:USDT (USDT-M Futures)
    - Investissement: 10.63 USDT (marge initiale)
    - Levier: 25x
    - Durée de fonctionnement: 3 jours (72h)
    - Mode simulation (dry-run) ou réel (live)
    """

    def __init__(
        self,
        api_key: str = None,
        secret_key: str = None,
        passphrase: str = None,
        symbol: str = "BTC/USDT:USDT",
        investment_usdt: float = 10.63,
        leverage: int = 25,
        grid_levels: int = 10,
        lower_price: float = None,
        upper_price: float = None,
        grid_spread_pct: float = 0.04,  # +-4% par rapport au prix actuel si non spécifié
        duration_days: float = 3.0,
        dry_run: bool = True
    ):
        self.symbol = symbol
        self.investment_usdt = investment_usdt
        self.leverage = leverage
        self.grid_levels = grid_levels
        self.lower_price = lower_price
        self.upper_price = upper_price
        self.grid_spread_pct = grid_spread_pct
        self.duration_days = duration_days
        self.dry_run = dry_run

        self.api_key = api_key or os.getenv("BITGET_API_KEY", "")
        self.secret_key = secret_key or os.getenv("BITGET_SECRET_KEY", "")
        self.passphrase = passphrase or os.getenv("BITGET_PASSPHRASE", "")

        self.start_time = None
        self.end_time = None
        self.exchange = None
        self.grid_prices = []
        self.open_orders = {}  # Format: {price: {'id': id, 'side': 'buy'/'sell', 'amount': amount}}

    def initialize_exchange(self):
        """Initialise la connexion ccxt avec Bitget."""
        exchange_config = {
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'password': self.passphrase,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # USDT Futures
            }
        }
        self.exchange = ccxt.bitget(exchange_config)

        if not self.dry_run:
            if not (self.api_key and self.secret_key and self.passphrase):
                raise ValueError("Clés API Bitget manquantes (API key, Secret, Passphrase requis pour le mode Réel).")
            # Configurer le levier sur Bitget
            try:
                logging.info(f"Configuration du levier à {self.leverage}x sur Bitget pour {self.symbol}...")
                self.exchange.set_leverage(self.leverage, self.symbol)
            except Exception as e:
                logging.warning(f"Impossible d'ajuster automatiquement le levier via l'API: {e}. Vérifiez sur l'interface Bitget.")

    def fetch_current_price(self) -> float:
        """Récupère le prix actuel du marché pour BTC/USDT."""
        if self.exchange:
            try:
                ticker = self.exchange.fetch_ticker(self.symbol)
                return float(ticker['last'])
            except Exception as e:
                logging.error(f"Erreur lors de la récupération du prix: {e}")
        # Prix par défaut si pas d'échange connecté ou erreur
        return 65000.0

    def calculate_grid(self, current_price: float):
        """Calcule les niveaux de prix du grid et la taille des positions."""
        if self.lower_price is None or self.upper_price is None:
            self.lower_price = current_price * (1 - self.grid_spread_pct)
            self.upper_price = current_price * (1 + self.grid_spread_pct)

        step = (self.upper_price - self.lower_price) / (self.grid_levels - 1)
        self.grid_prices = [round(self.lower_price + i * step, 2) for i in range(self.grid_levels)]

        # Capital total notionnel avec levier 25x
        notional_capital = self.investment_usdt * self.leverage
        # Notional par grille
        notional_per_grid = notional_capital / self.grid_levels
        # Quantité BTC par grille
        amount_btc_per_grid = notional_per_grid / current_price

        logging.info("--- Configuration de la Grille ---")
        logging.info(f"Symbole: {self.symbol}")
        logging.info(f"Capital Réel (Marge): {self.investment_usdt} USDT")
        logging.info(f"Levier: {self.leverage}x (Valeur Notionnelle Totale: {notional_capital:.2f} USDT)")
        logging.info(f"Plage de Prix: [{self.lower_price:.2f} - {self.upper_price:.2f}] USDT")
        logging.info(f"Nombre de niveaux de grille: {self.grid_levels}")
        logging.info(f"Notionnel par niveau: {notional_per_grid:.2f} USDT (~{amount_btc_per_grid:.4f} BTC)")
        logging.info(f"Niveaux calculés: {self.grid_prices}")
        return self.grid_prices, amount_btc_per_grid

    def setup_initial_grid_orders(self, current_price: float, amount_per_grid: float):
        """Place la grille initiale d'ordres d'achat (Buy Limit) sous le prix et de vente (Sell Limit) au-dessus du prix."""
        logging.info("Placement initial des ordres du grid...")
        for price in self.grid_prices:
            if price < current_price:
                self.place_order(side="buy", price=price, amount=amount_per_grid)
            elif price > current_price:
                self.place_order(side="sell", price=price, amount=amount_per_grid)

    def place_order(self, side: str, price: float, amount: float):
        """Place un ordre limite (ou simule s'il s'agit du mode dry-run)."""
        if self.dry_run:
            order_id = f"sim_{side}_{price}_{int(time.time()*1000)}"
            logging.info(f"[SIMULATION] Ordre placé: {side.upper()} {amount:.4f} BTC à {price:.2f} USDT (ID: {order_id})")
            self.open_orders[price] = {
                'id': order_id,
                'side': side,
                'amount': amount,
                'status': 'open'
            }
            return order_id
        else:
            try:
                order = self.exchange.create_order(
                    symbol=self.symbol,
                    type='limit',
                    side=side,
                    amount=amount,
                    price=price
                )
                logging.info(f"[RÉEL] Ordre placé: {side.upper()} {amount:.4f} BTC à {price:.2f} USDT (ID: {order['id']})")
                self.open_orders[price] = {
                    'id': order['id'],
                    'side': side,
                    'amount': amount,
                    'status': 'open'
                }
                return order['id']
            except Exception as e:
                logging.error(f"Erreur lors du placement de l'ordre {side} à {price}: {e}")
                return None

    def cancel_all_open_orders(self):
        """Annule tous les ordres ouverts."""
        logging.info("Annulation de tous les ordres ouverts...")
        if self.dry_run:
            self.open_orders.clear()
            logging.info("[SIMULATION] Tous les ordres ont été annulés.")
        else:
            if self.exchange:
                try:
                    for price, order_info in list(self.open_orders.items()):
                        self.exchange.cancel_order(order_info['id'], self.symbol)
                        logging.info(f"[RÉEL] Ordre {order_info['id']} à {price} USDT annulé.")
                    self.open_orders.clear()
                except Exception as e:
                    logging.error(f"Erreur lors de l'annulation des ordres: {e}")

    def check_order_status(self, price: float, order_info: dict, current_price: float) -> bool:
        """Vérifie si un ordre à un niveau de prix donné a été exécuté."""
        if self.dry_run:
            side = order_info['side']
            if side == 'buy' and current_price <= price:
                return True
            elif side == 'sell' and current_price >= price:
                return True
            return False
        else:
            try:
                order = self.exchange.fetch_order(order_info['id'], self.symbol)
                return order['status'] == 'closed'
            except Exception as e:
                logging.error(f"Erreur lors de la vérification de l'ordre {order_info['id']}: {e}")
                return False

    def run(self, poll_interval_sec: int = 10):
        """Démarre le bot pour une durée spécifiée (3 jours)."""
        self.initialize_exchange()
        current_price = self.fetch_current_price()
        prices, amount_per_grid = self.calculate_grid(current_price)
        self.setup_initial_grid_orders(current_price, amount_per_grid)

        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(days=self.duration_days)

        logging.info(f"Début du Grid Trading à {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logging.info(f"Fin programmée dans {self.duration_days} jours à {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            while datetime.now() < self.end_time:
                current_price = self.fetch_current_price()
                logging.info(f"[PRIX BTC] {current_price:.2f} USDT | Ordres ouverts: {len(self.open_orders)}")

                # Vérifier les ordres remplis
                for price in list(self.open_orders.keys()):
                    order_info = self.open_orders[price]
                    side = order_info['side']
                    amount = order_info['amount']

                    if self.check_order_status(price, order_info, current_price):
                        logging.info(f"🎉 ORDRE DE {side.upper()} EXÉCUTÉ à {price:.2f} USDT!")
                        del self.open_orders[price]

                        step = (self.upper_price - self.lower_price) / (self.grid_levels - 1)
                        if side == 'buy':
                            higher_price = round(price + step, 2)
                            if higher_price <= self.upper_price:
                                self.place_order(side='sell', price=higher_price, amount=amount)
                        elif side == 'sell':
                            lower_price = round(price - step, 2)
                            if lower_price >= self.lower_price:
                                self.place_order(side='buy', price=lower_price, amount=amount)

                time.sleep(poll_interval_sec)

            logging.info("⏰ Durée de 3 jours atteinte. Annulation des ordres...")
            self.cancel_all_open_orders()
        except KeyboardInterrupt:
            logging.info("Interruption manuelle reçue. Arrêt du bot...")
            self.cancel_all_open_orders()

def main():
    parser = argparse.ArgumentParser(description="Bot Bitget Future Grid BTC/USDT 25x")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Mode simulation (activé par défaut)")
    parser.add_argument("--live", action="store_true", help="Activer le mode réel (Trading en direct)")
    parser.add_argument("--capital", type=float, default=10.63, help="Investissement USDT (défaut: 10.63)")
    parser.add_argument("--leverage", type=int, default=25, help="Levier (défaut: 25)")
    parser.add_argument("--days", type=float, default=3.0, help="Durée en jours (défaut: 3)")

    args = parser.parse_args()
    is_dry_run = not args.live

    bot = BitgetFuturesGridBot(
        investment_usdt=args.capital,
        leverage=args.leverage,
        duration_days=args.days,
        dry_run=is_dry_run
    )
    logging.info(f"Lancement du bot Bitget Future Grid (Mode: {'SIMULATION' if is_dry_run else 'RÉEL'})...")
    bot.run()

if __name__ == "__main__":
    main()
