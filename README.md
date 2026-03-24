# Streamlit UI (Step 1)

This project now includes a basic Streamlit interface to input a YouTube URL.
It also supports downloading audio from that URL using `yt-dlp`.
Audio is transcribed using a local Faster-Whisper model (no external API required).

## Run locally

1. Activate your virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
streamlit run app.py
```

The app will open in your browser and show a field where you can paste a YouTube link.

## Pages

- **Home** (`app.py`): perform the task (download audio and transcribe).
- **Generated Text** (`pages/2_Generated_Text.py`): view only generated transcript text files.

## Audio download output

- Click **Download Audio** after entering a valid YouTube URL.
- Downloaded files are saved under `downloads/audio/` in this project folder.

## Speech-to-text output

- Choose a Whisper model size (`tiny`, `base`, or `small`).
- Click **Transcribe Audio** after downloading.
- Transcript files are saved under `downloads/transcripts/`.
- After successful transcription, the downloaded audio file is deleted automatically.
- The page shows a **Resulting Text** heading with the transcript and a **Copy Text** button.
- The **Generated Text** page lists `.txt` transcript files and opens the selected one for reading and copying.
- Transcript files are retained for 1 day, then deleted automatically by app cleanup.

## Deployment

### Local Server (Recommended for YouTube transcription)

This setup is server-friendly because it runs fully local inference with Faster-Whisper and does not rely on external speech APIs.

**Note:** If you deploy on Streamlit Community Cloud, YouTube downloads may fail with HTTP 403 due to shared cloud IP restrictions.

### Deploy on Render

Render provides a reliable hosting platform with good performance for this application.

#### Prerequisites
- Render account (free tier available)
- GitHub repository with your code
- `render.yaml` configuration file

#### Steps

1. **Create `render.yaml` in your project root:**

```yaml
services:
  - type: web
    name: youtube-transcriber
    env: python
    plan: standard
    pythonVersion: 3.11
    buildCommand: pip install -r requirements.txt
    startCommand: streamlit run app.py --server.port=10000 --server.address=0.0.0.0
    envVars:
      - key: STREAMLIT_SERVER_HEADLESS
        value: true
```

2. **Create `.streamlit/config.toml` for Render:**

```toml
[server]
headless = true
port = 10000
enableXsrfProtection = true
enableCORS = true

[logger]
level = "info"

[client]
toolbarMode = "viewer"
```

3. **Push to GitHub:**

```bash
git add .
git commit -m "Add Render deployment config"
git push
```

4. **Deploy on Render:**
   - Go to [render.com](https://render.com)
   - Connect your GitHub repository
   - Click "New +" → "Web Service"
   - Select your repository
   - Render will auto-detect and use `render.yaml`
   - Click "Create Web Service"

5. **Monitor deployment:**
   - Check logs in Render dashboard
   - Service will be live at: `https://youtube-transcriber-xxxxx.onrender.com`

#### Notes
- **Storage:** Transcripts are saved in `/tmp` on Render (ephemeral). For permanent storage, consider adding:
  - AWS S3 integration
  - Render Disks (paid feature)
  - External database
- **Performance:** May need to upgrade plan for large playlists (100+ videos)
- **Memory:** Standard tier (512MB) may struggle with `small`/`medium` Whisper models; use `tiny` or `base` instead

