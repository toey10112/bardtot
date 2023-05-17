from flask import Flask
from threading import Thread
import schedule

from binance.client import Client
import pandas as pd
import requests
import time
import firebase_admin
from firebase_admin import credentials, db
import os
from dotenv import load_dotenv
from flask import request

app = Flask(__name__)
trading_active = True
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
cred = credentials.Certificate('firebase_credentials.json')
firebase_admin.initialize_app(cred, {
    "databaseURL": DATABASE_URL
})

symbol = "BTCUSDT"
signal_before = "exit"


@app.route('/start')
def start():
    global trading_active
    global signal_before
    trading_active = True
    signal_before = "exit"
    return 'Trading bot is running!'


@app.route('/stop')
def stop_strategy():
    global trading_active
    trading_active = False
    ref = db.reference('/')
    user = ref.child("strategy").child("MACD").get()
    for key, i in user.items():
        if key == 'dummy':
            pass
        elif isinstance(i, dict):
            api_key = i.get('api_key')
            api_secret = i.get('secret_key')
            if api_key is not None and api_secret is not None:
                client = Client(api_key, api_secret)
                exit_position(client)


    return 'Trading strategy stopped.'


@app.route('/stop_individual', methods=['POST'])
def stop_strategy_individual():
    uid = request.json.get('uid')
    if not uid:
        return "Please provide uid"
    ref = db.reference('/')
    user = ref.child("strategy").child("MACD").child(uid).get()
    api_key = user['api_key']
    api_secret = user['secret_key']
    client = Client(api_key, api_secret)
    exit_position(client)
    delete_data = ref.child("strategy").child("MACD").child(uid).delete()
    return "Individual strategy stopped"


def run_schedule():
    while trading_active:
        schedule.run_pending()
        time.sleep(1)


def get_position_side(position):
    position_amt = float(position['positionAmt'])
    if position_amt > 0:
        return "LONG"
    elif position_amt < 0:
        return "SHORT"
    else:
        return "NONE"


def open_buy_position(client):
    # get the current position on the symbol
    position = client.futures_position_information(symbol=symbol)[0]
    position_side = get_position_side(position)
    position_size = abs(float(position['positionAmt']))

    if position_side == 'LONG':
        print("Position already open.")
        return
    elif position_side == 'SHORT':
        # close the short position before opening a long position
        print("Position already open in short.")
        order = client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_BUY,
            type=Client.ORDER_TYPE_MARKET,
            quantity=position_size
        )
        print(f"Close short position order: {order}")
    # open the long position
    usdt_balance = float(client.futures_account_balance()[8]['balance'])
    usdt_price = float(client.futures_symbol_ticker(symbol=symbol)['price'])
    quantity = round(usdt_balance / usdt_price, 3)
    order = client.futures_create_order(
        symbol=symbol,
        side=Client.SIDE_BUY,
        type=Client.ORDER_TYPE_MARKET,
        quantity=quantity,
        leverage=1
    )
    print(f"Open long position order: {order}")


def open_sell_position(client):
    # get the current position on the symbol
    position = client.futures_position_information(symbol=symbol)[0]
    position_side = get_position_side(position)
    position_size = abs(float(position['positionAmt']))
    if position_side == 'SHORT':
        print("Position already open.")
        return
    elif position_side == 'LONG':
        # close the long position before opening a short position
        print("Position already open in long.")
        order = client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_SELL,
            type=Client.ORDER_TYPE_MARKET,
            quantity=position_size
        )
        print(f"Close long position order: {order}")
    # open the short position
    usdt_balance = float(client.futures_account_balance()[8]['balance'])
    usdt_price = float(client.futures_symbol_ticker(symbol=symbol)['price'])
    quantity = round(usdt_balance / usdt_price, 3)
    order = client.futures_create_order(
        symbol=symbol,
        side=Client.SIDE_SELL,
        type=Client.ORDER_TYPE_MARKET,
        quantity=quantity,
        leverage=1
    )
    print(f"Open short position order: {order}")


