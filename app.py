from flask import Flask, request, jsonify, render_template, redirect
from pymongo import MongoClient
from datetime import datetime, timedelta
import string
import random
import validators
import qrcode
import io
import base64
import os
import sys

app = Flask(__name__)

# MongoDB Atlas connection with better error handling
try:
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')
    print(f"Connecting to MongoDB... (URI prefix: {mongodb_uri.split('@')[0].split('://')[0]}://****)")
    client = MongoClient(mongodb_uri)
    # Test the connection
    client.admin.command('ping')
    print("Successfully connected to MongoDB!")
    db = client.url_shortener
    urls_collection = db.urls
except Exception as e:
    print(f"Failed to connect to MongoDB: {str(e)}", file=sys.stderr)
    # Don't raise the exception, let the app start but handle errors in routes

# Create indexes
try:
    urls_collection.create_index('short_code', unique=True)
    urls_collection.create_index('created_at')
    urls_collection.create_index('expires_at')
    print("Successfully created MongoDB indexes")
except Exception as e:
    print(f"Failed to create indexes: {str(e)}", file=sys.stderr)

def generate_short_code(length=6):
    characters = string.ascii_letters + string.digits
    while True:
        code = ''.join(random.choice(characters) for _ in range(length))
        if not urls_collection.find_one({'short_code': code}):
            return code

def generate_qr_code(url):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffered.getvalue()).decode()}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/shorten', methods=['POST'])
def shorten_url():
    try:
        print("Received URL shortening request")
        data = request.get_json()
        if not data or 'url' not in data:
            print("Error: URL is missing from request")
            return jsonify({'error': 'URL is required'}), 400
            
        long_url = data['url']
        custom_code = data.get('custom_code')
        expiration_days = int(data.get('expiration_days', 30))
        
        print(f"Processing URL: {long_url}, Custom code: {custom_code}, Expiration: {expiration_days} days")
        
        if not validators.url(long_url):
            print(f"Error: Invalid URL format - {long_url}")
            return jsonify({'error': 'Invalid URL'}), 400
            
        # Use custom code or generate one
        short_code = custom_code if custom_code else generate_short_code()
        
        # Check if custom code exists
        if custom_code and urls_collection.find_one({'short_code': custom_code}):
            print(f"Error: Custom code already exists - {custom_code}")
            return jsonify({'error': 'Custom code already exists'}), 400
        
        # Create URL document
        url_doc = {
            'long_url': long_url,
            'short_code': short_code,
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(days=expiration_days),
            'clicks': 0,
            'last_accessed': None,
            'user_agent_stats': {}
        }
        
        print(f"Attempting to save URL document with short code: {short_code}")
        
        # Save to database
        try:
            urls_collection.insert_one(url_doc)
            print(f"Successfully saved URL document")
        except Exception as db_error:
            print(f"Database error: {str(db_error)}")
            return jsonify({'error': 'Database error: ' + str(db_error)}), 500
        
        # Generate short URL and QR code
        short_url = f"{request.host_url}{short_code}"
        qr_code = generate_qr_code(short_url)
        
        print(f"Generated short URL: {short_url}")
        
        return jsonify({
            'short_url': short_url,
            'qr_code': qr_code,
            'expiry_date': url_doc['expires_at'].isoformat(),
            'stats': {
                'clicks': 0,
                'created_at': url_doc['created_at'].isoformat()
            }
        })
    except Exception as e:
        print(f"Unexpected error in shorten_url: {str(e)}")
        return jsonify({'error': 'Failed to shorten URL: ' + str(e)}), 500

@app.route('/<short_code>')
def redirect_url(short_code):
    try:
        # Find and update URL document
        url_doc = urls_collection.find_one_and_update(
            {
                'short_code': short_code,
                '$or': [
                    {'expires_at': {'$gt': datetime.utcnow()}},
                    {'expires_at': None}
                ]
            },
            {
                '$inc': {'clicks': 1},
                '$set': {'last_accessed': datetime.utcnow()},
                '$push': {
                    'access_log': {
                        'timestamp': datetime.utcnow(),
                        'user_agent': request.user_agent.string,
                        'ip': request.remote_addr
                    }
                }
            },
            return_document=True
        )
        
        if not url_doc:
            return render_template('error.html', message='URL not found or has expired'), 404
            
        return redirect(url_doc['long_url'])
    except Exception as e:
        print(f"Error in redirect: {str(e)}")
        return render_template('error.html', message='An error occurred'), 500

@app.route('/stats/<short_code>')
def get_url_stats(short_code):
    try:
        url_doc = urls_collection.find_one({'short_code': short_code})
        if not url_doc:
            return jsonify({'error': 'URL not found'}), 404
            
        stats = {
            'total_clicks': url_doc['clicks'],
            'created_at': url_doc['created_at'].isoformat(),
            'last_accessed': url_doc['last_accessed'].isoformat() if url_doc['last_accessed'] else None,
            'expires_at': url_doc['expires_at'].isoformat() if url_doc['expires_at'] else None,
            'is_expired': url_doc['expires_at'] < datetime.utcnow() if url_doc['expires_at'] else False
        }
        
        return jsonify(stats)
    except Exception as e:
        print(f"Error in stats: {str(e)}")
        return jsonify({'error': 'Failed to get stats'}), 500

@app.route('/urls')
def list_urls():
    try:
        urls = list(urls_collection.find(
            {},
            {'_id': 0, 'short_code': 1, 'long_url': 1, 'clicks': 1, 'created_at': 1}
        ).sort('created_at', -1).limit(10))
        
        return jsonify([{
            'short_url': f"{request.host_url}{url['short_code']}",
            'long_url': url['long_url'],
            'clicks': url['clicks'],
            'created_at': url['created_at'].isoformat()
        } for url in urls])
    except Exception as e:
        print(f"Error in list_urls: {str(e)}")
        return jsonify({'error': 'Failed to list URLs'}), 500

@app.route('/health')
def health_check():
    try:
        # Test MongoDB connection
        client.admin.command('ping')
        return jsonify({
            'status': 'healthy',
            'mongodb': 'connected',
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'mongodb': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

if __name__ == '__main__':
    app.run(debug=True)
