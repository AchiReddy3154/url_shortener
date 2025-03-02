from flask import Flask, request, jsonify, render_template, redirect, abort, session, url_for
from pymongo import MongoClient
import random
import string
import datetime
import qrcode
import io
import base64
from bson import ObjectId
import bcrypt
import validators
import requests
from bs4 import BeautifulSoup
import plotly.express as px
import pandas as pd
from urllib.parse import urlparse
import os

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')  # Change this in production

# MongoDB connection
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/urlshortener')
try:
    client = MongoClient(MONGODB_URI)
    # Test the connection
    client.admin.command('ping')
    # Get database name from URI or use default
    db_name = MONGODB_URI.split('/')[-1].split('?')[0] or 'urlshortener'
    db = client[db_name]
    print(f"Successfully connected to MongoDB database: {db_name}")
except Exception as e:
    print(f"Error connecting to MongoDB: {str(e)}")
    raise

def is_url_malicious(url):
    try:
        # Basic URL validation
        if not validators.url(url):
            return True, "Invalid URL format"
            
        # Check URL parsing
        parsed = urlparse(url)
        if not all([parsed.scheme, parsed.netloc]):
            return True, "Invalid URL structure"
            
        # Check for common malicious patterns
        suspicious_patterns = [
            'phishing', 'malware', 'virus', 'hack', 
            '.exe', '.dll', '.bat', '.cmd', '.scr'
        ]
        if any(pattern in url.lower() for pattern in suspicious_patterns):
            return True, "URL contains suspicious patterns"
            
        # Fetch and check webpage content (optional, might slow down URL creation)
        response = requests.get(url, timeout=5, verify=True)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Check for suspicious meta content
        meta_tags = soup.find_all('meta')
        suspicious_meta = ['phishing', 'malware', 'virus']
        for tag in meta_tags:
            content = tag.get('content', '').lower()
            if any(term in content for term in suspicious_meta):
                return True, "Webpage contains suspicious content"
                
        return False, "URL appears safe"
    except Exception as e:
        return True, f"Error checking URL: {str(e)}"

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed)

