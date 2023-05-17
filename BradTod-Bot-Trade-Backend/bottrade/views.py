# Create your views here.
import requests
import json
from firebase_admin.exceptions import FirebaseError
from datetime import datetime

from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from firebase_admin import auth, db, get_app
from binance.client import Client

from django.conf import settings


def login(request):
    if request.method == "POST":
        email = request.POST['email']
        password = request.POST['password']

        firebase_api_key = settings.FIREBASE_API_KEY
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={firebase_api_key}"

        data = {
            "email": email,
            "password": password,
            "returnSecureToken": True
        }

        response = requests.post(url, json=data)

        if response.status_code == 200:
            json_response = response.json()

            # Store the ID token in the session
            request.session['id_token'] = json_response['idToken']
            print(f"ID token stored in session: {request.session['id_token']}")  # Add this line
            return redirect('home')
        else:
            messages.error(request, "Invalid email or password")
            return redirect('login')
    else:
        if 'id_token' in request.session:
            id_token = request.session.get('id_token')
            try:
                decoded_token = auth.verify_id_token(id_token)
                return redirect('home')
            except FirebaseError:
                # Invalid ID token, proceed to the login page
                return redirect('login')
            except Exception as e:
                messages.error(request, f"Unexpected error: {e}")
                return redirect('login')

        return render(request, 'login.html')


def stop_strategy(request):
    if 'id_token' in request.session:
        id_token = request.session.get('id_token')
        try:
            decoded_token = auth.verify_id_token(id_token)
            uid = decoded_token['uid']
            if request.method == "POST":
                strategy = request.POST['strategy']
                data = {"uid": uid}
                if strategy == "MACD":
                    response = requests.post("http://localhost:5000/stop_individual", json=data)
                elif strategy == "EMA":
                    response = requests.post("http://localhost:5001/stop_individual", json=data)
                elif strategy == "BOLLINGERBANDS":
                    response = requests.post("http://localhost:5002/stop_individual", json=data)
                elif strategy == "KELTNER":
                    response = requests.post("http://localhost:5003/stop_individual", json=data)
                if response.status_code == 200:
                    print("POST request successful")
                    return redirect('home')
                else:
                    print("POST request failed:", response.status_code)
                    return redirect('home')

            else:
                return redirect('home')

        except Exception as e:
            messages.error(request, f"Unexpected error: {e}")
            request.session.flush()
            return redirect('login')
        except FirebaseError as e:
            messages.error(request, f"Firebase error: {e}")
            request.session.flush()
            return redirect('login')
    else:
        return redirect('home')


def home(request):
    if 'id_token' in request.session:
        id_token = request.session.get('id_token')
        try:
            decoded_token = auth.verify_id_token(id_token)
            email = decoded_token['email']
            uid = decoded_token['uid']
            ref = db.reference('/')
            key = ref.child('key').child(uid).get()
            if key is None:
                messages.error(request, "Secret key is missing for this user")
                return redirect('add_key')
            else:
                api_key = key['api_key']
                secret_key = key['secret_key']
                client = Client(api_key, secret_key)

                positions = client.futures_position_information()
                open_positions = [position for position in positions if float(position['positionAmt']) != 0]
                for position in open_positions:
                    position['updateTime'] = datetime.fromtimestamp(int(position['updateTime']) // 1000).strftime(
                        '%Y-%m-%d %H:%M:%S')

                futures_balance = client.futures_account_balance()
                usdt_balance = 0
                ref = db.reference('/')

                for balance in futures_balance:
                    if balance['asset'] == 'USDT':
                        usdt_balance = float(balance['balance'])
                order = ref.child('strategy').get()
                strategy = next((s for s, value in order.items() if uid in value), None)
                print(strategy)

                context = {'user_email': email,
                           'usdt_balance': usdt_balance,
                           'open_positions': open_positions,
                           'strategy_used': strategy}
                return render(request, 'home.html', context)





        except FirebaseError as e:
            messages.error(request, f"Firebase error: {e}")
            request.session.flush()
            return redirect('login')
        except Exception as e:

            messages.error(request, f"Unexpected error: {e}")
            request.session.flush()
            return redirect('login')
    else:
        return redirect('login')


def logout(request):
    # if 'id_token' in request.session:
    print(request.session.get('id_token'))
    # del request.session['id_token']
    request.session.flush()

    print(request.session.get('id_token'))

    return redirect('login')


def register(request):
    if 'id_token' not in request.session:
        if request.method == 'POST':
            email = request.POST['email']
            password = request.POST['password']
            try:
                user = auth.create_user(email=email, password=password)
                messages.success(request, 'User registered successfully')
                return redirect('login')
            except Exception as e:
                messages.error(request, str(e))
        return render(request, 'register.html')
    else:
        return redirect('home')


def add_key(request):
    if 'id_token' in request.session:
        id_token = request.session['id_token']

        try:
            decoded_token = auth.verify_id_token(id_token)
            uid = decoded_token['uid']
        except:
            messages.error(request, "idToken error")
            request.session.flush()
            return redirect('login')
    else:
        return redirect('login')
    if request.method == "POST":
        api_key = request.POST['api_key']
        secret_key = request.POST['secret_key']

        # Add key data to the Firebase Realtime Database using the Firebase Admin SDK
        ref = db.reference('/')
        data = {
            "api_key": api_key,
            "secret_key": secret_key
        }
        ref.child('key').child(uid).set(data)

        return redirect('home')
    else:
        return render(request, 'add_key.html')


def make_order(request):
    if 'id_token' in request.session:
        id_token = request.session['id_token']

        try:
            decoded_token = auth.verify_id_token(id_token)
            uid = decoded_token['uid']
            ref = db.reference('/')
            key = ref.child('key').child(uid).get()
            if key is None:
                messages.error(request, "Secret key is missing for this user")
                return redirect('add_key')
        except:
            messages.error(request, "idToken error")
            request.session.flush()
            return redirect('login')
    else:
        return redirect('login')
    if request.method == 'POST':

        # Get the form data
        strategy = request.POST.get('strategy')
        # amount = request.POST.get('amount')
        coin = request.POST.get('coin')

        ref = db.reference('/')
        key = ref.child('key').child(uid).get()
        api_key = key['api_key']
        secret_key = key['secret_key']

        data = {
            "api_key": api_key,
            "secret_key": secret_key,
            "amount": 1,
            "coin": coin,

        }
        ref.child("strategy").child(strategy).child(uid).set(data)

        # Redirect to a success or confirmation page, or back to the form with a success message
        return redirect('home')
    else:
        return render(request, 'make_order.html')
