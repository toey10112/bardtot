import pandas as pd
from binance.client import Client
import requests
import time
import firebase_admin
from firebase_admin import credentials, db
import os
from dotenv import load_dotenv
from flask import Flask, request
from threading import Thread
import schedule

app = Flask(__name__)
trading_active = True
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
cred = credentials.Certificate('firebase_credentials.json')
firebase_admin.initialize_app(cred, {
    "databaseURL": DATABASE_URL
})

symbol = "BTCUSDT"


def ema(graph_data):
    data = graph_data.copy()
    df = pd.DataFrame(data,
                      columns=['date', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume',
                               'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume',
                               'ignore'])
    df['date'] = pd.to_datetime(df['date'], unit='ms')
    df.set_index('date', inplace=True)

    # Calculate EMA
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()

    if df['EMA21'][-1] > df['EMA50'][-1] and df['EMA21'][-2] <= df['EMA50'][-2]:
        # open_buy_position()
        return "LONG"
    elif df['EMA21'][-1] < df['EMA50'][-1] and df['EMA21'][-2] >= df['EMA50'][-2]:
        # open_sell_position()
        return "SHORT"
    else:
        return "NONE"


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


def run_schedule():
    while trading_active:
        schedule.run_pending()
        time.sleep(1)


@app.route('/stop')
def stop_strategy():
    global trading_active
    trading_active = False
    ref = db.reference('/')
    user = ref.child("strategy").child("EMA").get()
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


@app.route('/start')
def start():
    global trading_active
    trading_active = True
    return 'Trading bot is running!'


@app.route('/stop_individual', methods=['POST'])
def stop_strategy_individual():
    uid = request.json.get('uid')
    if not uid:
        return "Please provide uid"
    ref = db.reference('/')
    user = ref.child("strategy").child("EMA").child(uid).get()
    api_key = user['api_key']
    api_secret = user['secret_key']
    client = Client(api_key, api_secret)
    exit_position(client)
    delete_data = ref.child("strategy").child("EMA").child(uid).delete()
    return "Individual strategy stopped"


def trading_strategy():
    url = 'https://api.binance.com/api/v3/klines'
    params = {
        'symbol': 'BTCUSDT',
        'interval': '1h',
        'limit': 100
    }
    response = requests.get(url, params=params)
    graph_data = response.json()
    signal = ema(graph_data)
    ref = db.reference('/')
    user = ref.child("strategy").child("EMA").get()
    print(signal)
    if signal == "LONG":
        for key, i in user.items():
            if key == 'dummy':
                pass
            elif isinstance(i, dict):
                api_key = i.get('api_key')
                api_secret = i.get('secret_key')
                if api_key is not None and api_secret is not None:
                    client = Client(api_key, api_secret)
                    open_buy_position(client)
    elif signal == "SHORT":
        for key, i in user.items():
            if key == 'dummy':
                pass
            elif isinstance(i, dict):
                api_key = i.get('api_key')
                api_secret = i.get('secret_key')
                if api_key is not None and api_secret is not None:
                    client = Client(api_key, api_secret)
                    open_sell_position(client)



if __name__ == "__main__":
    schedule.every(1).hours.do(trading_strategy)
    t = Thread(target=run_schedule)
    t.start()

    # Start the Flask app
    app.run(host='0.0.0.0', port=5001)