def exit_position(client):
    # get the current position on the symbol
    position = client.futures_position_information(symbol=symbol)[0]
    position_side = get_position_side(position)
    position_size = abs(float(position['positionAmt']))
    if position_size == "NONE":
        print("No open position found.")
        return
    # close the position
    if position_side == 'LONG':
        order = client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_SELL,
            type=Client.ORDER_TYPE_MARKET,
            quantity=position_size
        )
        print(f"Exit long position order: {order}")
    elif position_side == 'SHORT':
        order = client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_BUY,
            type=Client.ORDER_TYPE_MARKET,
            quantity=position_size
        )
        print(f"Exit short position order: {order}")


def macd(market_data):
    data = market_data.copy()
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time',
                                     'quote_asset_volume', 'num_trades', 'taker_buy_base_asset_volume',
                                     'taker_buy_quote_asset_volume', 'ignore'])
    # Convert timestamp to datetime format
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    # Calculate the 12-day and 26-day EMA
    ema_8 = df['close'].ewm(span=8, adjust=False).mean()
    ema_20 = df['close'].ewm(span=20, adjust=False).mean()
    # Calculate the MACD line and signal line
    macd_line = ema_8 - ema_20
    signal_line = macd_line.ewm(span=8, adjust=False).mean()
    # Calculate the MACD histogram
    macd_hist = macd_line - signal_line
    # Determine buy, sell or hold signal
    if macd_line.iloc[-1] > signal_line.iloc[-1] and macd_line.iloc[-2] <= signal_line.iloc[-2]:
        # bullish crossover, buy signal
        # open_buy_position()
        return "buy"
    elif macd_line.iloc[-1] < signal_line.iloc[-1] and macd_line.iloc[-2] >= signal_line.iloc[-2]:
        # bearish crossover, sell signal
        # open_sell_position()
        return "sell"

    else:
        if signal_before == 'buy':
            if macd_hist.iloc[-1] < macd_hist.iloc[-2] and macd_hist.iloc[-2] < macd_hist.iloc[-3]:
                # exit_position()
                return "exit"
            else:
                return signal_before
        if signal_before == 'sell':
            if macd_hist.iloc[-1] > macd_hist.iloc[-2] and macd_hist.iloc[-2] > macd_hist.iloc[-3]:
                # exit_position()
                return "exit"
            else:
                return signal_before


def trading_strategy():
    url = 'https://api.binance.com/api/v3/klines'
    params = {
        'symbol': 'BTCUSDT',
        'interval': '5m',
        'limit': 100
    }
    response = requests.get(url, params=params)
    graph_data = response.json()
    signal = macd(graph_data)
    print(signal)
    ref = db.reference('/')
    user = ref.child("strategy").child("MACD").get()

    if signal == 'exit':
        for key, i in user.items():
            if key == 'dummy':
                pass
            elif isinstance(i, dict):
                api_key = i.get('api_key')
                api_secret = i.get('secret_key')
                if api_key is not None and api_secret is not None:
                    client = Client(api_key, api_secret)
                    exit_position(client)



    elif signal == 'buy':
        for key, i in user.items():
            if key == 'dummy':
                pass
            elif isinstance(i, dict):
                api_key = i.get('api_key')
                api_secret = i.get('secret_key')
                if api_key is not None and api_secret is not None:
                    client = Client(api_key, api_secret)
                    open_buy_position(client)
    elif signal == 'sell':
        for key, i in user.items():
            if key == 'dummy':
                pass
            elif isinstance(i, dict):
                api_key = i.get('api_key')
                api_secret = i.get('secret_key')
                if api_key is not None and api_secret is not None:
                    client = Client(api_key, api_secret)
                    open_sell_position(client)


if __name__ == '__main__':
    # Schedule the trading_strategy function to run every 5 minutes
    schedule.every(5).minutes.do(trading_strategy)

    # Run the schedule in a separate thread
    t = Thread(target=run_schedule)
    t.start()

    # Start the Flask app
    app.run(host='0.0.0.0', port=5000)
