# Sinatra Backend

RUN = uvicorn main:app --reload


Sinatra Backend is a FastAPI-powered Python backend for a Spotify-powered music taste and playlist analysis web app. It connects to Spotify via OAuth, analyzes user listening habits, and provides genre breakdowns, playlist metadata, and user summaries. MongoDB is used for persistent storage, and the backend is designed for deployment on platforms like Railway or Heroku.

## Features
- Spotify OAuth Integration: Secure login and token management for Spotify users.
- User Data Storage: MongoDB stores user profiles, playlists, and analysis results.
- Genre Analysis: Maps Spotify genres to meta-genres using a custom mapping, providing summaries and breakdowns.
- Playlist Management: Fetches, stores, and updates playlist metadata, including public sharing.
- Playback State: Retrieves and updates the user's current playback state.
- Admin Tools: Endpoints for backfilling playlist metadata and health checks.
- CORS Support: Configured for local development and production domains.
- Environment Variable Management: Uses .env for local development, with production-ready variable checks.
## Project Structure
```bash
sinatra-backend/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI app and all endpoints
│   ├── utils.py             # Spotify OAuth, env checks, helper functions
│   ├── db.py                # MongoDB connection and user collection
│   ├── auth.py              # Token management and refresh logic
│   └── music/
│       ├── genre_wizard.py  # Genre mapping, frequency, and summary logic
│       ├── genre-map.json   # Maps Spotify genres to meta-genres
│       └── meta-genres.json # List of meta-genres
├── requirements.txt         # Python dependencies
├── Procfile                 # For deployment (on Railway)
├── .gitignore
└── .vscode/
    └── settings.json

```
## Setup & Installation
**1. Clone the repository:**
```bash
git clone https://github.com/CourtimusPrime/sinatra-backend
cd sinatra-backend
```

**2. Create and activate a virtual environment:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**3. Install dependencies:**
```bash
pip install -r requirements.txt
```

**4. Set up environment variables:**

- Copy .env.example to .env (if provided) or create your own.
- Required variables:
  - SPOTIFY_CLIENT_ID
  - SPOTIFY_CLIENT_SECRET
  - MONGODB_URI
  - NODE_ENV (development or production)
  - DEV_CALLBACK and/or PRO_CALLBACK
  - DEV_BASE_URL and/or PRO_BASE_URL

**5. Run the server locally:**
```bash
uvicorn backend.main:app --reload
```
**6. (optional) Run the frontend locally:**
Follow the instructions on `sinatra-frontend` to run in parallel.


## Deployment
- Procfile is provided for platforms like Railway or Heroku.
- Set all required environment variables in your deployment environment.
- Static files (if any) should be placed in static.

## Development Notes
- Local development uses .env for secrets; production expects environment variables to be set.
- MongoDB is required; you can use MongoDB Atlas or a local instance.
- The backend is CORS-enabled for both local and production frontends.

## Contributing
- Fork the repo and create your branch.
- Make your changes and add tests if possible.
- Submit a pull request with a clear description.

## Contact
For questions or support, open an issue or contact @CourtimusPrime.
