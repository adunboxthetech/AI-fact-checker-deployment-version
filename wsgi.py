from app import app

# Vercel (and WSGI servers like Gunicorn) look for a variable called "application"
application = app

if __name__ == "__main__":
    # For local debugging only
    app.run(host="0.0.0.0", port=5000, debug=True)