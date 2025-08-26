from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_migrate import Migrate
from pycoingecko import CoinGeckoAPI
import random
import string
from datetime import datetime
import logging
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*", "supports_credentials": True}})
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:FkLEPOrXzVjKQMRdtbQnhiXWYfjpkUFk@centerbeam.proxy.rlwy.net:52075/railway'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)
cg = CoinGeckoAPI()

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('flask_cors').level = logging.DEBUG

@app.after_request
def after_request(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

words = [
    'apple', 'ball', 'cat', 'dog', 'egg', 'fish', 'goat', 'hat', 'ice', 'jam', 'kit', 'log',
    'man', 'net', 'oak', 'pig', 'quilt', 'rat', 'sun', 'top', 'up', 'van', 'win', 'xray',
    'yak', 'zip', 'ant', 'bee', 'cow', 'duck', 'ear', 'fox', 'gun', 'hen', 'ink', 'jug'
]

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wallet_name = db.Column(db.String(50), default='Main wallet')
    seed_phrase = db.Column(db.Text, unique=True, nullable=False)
    pin = db.Column(db.String(6), nullable=False)
    balances = db.Column(db.JSON, default=lambda: {
        'BTC': 0, 'ETH': 0, 'XLM': 0, 'UNI': 0, 'KOGE': 0, 'BR': 0
    })

class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.Text, nullable=False)
    asset = db.Column(db.String(10), nullable=True)
    amount = db.Column(db.Float, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

def generate_seed():
    return ' '.join(random.choice(words) for _ in range(12))

def generate_pin():
    return ''.join(random.choice(string.digits) for _ in range(6))

def log_action(user_id, action, asset=None, amount=None):
    log = Log(user_id=user_id, action=action, asset=asset, amount=amount)
    db.session.add(log)
    db.session.commit()

@app.route('/generate', methods=['POST', 'OPTIONS'])
def generate_wallet():
    if request.method == 'OPTIONS':
        logging.debug("Обробка OPTIONS-запиту для /generate")
        return '', 204
    try:
        logging.debug("Початок створення гаманця")
        seed = generate_seed()
        logging.debug(f"Seed згенеровано: {seed}")
        pin = generate_pin()
        logging.debug(f"PIN згенеровано: {pin}")
        user = User(seed_phrase=seed, pin=pin)
        logging.debug("Користувача створено")
        db.session.add(user)
        logging.debug("Користувача додано до сесії")
        db.session.commit()
        logging.debug("Коміт виконано")
        log_action(user.id, 'Wallet created')
        logging.debug(f"Гаманець створено: id={user.id}, seed={seed}")
        return jsonify({'success': True, 'id': user.id, 'seed': seed, 'pin': pin, 'wallet_name': user.wallet_name})
    except Exception as e:
        logging.error(f"Помилка в /generate: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        logging.debug("Обробка OPTIONS-запиту для /login")
        return '', 204
    try:
        data = request.json
        seed = data.get('seed')
        pin = data.get('pin')
        wallet_name = data.get('wallet_name', 'Main wallet')
        user = User.query.filter_by(seed_phrase=seed).first()
        if user and user.pin == pin:
            user.wallet_name = wallet_name
            db.session.commit()
            log_action(user.id, 'Logged in')
            logging.debug(f"Логін успішний: id={user.id}")
            return jsonify({'success': True, 'id': user.id, 'balances': user.balances, 'wallet_name': user.wallet_name})
        logging.warning(f"Невірна seed або PIN: seed={seed}")
        return jsonify({'success': False, 'message': 'Невірна seed або PIN'})
    except Exception as e:
        logging.error(f"Помилка в /login: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/get_balances', methods=['GET', 'OPTIONS'])
def get_balances():
    if request.method == 'OPTIONS':
        logging.debug("Обробка OPTIONS-запиту для /get_balances")
        return '', 204
    try:
        user_id = request.args.get('user_id')
        user = db.session.get(User, user_id)  # Updated to Session.get()
        if user:
            log_action(user.id, 'Viewed balances')
            prices = cg.get_price(ids=['bitcoin', 'ethereum', 'stellar', 'uniswap', 'koge', 'br'], vs_currencies='usd', include_24hr_change='true')
            logging.debug(f"Баланси отримано: user_id={user_id}")
            return jsonify({'success': True, 'balances': user.balances, 'prices': prices})
        logging.warning(f"Користувача не знайдено: user_id={user_id}")
        return jsonify({'success': False, 'message': 'Користувача не знайдено'})
    except Exception as e:
        logging.error(f"Помилка в /get_balances: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/get_coin_details', methods=['GET', 'OPTIONS'])
def get_coin_details():
    if request.method == 'OPTIONS':
        logging.debug("Обробка OPTIONS-запиту для /get_coin_details")
        return '', 204
    try:
        user_id = request.args.get('user_id')
        coin_id = request.args.get('coin_id')
        user = db.session.get(User, user_id)  # Updated to Session.get()
        if user:
            balance = user.balances.get(coin_id.upper(), 0)
            transactions = Log.query.filter_by(user_id=user_id, asset=coin_id.upper()).all()
            transaction_data = [{'amount': tx.amount, 'asset': tx.asset} for tx in transactions if tx.amount is not None]
            log_action(user.id, f'Viewed coin details for {coin_id}')
            logging.debug(f"Деталі монети отримано: user_id={user_id}, coin_id={coin_id}")
            return jsonify({'success': True, 'balance': balance, 'transactions': transaction_data})
        logging.warning(f"Користувача не знайдено: user_id={user_id}")
        return jsonify({'success': False, 'message': 'Користувача не знайдено'})
    except Exception as e:
        logging.error(f"Помилка в /get_coin_details: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/create_wallet', methods=['POST', 'OPTIONS'])
def admin_create_wallet():
    if request.method == 'OPTIONS':
        logging.debug("Обробка OPTIONS-запиту для /admin/create_wallet")
        return '', 204
    try:
        seed = generate_seed()
        pin = generate_pin()
        user = User(seed_phrase=seed, pin=pin)
        db.session.add(user)
        db.session.commit()
        log_action(user.id, 'Admin created wallet')
        logging.debug(f"Адмін створив гаманець: id={user.id}, seed={seed}")
        return jsonify({'success': True, 'id': user.id, 'seed': seed, 'pin': pin, 'wallet_name': user.wallet_name})
    except Exception as e:
        logging.error(f"Помилка в /admin/create_wallet: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/add_balance', methods=['POST', 'OPTIONS'])
def admin_add_balance():
    if request.method == 'OPTIONS':
        logging.debug("Обробка OPTIONS-запиту для /admin/add_balance")
        return '', 204
    try:
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
            log_action(user.id, f'Admin added {amount} to {asset}', asset=asset, amount=amount)
            logging.debug(f"Баланс додано: user_id={user.id}, asset={asset}, amount={amount}")
            return jsonify({'success': True})
        logging.warning(f"Користувача не знайдено: seed={seed}")
        return jsonify({'success': False, 'message': 'Користувача не знайдено'})
    except Exception as e:
        logging.error(f"Помилка в /admin/add_balance: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Загальна помилка: {str(e)}")
    return jsonify({'success': False, 'message': 'Внутрішня помилка сервера'}), 500

with app.app_context():
    try:
        db.create_all()
        logging.info("Таблиці створено або вже існують.")
    except Exception as e:
        logging.error(f"Помилка при створенні таблиць: {str(e)}")

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
