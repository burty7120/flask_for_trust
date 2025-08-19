from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from pycoingecko import CoinGeckoAPI
import random
import string
from datetime import datetime
import logging

app = Flask(__name__)
# Enable CORS for all routes and origins
CORS(app, resources={r"/*": {"origins": "*", "supports_credentials": True}})
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:FkLEPOrXzVjKQMRdtbQnhiXWYfjpkUFk@centerbeam.proxy.rlwy.net:52075/railway'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
cg = CoinGeckoAPI()

# Enable CORS logging for debugging
logging.getLogger('flask_cors').level = logging.DEBUG

@app.after_request
def after_request(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

# ... rest of your models and functions remain unchanged ...

@app.route('/generate', methods=['POST', 'OPTIONS'])
def generate_wallet():
    if request.method == 'OPTIONS':
        return '', 204
    seed = generate_seed()
    pin = generate_pin()
    user = User(seed_phrase=seed, pin=pin)
    db.session.add(user)
    db.session.commit()
    log_action(user.id, 'Wallet created')
    return jsonify({'success': True, 'id': user.id, 'seed': seed, 'pin': pin, 'wallet_name': user.wallet_name})

@app.route('/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.json
    seed = data.get('seed')
    pin = data.get('pin')
    wallet_name = data.get('wallet_name', 'Main wallet')
    user = User.query.filter_by(seed_phrase=seed).first()
    if user and user.pin == pin:
        user.wallet_name = wallet_name
        db.session.commit()
        log_action(user.id, 'Logged in')
        return jsonify({'success': True, 'id': user.id, 'balances': user.balances, 'wallet_name': user.wallet_name})
    return jsonify({'success': False})

@app.route('/get_balances', methods=['GET', 'OPTIONS'])
def get_balances():
    if request.method == 'OPTIONS':
        return '', 204
    user_id = request.args.get('user_id')
    user = User.query.get(user_id)
    if user:
        log_action(user.id, 'Viewed balances')
        prices = cg.get_price(ids=['bitcoin', 'ethereum', 'stellar', 'uniswap', 'koge', 'br'], vs_currencies='usd', include_24hr_change='true')
        return jsonify({'success': True, 'balances': user.balances, 'prices': prices})
    return jsonify({'success': False})

@app.route('/admin/create_wallet', methods=['POST', 'OPTIONS'])
def admin_create_wallet():
    if request.method == 'OPTIONS':
        return '', 204
    seed = generate_seed()
    pin = generate_pin()
    user = User(seed_phrase=seed, pin=pin)
    db.session.add(user)
    db.session.commit()
    log_action(user.id, 'Admin created wallet')
    return jsonify({'success': True, 'id': user.id, 'seed': seed, 'pin': pin, 'wallet_name': user.wallet_name})

@app.route('/admin/add_balance', methods=['POST', 'OPTIONS'])
def admin_add_balance():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.json
    seed = data.get('seed')
    asset = data.get('asset')
    amount = float(data.get('amount', 0))
    user = User.query.filter_by(seed_phrase=seed).first()
    if user:
        if asset not in user.balances:
            user.balances[asset] = 0
        user.balances[asset] += amount
        db.session.commit()
        log_action(user.id, f'Admin added {amount} to {asset}')
        return jsonify({'success': True})
    return jsonify({'success': False})

with app.app_context():
    try:
        db.create_all()
        print("Таблиці створено або вже існують.")
    except Exception as e:
        print(f"Помилка при створенні таблиць: {e}")

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
