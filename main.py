import pandas as pd
import numpy as np
import yfinance as yf
import alpaca_trade_api as tradeapi
import logging
from datetime import datetime, timedelta
import time
from dotenv import load_dotenv
import os

# Load API credentials from .env file
load_dotenv()
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
BASE_URL = os.getenv('BASE_URL')

# Configure logging to track trades and errors
logging.basicConfig(
    filename='trading_log.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Set up Alpaca API for trading
api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')

# Trading strategy settings
SYMBOL = 'TSLA'  # Stock we're trading
SHORT_MA = 20    # Short-term moving average period
LONG_MA = 50     # Long-term moving average period
POSITION_SIZE = 0.1  # Max 10% of account per trade

# Risk management settings
STOP_LOSS_PCT = 0.05  # Exit if price drops 5% from buy

def fetch_data(symbol, start_date, end_date):
    # Pull historical stock data from yfinance
    logging.info(f"Fetching data for {symbol} from {start_date} to {end_date}")
    data = yf.download(symbol, start=start_date, end=end_date, interval='1d')
    return data

def calculate_signals(data):
    # Compute moving averages and generate buy/sell signals
    data['Short_MA'] = data['Close'].rolling(window=SHORT_MA).mean()
    data['Long_MA'] = data['Close'].rolling(window=LONG_MA).mean()
    
    # Set up columns for signals and positions
    data['Signal'] = 0
    data['Position'] = 0
    
    # Loop through data to find crossovers
    for i in range(1, len(data)):
        # Buy when short MA crosses above long MA
        if (data['Short_MA'].iloc[i] > data['Long_MA'].iloc[i]) and (data['Short_MA'].iloc[i-1] <= data['Long_MA'].iloc[i-1]):
            data.iloc[i, data.columns.get_loc('Signal')] = 1
        # Sell when short MA crosses below long MA
        elif (data['Short_MA'].iloc[i] < data['Long_MA'].iloc[i]) and (data['Short_MA'].iloc[i-1] >= data['Long_MA'].iloc[i-1]):
            data.iloc[i, data.columns.get_loc('Signal')] = -1
    
    # Track position: 1 if holding, 0 if not
    data['Position'] = data['Signal'].replace(-1, 0).ffill()
    return data

def backtest(data):
    # Run a backtest to see how the strategy performs
    data['Returns'] = data['Close'].pct_change()
    data['Strategy_Returns'] = data['Position'].shift(1) * data['Returns']
    total_return = (1 + data['Strategy_Returns']).cumprod().iloc[-1] - 1
    logging.info(f"Backtest Total Return: {total_return * 100:.2f}%")
    print(f"Backtest Total Return: {total_return * 100:.2f}%")
    return total_return

def is_market_open():
    # Check if the stock market is open
    clock = api.get_clock()
    return clock.is_open

def get_position_size(account_value):
    # Figure out how many shares to buy based on account size
    return int((account_value * POSITION_SIZE) / api.get_latest_bar(SYMBOL).close)

def live_trade():
    # Start live trading with Alpaca
    logging.info("Starting live trading...")
    position = 0  # Track if we're holding (1) or not (0)
    buy_price = 0  # Keep track of the price we bought at for stop-loss
    
    while True:
        try:
            if not is_market_open():
                logging.info("Market is closed. Waiting for market to open...")
                time.sleep(3600)  # Check again in an hour
                continue

            # Grab the last 60 days of data to calculate MAs
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
            data = fetch_data(SYMBOL, start_date, end_date)
            data = calculate_signals(data)

            # Look at the most recent signal and price
            latest_signal = data['Signal'].iloc[-1]
            latest_price = data['Close'].iloc[-1]

            # Check account balance
            account = api.get_account()
            equity = float(account.equity)

            # Stop-loss: sell if price drops too much
            if position == 1 and latest_price <= buy_price * (1 - STOP_LOSS_PCT):
                logging.info(f"Stop-loss triggered at {latest_price}. Selling {SYMBOL}.")
                api.submit_order(
                    symbol=SYMBOL,
                    qty=position,
                    side='sell',
                    type='market',
                    time_in_force='gtc'
                )
                position = 0
                continue

            # Execute trades based on signals
            if latest_signal == 1 and position == 0:
                qty = get_position_size(equity)
                if qty > 0:
                    api.submit_order(
                        symbol=SYMBOL,
                        qty=qty,
                        side='buy',
                        type='market',
                        time_in_force='gtc'
                    )
                    position = qty
                    buy_price = latest_price
                    logging.info(f"Bought {qty} shares of {SYMBOL} at {latest_price}")
            elif latest_signal == -1 and position > 0:
                api.submit_order(
                    symbol=SYMBOL,
                    qty=position,
                    side='sell',
                    type='market',
                    time_in_force='gtc'
                )
                position = 0
                logging.info(f"Sold {position} shares of {SYMBOL} at {latest_price}")

            time.sleep(60)  # Wait a minute before checking again

        except Exception as e:
            logging.error(f"Error in live trading: {str(e)}")
            time.sleep(60)

def main():
    # First, backtest the strategy with historical data
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    data = fetch_data(SYMBOL, start_date, end_date)
    data = calculate_signals(data)
    backtest(data)

    # Uncomment to start live trading
    # live_trade()

if __name__ == "__main__":
    main()