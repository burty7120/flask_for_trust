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

# Configure CORS to allow all origins and methods
CORS(app, resources={r"/*": {"origins": "*", "supports_credentials": True, "methods": ["GET", "POST", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]}})

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:FkLEPOrXzVjKQMRdtbQnhiXWYfjpkUFk@centerbeam.proxy.rlwy.net:52075/railway'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'max_overflow': 20,
    'pool_timeout': 30,
    'pool_pre_ping': True
}

# Initialize database and migration
db = SQLAlchemy(app)
migrate = Migrate(app, db)
cg = CoinGeckoAPI()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Seed phrase word list
words = [
    'apple', 'ball', 'cat', 'dog', 'egg', 'fish', 'goat', 'hat', 'ice', 'jam', 'kit', 'log',
    'man', 'net', 'oak', 'pig', 'quilt', 'rat', 'sun', 'top', 'up', 'van', 'win', 'xray',
    'yak', 'zip', 'ant', 'bee', 'cow', 'duck', 'ear', 'fox', 'gun', 'hen', 'ink', 'jug'
]

# Database models
class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    wallet_name = db.Column(db.String(50), default='Main wallet')
    seed_phrase = db.Column(db.Text, unique=True, nullable=False, index=True)
    pin = db.Column(db.String(6), nullable=False)
    balances = db.Column(db.JSON, default=lambda: {
        'BTC': 0.0, 'ETH': 0.0, 'XLM': 0.0, 'UNI': 0.0, 'KOGE': 0.0, 'BR': 0.0
    })

