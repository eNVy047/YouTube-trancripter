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
- If YouTube download is blocked (HTTP 403 on Streamlit Cloud), use **Fallback: Upload Audio** on Home page.

## Speech-to-text output

- Choose a Whisper model size (`tiny`, `base`, or `small`).
- Click **Transcribe Audio** after downloading.
- Transcript files are saved under `downloads/transcripts/`.
- After successful transcription, the downloaded audio file is deleted automatically.
- The page shows a **Resulting Text** heading with the transcript and a **Copy Text** button.
- The **Generated Text** page lists `.txt` transcript files and opens the selected one for reading and copying.
- Transcript files are retained for 1 day, then deleted automatically by app cleanup.

## Deployment note

This setup is server-friendly because it runs fully local inference with Faster-Whisper and does not rely on external speech APIs.

If you deploy on Streamlit Community Cloud, YouTube downloads may fail with HTTP 403 due to shared cloud IP restrictions. For stable downloads, deploy on your own VPS/server.

