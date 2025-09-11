from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_migrate import Migrate
from pycoingecko import CoinGeckoAPI
import random
import string
from datetime import datetime, timedelta
import logging
import os
from sqlalchemy.sql import text
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.dialects.postgresql import JSONB
import threading

app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "*", "supports_credentials": True, "methods": ["GET", "POST", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]}})

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:ZXlFWOKNnvLBaVPtNBqFoCKHCWVBJzgX@hopper.proxy.rlwy.net:21971/railway'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'max_overflow': 20,
    'pool_timeout': 30,
    'pool_pre_ping': True
}

db = SQLAlchemy(app)
migrate = Migrate(app, db)
cg = CoinGeckoAPI()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

words = [
    'apple', 'ball', 'cat', 'dog', 'egg', 'fish', 'goat', 'hat', 'ice', 'jam', 'kit', 'log',
    'man', 'net', 'oak', 'pig', 'quilt', 'rat', 'sun', 'top', 'up', 'van', 'win', 'xray',
    'yak', 'zip', 'ant', 'bee', 'cow', 'duck', 'ear', 'fox', 'gun', 'hen', 'ink', 'jug'
]

price_cache = {
    'data': None,
    'last_update': None,
    'lock': threading.Lock()
}

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    wallet_name = db.Column(db.String(50), default='Main wallet')
    seed_phrase = db.Column(db.Text, unique=True, nullable=False, index=True)
    pin = db.Column(db.String(6), nullable=False)
    balances = db.Column(MutableDict.as_mutable(JSONB), default=lambda: {
        'BTC': 0.0, 'ETH': 0.0, 'XLM': 0.0, 'UNI': 0.0, 'KOGE': 0.0, 'BR': 0.0,
        'USDT': 0.0, 'TRX': 0.0  # Додано USDT і TRX
    })
    address = db.Column(db.String(34), unique=True, nullable=True)

class Log(db.Model):
    __tablename__ = 'log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    action = db.Column(db.Text, nullable=False)
    asset = db.Column(db.String(10), nullable=True)
    amount = db.Column(db.Float, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

def generate_seed():
    return ' '.join(random.choice(words) for _ in range(12))

def generate_pin():
    return ''.join(random.choice(string.digits) for _ in range(6))

def generate_trc20_address():
    characters = string.ascii_letters + string.digits
    address = 'T' + ''.join(random.choice(characters) for _ in range(33))
    with app.app_context():
        while User.query.filter_by(address=address).first():
            address = 'T' + ''.join(random.choice(characters) for _ in range(33))
    return address

def log_action(user_id, action, asset=None, amount=None):
    try:
        log = Log(user_id=user_id, action=action, asset=asset, amount=amount)
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to log action: {str(e)}")
        db.session.rollback()

def init_db():
    try:
        with app.app_context():
            db.create_all()
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('user')]
            if 'address' not in columns:
                logger.info("Adding 'address' column to 'user' table")
                with db.engine.connect() as connection:
                    connection.execute(text('ALTER TABLE "user" ADD COLUMN address VARCHAR(34) UNIQUE'))
                    connection.commit()
            columns = [col['name'] for col in inspector.get_columns('log')]
            if 'asset' not in columns:
                logger.info("Adding 'asset' column to 'log' table")
                with db.engine.connect() as connection:
                    connection.execute(text('ALTER TABLE log ADD COLUMN asset VARCHAR(10)'))
                    connection.commit()
            if 'amount' not in columns:
                logger.info("Adding 'amount' column to 'log' table")
                with db.engine.connect() as connection:
                    connection.execute(text('ALTER TABLE log ADD COLUMN amount FLOAT'))
                    connection.commit()
            users_without_address = User.query.filter((User.address == None) | (User.address == '')).all()
            for user in users_without_address:
                user.address = generate_trc20_address()
                logger.info(f"Generated TRC-20 address for user_id={user.id}: {user.address}")
            db.session.commit()
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        db.session.rollback()

with app.app_context():
    init_db()

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

