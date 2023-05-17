import numpy as np
from binance.client import Client
import requests
import time
from flask import Flask
from threading import Thread
import schedule
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


def bb(graph_data):
    # input
    data = graph_data[-34:].copy()
    close_prices = [float(entry[4]) for entry in data]
    mult = 2.0
    dev = np.std(close_prices)
    dev2 = dev * 2
    basis = np.mean(close_prices)

    upper1 = basis + dev
    lower1 = basis - dev
    upper2 = basis + dev2
    lower2 = basis - dev2

    last_close = float(data[-1][4])
    # Define entry and exit conditions
    long_condition = last_close > upper1.iloc[-1]
    short_condition = last_close < lower1.iloc[-1]

    exit_long_condition = short_condition
    exit_short_condition = long_condition

    # Execute strategy orders
    if long_condition:
        print("Buy signal")
    elif short_condition:
        print("Sell signal")
    if exit_long_condition:
        print("Close long position")
    elif exit_short_condition:
        print("Close short position")

    middle_band = np.mean(close_prices)
    upper_band = middle_band + dev2
    lower_band = middle_band - dev2
    last_close = float(data[-1][4])
    if last_close > upper_band:
        # open_buy_position()
        return "buy"
    if last_close < lower_band:
        # open_sell_position()
        return "sell"


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


def trading_strategy():
    while True:
        url = 'https://api.binance.com/api/v3/klines'
        params = {
            'symbol': 'BTCUSDT',
            'interval': '1d',
            'limit': 100
        }
        response = requests.get(url, params=params)
        graph_data = response.json()
        signal = bb(graph_data)
        print(signal)
        ref = db.reference('/')
        user = ref.child("strategy").child("BOLLINGERBANDS").get()
        if signal == 'buy':
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


def run_schedule():
    while trading_active:
        schedule.run_pending()
        time.sleep(1)


@app.route('/start')
def start():
    global trading_active
    trading_active = True
    return 'Trading bot is running!'


@app.route('/stop')
def stop_strategy():
    global trading_active
    trading_active = False
    ref = db.reference('/')
    user = ref.child("strategy").child("BOLLINGERBANDS").get()
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
    user = ref.child("strategy").child("BOLLINGERBANDS").child(uid).get()
    api_key = user['api_key']
    api_secret = user['secret_key']
    client = Client(api_key, api_secret)
    exit_position(client)
    delete_data = ref.child("strategy").child("BOLLINGERBANDS").child(uid).delete()
    return "Individual strategy stopped"


if __name__ == '__main__':
    # Schedule the trading_strategy function to run every 5 minutes
    schedule.every(1).days.do(trading_strategy)

    # Run the schedule in a separate thread
    t = Thread(target=run_schedule)
    t.start()

    # Start the Flask app
    app.run(host='0.0.0.0', port=5002)
