import os

port = os.getenv('PORT', '10000')
bind = f"0.0.0.0:{port}"
workers = 4
threads = 4
timeout = 120
