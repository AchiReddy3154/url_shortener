# URL Shortener Service

A modern URL shortening service with analytics and security features built using Python Flask and MongoDB.

## Features

- URL shortening with custom code option
- Expiration management for URLs
- Click tracking and analytics
- Protection against malicious URLs using Google Safe Browsing API
- Rate limiting to prevent abuse
- Modern, responsive UI built with Tailwind CSS
- Real-time analytics visualization using Chart.js

## Prerequisites

- Python 3.7+
- MongoDB
- Google Safe Browsing API key (optional, for malicious URL detection)

## Installation

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set up MongoDB:
   - Install MongoDB
   - Start MongoDB service
   - The application will automatically create required collections

4. Configure environment variables:
   - Copy `.env.example` to `.env`
   - Add your Google Safe Browsing API key (optional)
   - Add a secret key for Flask

## Running the Application

1. Start MongoDB service
2. Run the Flask application:
   ```
   python app.py
   ```
3. Access the application at `http://localhost:5000`

## API Endpoints

- `POST /shorten`: Create a shortened URL
  - Parameters:
    - `url`: Long URL to shorten
    - `custom_code`: (optional) Custom short code
    - `expiration_days`: (optional) Number of days until URL expires

- `GET /<short_code>`: Redirect to original URL

- `GET /analytics/<short_code>`: Get analytics for a shortened URL

## Security Features

- URL validation
- Malicious URL detection using Google Safe Browsing API
- Rate limiting to prevent abuse
- URL expiration management

## Contributing

Feel free to submit issues and enhancement requests!

## License

MIT License