def generate_short_code():
    characters = string.ascii_letters + string.digits
    while True:
        code = ''.join(random.choices(characters, k=6))
        if not db.urls.find_one({"short_code": code}):
            return code

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = db.users.find_one({'username': username})
        if user and check_password(password, user['password']):
            session['user_id'] = str(user['_id'])
            session['username'] = username
            return redirect(url_for('index'))
        return render_template('signin.html', error='Invalid username or password')
    
    return render_template('signin.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if db.users.find_one({'username': username}):
            return render_template('signup.html', error='Username already exists')
        
        user_id = db.users.insert_one({
            'username': username,
            'password': hash_password(password),
            'created_at': datetime.datetime.utcnow(),
            'urls_created': [],
            'total_visits': 0
        }).inserted_id
        
        session['user_id'] = str(user_id)
        session['username'] = username
        return redirect(url_for('index'))
    
    return render_template('signup.html')

@app.route('/signout')
def signout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/shorten', methods=['POST'])
def shorten_url():
    try:
        data = request.json
        long_url = data.get('url')
        custom_code = data.get('custom_code')
        expiration_days = int(data.get('expiration_days', 30))
        password = data.get('password')
        schedule_start = data.get('schedule_start')
        schedule_end = data.get('schedule_end')

        if not long_url:
            return jsonify({"error": "URL is required"}), 400

        # Check for malicious URL
        is_malicious, message = is_url_malicious(long_url)
        if is_malicious:
            return jsonify({"error": f"URL appears unsafe: {message}"}), 400

        if custom_code:
            if db.urls.find_one({"short_code": custom_code}):
                return jsonify({"error": "Custom code already exists"}), 400
            short_code = custom_code
        else:
            short_code = generate_short_code()

        # Create URL document
        url_doc = {
            "long_url": long_url,
            "short_code": short_code,
            "created_at": datetime.datetime.utcnow(),
            "expires_at": datetime.datetime.utcnow() + datetime.timedelta(days=expiration_days),
            "clicks": 0,
            "click_times": [],
            "is_active": True
        }

        # Add user ID if logged in
        if 'user_id' in session:
            url_doc['user_id'] = ObjectId(session['user_id'])

        if password:
            url_doc["password_hash"] = hash_password(password)

        if schedule_start:
            url_doc["schedule_start"] = datetime.datetime.fromisoformat(schedule_start.replace('Z', '+00:00'))
        if schedule_end:
            url_doc["schedule_end"] = datetime.datetime.fromisoformat(schedule_end.replace('Z', '+00:00'))

        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        short_url = request.host_url + short_code
        qr.add_data(short_url)
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color="black", back_color="white")
        
        # Convert QR code to base64
        buffered = io.BytesIO()
        qr_image.save(buffered, format="PNG")
        qr_code_base64 = base64.b64encode(buffered.getvalue()).decode()

        # Save to database
        result = db.urls.insert_one(url_doc)

        # Update user's urls_created if logged in
        if 'user_id' in session:
            db.users.update_one(
                {'_id': ObjectId(session['user_id'])},
                {'$push': {'urls_created': result.inserted_id}}
            )

        return jsonify({
            "short_url": short_url,
            "qr_code": f"data:image/png;base64,{qr_code_base64}",
            "expiry_date": url_doc["expires_at"],
            "stats": {
                "clicks": 0,
                "created_at": url_doc["created_at"]
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/<short_code>', methods=['GET', 'POST'])
def redirect_url(short_code):
    url_doc = db.urls.find_one({"short_code": short_code})
    
    if not url_doc:
        abort(404)

    # Check if URL is expired
    if url_doc.get("expires_at") < datetime.datetime.utcnow():
        return "This link has expired", 410

    # Check scheduling
    now = datetime.datetime.utcnow()
    if url_doc.get("schedule_start") and now < url_doc["schedule_start"]:
        return "This link is not yet active", 403
    if url_doc.get("schedule_end") and now > url_doc["schedule_end"]:
        return "This link has expired", 410

    # Handle password protection
    if url_doc.get("password_hash"):
        if request.method == 'GET':
            return render_template('password.html', short_code=short_code)
        else:
            password = request.form.get('password')
            if not password or not check_password(password, url_doc["password_hash"]):
                return "Invalid password", 401

    # Update click statistics
    click_time = datetime.datetime.utcnow()
    db.urls.update_one(
        {"_id": url_doc["_id"]},
        {
            "$inc": {"clicks": 1},
            "$push": {"click_times": click_time}
        }
    )

    # Update user's total_visits if URL belongs to a user
    if url_doc.get('user_id'):
        db.users.update_one(
            {'_id': url_doc['user_id']},
            {'$inc': {'total_visits': 1}}
        )

    return redirect(url_doc["long_url"])

@app.route('/stats/<short_code>')
def get_stats(short_code):
    url_doc = db.urls.find_one({"short_code": short_code})
    if not url_doc:
        abort(404)

    # Generate click time graph data
    click_times = url_doc.get("click_times", [])
    if click_times:
        df = pd.DataFrame(click_times, columns=['timestamp'])
        df['date'] = df['timestamp'].dt.date
        daily_clicks = df.groupby('date').size().reset_index(name='clicks')
        
        fig = px.line(daily_clicks, x='date', y='clicks', 
                     title='Click History',
                     labels={'date': 'Date', 'clicks': 'Number of Clicks'})
        graph_html = fig.to_html(full_html=False)
    else:
        graph_html = "<p>No click data available</p>"

    return render_template(
        'stats.html',
        url=url_doc,
        graph_html=graph_html,
        total_clicks=url_doc.get("clicks", 0),
        created_at=url_doc["created_at"],
        expires_at=url_doc.get("expires_at"),
        is_password_protected=bool(url_doc.get("password_hash")),
        schedule_start=url_doc.get("schedule_start"),
        schedule_end=url_doc.get("schedule_end")
    )

@app.route('/urls')
def get_urls():
    urls = list(db.urls.find(
        {},
        {
            "short_code": 1,
            "long_url": 1,
            "clicks": 1,
            "created_at": 1,
            "expires_at": 1,
            "is_password_protected": {"$cond": [{"$ifNull": ["$password_hash", False]}, True, False]},
            "has_schedule": {"$cond": [
                {"$or": [
                    {"$ne": ["$schedule_start", None]},
                    {"$ne": ["$schedule_end", None]}
                ]},
                True,
                False
            ]}
        }
    ).sort("created_at", -1).limit(10))

    current_time = datetime.datetime.utcnow()
    for url in urls:
        url["_id"] = str(url["_id"])
        url["short_url"] = request.host_url + url["short_code"]
        url["is_expired"] = url["expires_at"] < current_time if url.get("expires_at") else False
        # Format dates for display
        url["created_at"] = url["created_at"].strftime("%Y-%m-%d %H:%M UTC")
        url["expires_at"] = url["expires_at"].strftime("%Y-%m-%d %H:%M UTC") if url.get("expires_at") else None

    return jsonify(urls)

@app.route('/user/stats')
def user_stats():
    if 'user_id' not in session:
        return redirect(url_for('signin'))
    
    user = db.users.find_one({'_id': ObjectId(session['user_id'])})
    if not user:
        session.clear()
        return redirect(url_for('signin'))
    
    # Get user's URLs and their stats
    urls = list(db.urls.find({'user_id': ObjectId(session['user_id'])}))
    
    total_clicks = sum(url.get('clicks', 0) for url in urls)
    urls_created = len(urls)
    
    # Get click distribution over time
    all_clicks = []
    for url in urls:
        all_clicks.extend(url.get('click_times', []))
    
    # Create time series data for clicks
    clicks_chart = None
    if all_clicks:
        try:
            df = pd.DataFrame({'clicks': all_clicks})
            df['date'] = pd.to_datetime(df['clicks'])
            daily_clicks = df.groupby(df['date'].dt.date).size().reset_index()
            daily_clicks.columns = ['date', 'clicks']
            
            fig = px.line(daily_clicks, x='date', y='clicks', 
                         title='Your URL Clicks Over Time',
                         labels={'date': 'Date', 'clicks': 'Number of Clicks'})
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#718096'
            )
            clicks_chart = fig.to_html(full_html=False)
        except Exception as e:
            print(f"Error generating chart: {str(e)}")
            clicks_chart = None
    
    return render_template('stats.html', 
                         user=user,
                         total_clicks=total_clicks,
                         urls_created=urls_created,
                         urls=urls,
                         clicks_chart=clicks_chart,
                         now=datetime.datetime.utcnow())

if __name__ == '__main__':
    app.run(debug=True)
