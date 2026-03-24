import json
import time
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components
import yt_dlp
from faster_whisper import WhisperModel
from yt_dlp.utils import DownloadError


def is_valid_youtube_url(url: str) -> bool:
    """Return True when the URL belongs to a known YouTube domain."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    domain = parsed.netloc.lower().replace("www.", "")
    allowed_domains = {"youtube.com", "youtu.be", "m.youtube.com"}
    return domain in allowed_domains


def download_audio(url: str, output_dir: Path) -> Path:
    """Download best available audio from URL and return saved file path."""
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "outtmpl": str(output_dir / "%(title).120s-%(id)s.%(ext)s"),
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "geo_bypass": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = Path(ydl.prepare_filename(info))
    except DownloadError as exc:
        raise RuntimeError(str(exc)) from exc

    return file_path


def save_uploaded_audio(uploaded_file, output_dir: Path) -> Path:
    """Persist uploaded audio to local storage and return file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(uploaded_file.name).name
    destination = output_dir / safe_name
    destination.write_bytes(uploaded_file.getbuffer())
    return destination


@st.cache_resource(show_spinner=False)
def load_stt_model(model_size: str) -> WhisperModel:
    """Load and cache a local Faster-Whisper model for CPU inference."""
    return WhisperModel(model_size, device="cpu", compute_type="int8")


def transcribe_audio(audio_path: Path, transcript_dir: Path, model_size: str) -> tuple[str, Path]:
    """Transcribe audio locally and save transcript text to disk."""
    transcript_dir.mkdir(parents=True, exist_ok=True)
    model = load_stt_model(model_size)

    segments, _ = model.transcribe(str(audio_path), beam_size=5)
    transcript_text = " ".join(segment.text.strip() for segment in segments).strip()

    transcript_path = transcript_dir / f"{audio_path.stem}.txt"
    transcript_path.write_text(transcript_text, encoding="utf-8")
    return transcript_text, transcript_path


def delete_audio_file(audio_path: Path) -> bool:
    """Delete audio file after transcription; return True when removed."""
    if audio_path.exists() and audio_path.is_file():
        audio_path.unlink()
        return True
    return False


def cleanup_old_transcripts(transcript_dir: Path, max_age_hours: int = 24) -> int:
    """Delete transcript files older than the configured retention window."""
    if not transcript_dir.exists():
        return 0

    cutoff_ts = time.time() - (max_age_hours * 3600)
    deleted_count = 0

    for transcript_file in transcript_dir.glob("*.txt"):
        try:
            if transcript_file.stat().st_mtime < cutoff_ts:
                transcript_file.unlink()
                deleted_count += 1
        except OSError:
            continue

    return deleted_count


def render_copy_button(text: str, button_id: str) -> None:
    """Render a browser-side copy button for transcript text."""
    js_text = json.dumps(text)
    components.html(
        f"""
        <button id="{button_id}" style="padding:8px 14px; border-radius:8px; border:1px solid #c9ced6; background:#ffffff; cursor:pointer;">Copy Text</button>
        <script>
        const textToCopy = {js_text};
        const copyBtn = document.getElementById({json.dumps(button_id)});
        copyBtn.addEventListener("click", async () => {{
            try {{
                await navigator.clipboard.writeText(textToCopy);
                copyBtn.textContent = "Copied";
                setTimeout(() => copyBtn.textContent = "Copy Text", 1500);
            }} catch (error) {{
                copyBtn.textContent = "Copy failed";
                setTimeout(() => copyBtn.textContent = "Copy Text", 1800);
            }}
        }});
        </script>
        """,
        height=52,
    )


st.set_page_config(page_title="Home | YouTube to Text", page_icon="▶", layout="centered")

st.title("Home")
st.write("Paste a YouTube link, download audio, and transcribe it locally on your server.")
st.caption("Use the Generated Text page from the left sidebar to view saved transcripts only.")

youtube_url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...")
downloads_dir = Path("downloads") / "audio"
transcripts_dir = Path("downloads") / "transcripts"
model_size = st.selectbox("Whisper model size", options=["tiny", "base", "small"], index=1)

deleted_transcripts = cleanup_old_transcripts(transcripts_dir, max_age_hours=24)
if deleted_transcripts > 0:
    st.info(f"Auto-cleanup removed {deleted_transcripts} old local transcript file(s).")

st.caption("Transcript files are kept for 1 day and then deleted automatically.")

if "last_audio_path" not in st.session_state:
    st.session_state.last_audio_path = ""

if youtube_url:
    if is_valid_youtube_url(youtube_url):
        st.success("Valid YouTube URL received.")
        st.code(youtube_url, language="text")

        if st.button("Download Audio"):
            with st.spinner("Downloading audio..."):
                try:
                    saved_file = download_audio(youtube_url, downloads_dir)
                except Exception as exc:
                    st.error(f"Audio download failed: {exc}")
                    if "HTTP Error 403" in str(exc):
                        st.info(
                            "YouTube blocked this server IP/session. This is common on Streamlit Cloud. "
                            "Try redeploying on your own VPS/server, or use a different network/server region."
                        )
                else:
                    st.success("Audio downloaded successfully.")
                    st.write(f"Saved to: {saved_file}")
                    st.session_state.last_audio_path = str(saved_file)
    else:
        st.error("Please enter a valid YouTube URL.")

if st.session_state.last_audio_path:
    audio_file = Path(st.session_state.last_audio_path)
    if not audio_file.exists():
        st.warning("Previously downloaded audio was not found. Download again.")
        st.session_state.last_audio_path = ""
    else:
        st.info(f"Ready to transcribe: {audio_file}")

        if st.button("Transcribe Audio"):
            with st.spinner("Transcribing locally with Faster-Whisper..."):
                try:
                    transcript_text, transcript_file = transcribe_audio(
                        audio_file,
                        transcripts_dir,
                        model_size,
                    )
                except Exception as exc:
                    st.error(f"Transcription failed: {exc}")
                else:
                    st.success("Transcription completed.")
                    st.write(f"Transcript file: {transcript_file}")
                    st.subheader("Resulting Text")
                    st.text_area("Result", transcript_text, height=280)
                    render_copy_button(transcript_text, button_id="copy-new-transcript")

                    if delete_audio_file(audio_file):
                        st.info("Source audio file deleted after transcription.")
                    else:
                        st.warning("Transcript saved, but audio file could not be deleted.")

                    st.session_state.last_audio_path = ""

                    st.download_button(
                        label="Download Transcript (.txt)",
                        data=transcript_text,
                        file_name=transcript_file.name,
                        mime="text/plain",
                    )
