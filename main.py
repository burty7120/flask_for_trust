from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import random
import string
from datetime import datetime
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
# Використовуємо твоє посилання до бази даних
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:FkLEPOrXzVjKQMRdtbQnhiXWYfjpkUFk@centerbeam.proxy.rlwy.net:52075/railway'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Список коротких англійських слів для seed
words = [
    'apple', 'ball', 'cat', 'dog', 'egg', 'fish', 'goat', 'hat', 'ice', 'jam', 'kit', 'log',
    'man', 'net', 'oak', 'pig', 'quilt', 'rat', 'sun', 'top', 'up', 'van', 'win', 'xray',
    'yak', 'zip', 'ant', 'bee', 'cow', 'duck', 'ear', 'fox', 'gun', 'hen', 'ink', 'jug'
]

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wallet_name = db.Column(db.String(50), default='Main wallet')  # Додано назву гаманця
    seed_phrase = db.Column(db.Text, unique=True, nullable=False)
    pin = db.Column(db.String(6), nullable=False)
    balances = db.Column(db.JSON, default=lambda: {
        'BTC': 0, 'ETH': 0, 'XLM': 0, 'UNI': 0, 'KOGE': 0, 'BR': 0
    })

class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

def generate_seed():
    return ' '.join(random.choice(words) for _ in range(12))

def generate_pin():
    return ''.join(random.choice(string.digits) for _ in range(6))

def log_action(user_id, action):
    log = Log(user_id=user_id, action=action)
    db.session.add(log)
    db.session.commit()

@app.route('/generate', methods=['POST'])
def generate_wallet():
    seed = generate_seed()
    pin = generate_pin()
    user = User(seed_phrase=seed, pin=pin)
    db.session.add(user)
    db.session.commit()
    log_action(user.id, 'Wallet created')
    return jsonify({'success': True, 'id': user.id, 'seed': seed, 'pin': pin, 'wallet_name': user.wallet_name})

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    seed = data.get('seed')
    pin = data.get('pin')
    wallet_name = data.get('wallet_name', 'Main wallet')
    user = User.query.filter_by(seed_phrase=seed).first()
    if user and user.pin == pin:
        user.wallet_name = wallet_name  # Оновити назву гаманця, якщо задано
        db.session.commit()
        log_action(user.id, 'Logged in')
        return jsonify({'success': True, 'id': user.id, 'balances': user.balances, 'wallet_name': user.wallet_name})
    return jsonify({'success': False})

@app.route('/get_balances', methods=['GET'])
def get_balances():
    user_id = request.args.get('user_id')
    user = User.query.get(user_id)
    if user:
        log_action(user.id, 'Viewed balances')
        return jsonify({'success': True, 'balances': user.balances})
    return jsonify({'success': False})

@app.route('/admin/create_wallet', methods=['POST'])
def admin_create_wallet():
    seed = generate_seed()
    pin = generate_pin()
    user = User(seed_phrase=seed, pin=pin)
    db.session.add(user)
    db.session.commit()
    log_action(user.id, 'Admin created wallet')
    return jsonify({'success': True, 'id': user.id, 'seed': seed, 'pin': pin, 'wallet_name': user.wallet_name})

@app.route('/admin/add_balance', methods=['POST'])
def admin_add_balance():
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

# Ініціалізація таблиць при запуску з обробкою помилок
with app.app_context():
    try:
        db.create_all()
        print("Таблиці створено або вже існують.")
    except Exception as e:
        print(f"Помилка при створенні таблиць: {e}")

if __name__ == '__main__':
    app.run(debug=True, port=5000)