class Log(db.Model):
    __tablename__ = 'log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    action = db.Column(db.Text, nullable=False)
    asset = db.Column(db.String(10), nullable=True)
    amount = db.Column(db.Float, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

# Utility functions
def generate_seed():
    return ' '.join(random.choice(words) for _ in range(12))

def generate_pin():
    return ''.join(random.choice(string.digits) for _ in range(6))

def log_action(user_id, action, asset=None, amount=None):
    try:
        log = Log(user_id=user_id, action=action, asset=asset, amount=amount)
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to log action: {str(e)}")
        db.session.rollback()

# CORS headers for all responses
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

# Routes
@app.route('/generate', methods=['POST', 'OPTIONS'])
def generate_wallet():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        data = request.get_json()
        pin = data.get('pin')
        if not pin or len(pin) != 6 or not pin.isdigit():
            return jsonify({'success': False, 'message': 'PIN must be 6 digits'}), 400

        seed = generate_seed()
        user = User(seed_phrase=seed, pin=pin, wallet_name='Main wallet')
        db.session.add(user)
        db.session.commit()
        log_action(user.id, 'Wallet created')
        logger.info(f"Wallet created: id={user.id}, seed={seed}")
        return jsonify({
            'success': True,
            'id': user.id,
            'seed': seed,
            'pin': pin,
            'wallet_name': user.wallet_name
        })
    except Exception as e:
        logger.error(f"Error in /generate: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        data = request.get_json()
        seed = data.get('seed')
        pin = data.get('pin')
        wallet_name = data.get('wallet_name', 'Main wallet')
        if not seed or not pin:
            return jsonify({'success': False, 'message': 'Seed and PIN are required'}), 400

        user = User.query.filter_by(seed_phrase=seed).first()
        if user and user.pin == pin:
            user.wallet_name = wallet_name
            db.session.commit()
            log_action(user.id, 'Logged in')
            logger.info(f"Login successful: id={user.id}")
            return jsonify({
                'success': True,
                'id': user.id,
                'balances': user.balances,
                'wallet_name': user.wallet_name
            })
        logger.warning(f"Invalid seed or PIN: seed={seed}")
        return jsonify({'success': False, 'message': 'Invalid seed or PIN'}), 401
    except Exception as e:
        logger.error(f"Error in /login: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/get_balances', methods=['GET', 'OPTIONS'])
def get_balances():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'User ID is required'}), 400

        user = db.session.get(User, user_id)
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'success': False, 'message': 'User not found'}), 404

        prices = cg.get_price(
            ids=['bitcoin', 'ethereum', 'stellar', 'uniswap', 'koge', 'billionaire'],
            vs_currencies='usd',
            include_24hr_change=True
        )
        log_action(user.id, 'Viewed balances')
        logger.info(f"Balances retrieved: user_id={user_id}")
        return jsonify({
            'success': True,
            'balances': user.balances,
            'prices': prices
        })
    except Exception as e:
        logger.error(f"Error in /get_balances: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/get_wallets', methods=['GET', 'OPTIONS'])
def get_wallets():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'User ID is required'}), 400

        user = db.session.get(User, user_id)
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'success': False, 'message': 'User not found'}), 404

        wallets = [{'id': user.id, 'name': user.wallet_name}]
        prices = cg.get_price(
            ids=['bitcoin', 'ethereum', 'stellar', 'uniswap', 'koge', 'billionaire'],
            vs_currencies='usd',
            include_24hr_change=True
        )
        log_action(user.id, 'Viewed wallets')
        logger.info(f"Wallets retrieved: user_id={user_id}")
        return jsonify({
            'success': True,
            'wallets': wallets,
            'balances': user.balances,
            'prices': prices
        })
    except Exception as e:
        logger.error(f"Error in /get_wallets: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/get_coin_details', methods=['GET', 'OPTIONS'])
def get_coin_details():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        user_id = request.args.get('user_id')
        coin_id = request.args.get('coin_id')
        if not user_id or not coin_id:
            return jsonify({'success': False, 'message': 'User ID and Coin ID are required'}), 400

        user = db.session.get(User, user_id)
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'success': False, 'message': 'User not found'}), 404

        balance = user.balances.get(coin_id.upper(), 0.0)
        transactions = Log.query.filter_by(user_id=user_id, asset=coin_id.upper()).all()
        transaction_data = [
            {'amount': tx.amount, 'asset': tx.asset, 'action': tx.action, 'timestamp': tx.timestamp.isoformat()}
            for tx in transactions if tx.amount is not None
        ]
        log_action(user.id, f'Viewed coin details for {coin_id}')
        logger.info(f"Coin details retrieved: user_id={user_id}, coin_id={coin_id}")
        return jsonify({
            'success': True,
            'balance': balance,
            'transactions': transaction_data
        })
    except Exception as e:
        logger.error(f"Error in /get_coin_details: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/get_transactions', methods=['GET', 'OPTIONS'])
def get_transactions():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'User ID is required'}), 400

        user = db.session.get(User, user_id)
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'success': False, 'message': 'User not found'}), 404

        transactions = Log.query.filter_by(user_id=user_id).order_by(Log.timestamp.desc()).all()
        transaction_data = [
            {'amount': tx.amount, 'asset': tx.asset, 'action': tx.action, 'timestamp': tx.timestamp.isoformat()}
            for tx in transactions if tx.amount is not None
        ]
        log_action(user.id, 'Viewed transactions')
        logger.info(f"Transactions retrieved: user_id={user_id}")
        return jsonify({
            'success': True,
            'transactions': transaction_data
        })
    except Exception as e:
        logger.error(f"Error in /get_transactions: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/create_wallet', methods=['POST', 'OPTIONS'])
def admin_create_wallet():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        seed = generate_seed()
        pin = generate_pin()
        user = User(seed_phrase=seed, pin=pin, wallet_name='Main wallet')
        db.session.add(user)
        db.session.commit()
        log_action(user.id, 'Admin created wallet')
        logger.info(f"Admin created wallet: id={user.id}, seed={seed}")
        return jsonify({
            'success': True,
            'id': user.id,
            'seed': seed,
            'pin': pin,
            'wallet_name': user.wallet_name
        })
    except Exception as e:
        logger.error(f"Error in /admin/create_wallet: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/add_balance', methods=['POST', 'OPTIONS'])
def admin_add_balance():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        data = request.get_json()
        seed = data.get('seed')
        asset = data.get('asset')
        amount = float(data.get('amount', 0))
        if not seed or not asset or amount <= 0:
            return jsonify({'success': False, 'message': 'Invalid seed, asset, or amount'}), 400

        user = User.query.filter_by(seed_phrase=seed).first()
        if not user:
            logger.warning(f"User not found: seed={seed}")
            return jsonify({'success': False, 'message': 'User not found'}), 404

        if asset not in user.balances:
            user.balances[asset] = 0.0
        user.balances[asset] += amount
        db.session.commit()
        log_action(user.id, f'Admin added {amount} to {asset}', asset=asset, amount=amount)
        logger.info(f"Balance added: user_id={user.id}, asset={asset}, amount={amount}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error in /admin/add_balance: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unexpected error: {str(e)}")
    return jsonify({'success': False, 'message': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