def get_cached_prices():
    with price_cache['lock']:
        # Дефолтні ціни на випадок помилок
        default_prices = {
            'bitcoin': {'usd': 104000.0, 'usd_24h_change': 0.0},
            'ethereum': {'usd': 4200.0, 'usd_24h_change': 0.0},
            'stellar': {'usd': 0.1, 'usd_24h_change': 0.0},
            'uniswap': {'usd': 6.0, 'usd_24h_change': 0.0},
            'koge': {'usd': 0.01, 'usd_24h_change': 0.0},
            'billionaire': {'usd': 0.001, 'usd_24h_change': 0.0},
            'tether': {'usd': 1.0, 'usd_24h_change': 0.0},
            'tron': {'usd': 0.15, 'usd_24h_change': 0.0}
        }
        
        # Якщо кеш старіший 60 секунд - оновлюємо
        if price_cache['last_update'] is None or (datetime.now() - price_cache['last_update']).total_seconds() > 60:
            try:
                logger.info("Fetching fresh prices from CoinGecko")
                prices = cg.get_price(
                    ids=['bitcoin', 'ethereum', 'stellar', 'uniswap', 'koge', 'billionaire', 'tether', 'tron'],
                    vs_currencies='usd',
                    include_24hr_change=True
                )
                if prices:
                    price_cache['data'] = prices
                    price_cache['last_update'] = datetime.now()
                    logger.info("CoinGecko prices updated successfully")
                else:
                    logger.warning("CoinGecko returned empty response, using default prices")
                    price_cache['data'] = default_prices
            except Exception as e:
                logger.error(f"Error fetching prices from CoinGecko: {str(e)}")
                # Використовуємо дефолтні ціни при помилці
                price_cache['data'] = default_prices
                price_cache['last_update'] = datetime.now()
        
        # Завжди повертаємо дані, навіть якщо це дефолтні
        return price_cache['data'] or default_prices

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
        address = generate_trc20_address()
        user = User(seed_phrase=seed, pin=pin, wallet_name='Main wallet', address=address)
        db.session.add(user)
        db.session.commit()
        log_action(user.id, 'Wallet created')
        logger.info(f"Wallet created: id={user.id}, seed={seed}, address={address}")
        return jsonify({
            'success': True,
            'id': user.id,
            'seed': seed,
            'pin': pin,
            'wallet_name': user.wallet_name,
            'address': user.address
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
        if user:
            # Оновлюємо PIN-код на новий
            user.pin = pin
            user.wallet_name = wallet_name
            db.session.commit()
            log_action(user.id, 'Logged in')
            logger.info(f"Login successful: id={user.id}")
            return jsonify({
                'success': True,
                'id': user.id,
                'balances': user.balances,
                'wallet_name': user.wallet_name,
                'address': user.address
            })
        logger.warning(f"Invalid seed: seed={seed}")
        return jsonify({'success': False, 'message': 'Invalid seed'}), 401
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
        if not user_id or user_id == 'null':
            logger.warning(f"Invalid user_id: {user_id}")
            return jsonify({'success': False, 'message': 'Invalid user ID'}), 400

        user = db.session.get(User, user_id)
        if not user:
            logger.warning(f"User not found: user_id={user_id}")
            return jsonify({'success': False, 'message': 'User not found'}), 404

        # ВИКОРИСТОВУЄМО КЕШОВАНІ ЦІНИ
        prices = get_cached_prices()

        token_images = {
            'BTC': 'images/btc.png',
            'ETH': 'images/eth.png',
            'XLM': 'images/xlm.png',
            'UNI': 'images/uni.png',
            'KOGE': 'images/koge.png',
            'BR': 'images/br.png',
            'USDT': 'images/usdt.png',
            'TRX': 'images/trx.png'
        }
        
        balances = [
            {
                'name': {
                    'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'XLM': 'Stellar',
                    'UNI': 'Uniswap', 'KOGE': 'Koge', 'BR': 'Billionaire',
                    'USDT': 'Tether', 'TRX': 'TRON'
                }.get(symbol, symbol),
                'symbol': symbol,
                'balance': float(balance) if balance is not None and not isinstance(balance, str) else 0.0,
                'image': token_images.get(symbol, 'images/default-coin.png'),
                'price': float(prices.get(id, {}).get('usd', 0.0)) if prices.get(id) else 0.0
            }
            for symbol, balance in user.balances.items()
            for id in [
                'bitcoin' if symbol == 'BTC' else
                'ethereum' if symbol == 'ETH' else
                'stellar' if symbol == 'XLM' else
                'uniswap' if symbol == 'UNI' else
                'koge' if symbol == 'KOGE' else
                'billionaire' if symbol == 'BR' else
                'tether' if symbol == 'USDT' else
                'tron' if symbol == 'TRX' else symbol.lower()
            ]
            if float(balance) > 0
        ]
        
        log_action(user.id, 'Viewed balances')
        logger.info(f"Balances retrieved: user_id={user_id}")
        return jsonify({
            'success': True,
            'balances': balances,
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

        wallets = [{'id': user.id, 'name': user.wallet_name, 'address': user.address}]
        prices = cg.get_price(
            ids=['bitcoin', 'ethereum', 'stellar', 'uniswap', 'koge', 'billionaire'],
            vs_currencies='usd',
            include_24hr_change=True
        ) or {
            'bitcoin': {'usd': 60000.0, 'usd_24h_change': 0.0},
            'ethereum': {'usd': 2500.0, 'usd_24h_change': 0.0},
            'stellar': {'usd': 0.1, 'usd_24h_change': 0.0},
            'uniswap': {'usd': 6.0, 'usd_24h_change': 0.0},
            'koge': {'usd': 0.01, 'usd_24h_change': 0.0},
            'billionaire': {'usd': 0.001, 'usd_24h_change': 0.0}
        }
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

@app.route('/send_transaction', methods=['POST', 'OPTIONS'])
def send_transaction():
    if request.method == 'OPTIONS':
        return '', 204
    
    start_time = datetime.now()
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        coin_symbol = data.get('coin_symbol')
        amount = data.get('amount')
        recipient_address = data.get('recipient_address')
        network_fee = data.get('network_fee', 0.0)

        if not all([user_id, coin_symbol, amount, recipient_address]):
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400

        try:
            user_id = int(user_id)
            amount = float(amount)
            network_fee = float(network_fee)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Invalid data format'}), 400

        sender = db.session.get(User, user_id)
        if not sender:
            return jsonify({'success': False, 'message': 'Sender not found'}), 404

        coin_symbol = coin_symbol.upper()
        
        if coin_symbol not in sender.balances or float(sender.balances.get(coin_symbol, 0)) < amount:
            return jsonify({'success': False, 'message': 'Insufficient balance'}), 400

        if network_fee > 0:
            trx_balance = float(sender.balances.get('TRX', 0))
            if trx_balance < network_fee:
                return jsonify({'success': False, 'message': 'Insufficient TRX for network fee'}), 400

        # Оновлюємо баланси
        sender_balance_before = float(sender.balances.get(coin_symbol, 0))
        sender.balances[coin_symbol] = max(0, sender_balance_before - amount)
        
        if network_fee > 0:
            sender_trx_before = float(sender.balances.get('TRX', 0))
            sender.balances['TRX'] = max(0, sender_trx_before - network_fee)

        # ШВИДКИЙ коміт (без блокування!)
        db.session.commit()

        # ВИКОРИСТОВУЄМО КЕШОВАНІ ЦІНИ
        prices = get_cached_prices()
        coin_id = {
            'BTC': 'bitcoin', 'ETH': 'ethereum', 'XLM': 'stellar',
            'UNI': 'uniswap', 'KOGE': 'koge', 'BR': 'billionaire',
            'USDT': 'tether', 'TRX': 'tron'
        }.get(coin_symbol, coin_symbol.lower())
        
        usd_value = amount * float(prices.get(coin_id, {}).get('usd', 1.0))

        # Логування
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        logger.info(f"Transaction completed in {processing_time:.2f}s: user_id={user_id}, coin_symbol={coin_symbol}, amount={amount}")

        log_action(sender.id, f'Sent {amount} {coin_symbol} to {recipient_address}', coin_symbol, -amount)
        if network_fee > 0:
            log_action(sender.id, f'Paid {network_fee} TRX network fee', 'TRX', -network_fee)

        return jsonify({'success': True, 'usd_value': usd_value, 'fee': network_fee})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in /send_transaction: {str(e)}")
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

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

        coin_id = coin_id.upper()
        balance = float(user.balances.get(coin_id, 0.0)) if user.balances.get(coin_id) is not None else 0.0
        transactions = Log.query.filter_by(user_id=user_id, asset=coin_id).all()
        transaction_data = [
            {
                'amount': float(tx.amount) if tx.amount is not None and not isinstance(tx.amount, str) else 0.0,
                'asset': tx.asset,
                'action': tx.action,
                'timestamp': tx.timestamp.isoformat()
            }
            for tx in transactions if tx.amount is not None
        ]
        log_action(user.id, f'Viewed coin details for {coin_id}')
        logger.info(f"Coin details retrieved: user_id={user_id}, coin_id={coin_id}, balance={balance}")
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
            {
                'amount': float(tx.amount) if tx.amount is not None and not isinstance(tx.amount, str) else 0.0,
                'asset': tx.asset,
                'action': tx.action,
                'timestamp': tx.timestamp.isoformat()
            }
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
        address = generate_trc20_address()
        user = User(seed_phrase=seed, pin=pin, wallet_name='Main wallet', address=address)
        db.session.add(user)
        db.session.commit()
        log_action(user.id, 'Admin created wallet')
        logger.info(f"Admin created wallet: id={user.id}, seed={seed}, address={address}")
        return jsonify({
            'success': True,
            'id': user.id,
            'seed': seed,
            'pin': pin,
            'wallet_name': user.wallet_name,
            'address': user.address
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
        amount = data.get('amount')
        if not seed or not asset or amount is None:
            return jsonify({'success': False, 'message': 'Invalid seed, asset, or amount'}), 400

        try:
            amount = float(amount)
            if amount <= 0 or not isinstance(amount, (int, float)) or str(amount) == 'nan':
                return jsonify({'success': False, 'message': 'Invalid amount'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Invalid amount format'}), 400

        user = User.query.filter_by(seed_phrase=seed).first()
        if not user:
            logger.warning(f"User not found: seed={seed}")
            return jsonify({'success': False, 'message': 'User not found'}), 404

        asset = asset.upper()
        if asset not in user.balances:
            user.balances[asset] = 0.0
        user.balances[asset] = float(user.balances[asset]) + amount
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
