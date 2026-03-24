import os
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader
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


def read_secret(name: str) -> str:
    """Read a value from environment first, then Streamlit secrets."""
    env_value = os.getenv(name)
    if env_value:
        return env_value

    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except (FileNotFoundError, KeyError):
        pass

    return ""


def configure_cloudinary() -> bool:
    """Configure Cloudinary SDK and return True when credentials are available."""
    cloud_name = read_secret("CLOUDINARY_CLOUD_NAME")
    api_key = read_secret("CLOUDINARY_API_KEY")
    api_secret = read_secret("CLOUDINARY_API_SECRET")

    if not (cloud_name and api_key and api_secret):
        return False

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )
    return True


def tracker_file_path(base_dir: Path) -> Path:
    """Location for Cloudinary transcript retention tracker."""
    return base_dir / "cloudinary_transcript_tracker.json"


def load_tracker(path: Path) -> dict:
    """Load Cloudinary tracker JSON from disk."""
    if not path.exists():
        return {"transcripts": []}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"transcripts": []}


def save_tracker(path: Path, data: dict) -> None:
    """Persist Cloudinary tracker JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def upload_file_to_cloudinary(file_path: Path, folder: str, resource_type: str) -> dict:
    """Upload a file to Cloudinary and return upload response."""
    return cloudinary.uploader.upload(
        str(file_path),
        folder=folder,
        resource_type=resource_type,
        use_filename=True,
        unique_filename=True,
        overwrite=False,
    )


def delete_cloudinary_asset(public_id: str, resource_type: str) -> bool:
    """Delete a Cloudinary asset by public_id and type."""
    try:
        response = cloudinary.uploader.destroy(public_id, resource_type=resource_type)
    except Exception:
        return False

    return response.get("result") in {"ok", "not found"}


def cleanup_cloudinary_transcripts(base_dir: Path, retention_hours: int = 24) -> int:
    """Delete Cloudinary transcript assets older than retention period."""
    tracker_path = tracker_file_path(base_dir)
    tracker = load_tracker(tracker_path)
    now_ts = time.time()
    threshold_ts = now_ts - (retention_hours * 3600)

    kept = []
    deleted_count = 0

    for item in tracker.get("transcripts", []):
        uploaded_at = float(item.get("uploaded_at", 0))
        public_id = item.get("public_id", "")
        resource_type = item.get("resource_type", "raw")

        if not public_id:
            continue

        if uploaded_at < threshold_ts:
            if delete_cloudinary_asset(public_id, resource_type=resource_type):
                deleted_count += 1
            continue

        kept.append(item)

    tracker["transcripts"] = kept
    save_tracker(tracker_path, tracker)
    return deleted_count


def record_cloudinary_transcript(base_dir: Path, public_id: str, resource_type: str) -> None:
    """Record transcript Cloudinary asset for delayed deletion."""
    tracker_path = tracker_file_path(base_dir)
    tracker = load_tracker(tracker_path)
    tracker.setdefault("transcripts", []).append(
        {
            "public_id": public_id,
            "resource_type": resource_type,
            "uploaded_at": time.time(),
        }
    )
    save_tracker(tracker_path, tracker)


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


def list_transcript_files(transcript_dir: Path) -> list[Path]:
    """Return transcript text files sorted by newest first."""
    if not transcript_dir.exists():
        return []

    files = [path for path in transcript_dir.glob("*.txt") if path.is_file()]
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


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
metadata_dir = Path("downloads") / "metadata"
model_size = st.selectbox("Whisper model size", options=["tiny", "base", "small"], index=1)

cloudinary_ready = configure_cloudinary()
if not cloudinary_ready:
    st.warning(
        "Cloudinary credentials are missing. Set CLOUDINARY_CLOUD_NAME, "
        "CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET in environment or Streamlit secrets."
    )

deleted_transcripts = cleanup_old_transcripts(transcripts_dir, max_age_hours=24)
if deleted_transcripts > 0:
    st.info(f"Auto-cleanup removed {deleted_transcripts} old local transcript file(s).")

if cloudinary_ready:
    deleted_cloud_files = cleanup_cloudinary_transcripts(metadata_dir, retention_hours=24)
    if deleted_cloud_files > 0:
        st.info(f"Auto-cleanup removed {deleted_cloud_files} old Cloudinary transcript file(s).")

st.caption("Transcript files are kept for 1 day and then deleted automatically.")

if "last_audio_path" not in st.session_state:
    st.session_state.last_audio_path = ""

if "last_audio_source" not in st.session_state:
    st.session_state.last_audio_source = ""

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
                    st.session_state.last_audio_source = "youtube"
    else:
        st.error("Please enter a valid YouTube URL.")

    if st.session_state.last_audio_path:
        audio_file = Path(st.session_state.last_audio_path)
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

                    if cloudinary_ready:
                        try:
                            audio_upload = upload_file_to_cloudinary(
                                audio_file,
                                folder="youtube_transcriber/audio",
                                resource_type="video",
                            )
                            transcript_upload = upload_file_to_cloudinary(
                                transcript_file,
                                folder="youtube_transcriber/transcripts",
                                resource_type="raw",
                            )

                            audio_public_id = audio_upload.get("public_id", "")
                            transcript_public_id = transcript_upload.get("public_id", "")

                            if audio_public_id:
                                if delete_cloudinary_asset(audio_public_id, resource_type="video"):
                                    st.info("Cloudinary audio file deleted after task completion.")
                                else:
                                    st.warning("Cloudinary audio upload succeeded, but delete failed.")

                            if transcript_public_id:
                                record_cloudinary_transcript(
                                    metadata_dir,
                                    public_id=transcript_public_id,
                                    resource_type="raw",
                                )
                        except Exception as exc:
                            st.warning(f"Cloudinary upload/delete issue: {exc}")

                    if delete_audio_file(audio_file):
                        st.info("Source audio file deleted after transcription.")
                    else:
                        st.warning("Transcript saved, but audio file could not be deleted.")

                    st.session_state.last_audio_path = ""
                    st.session_state.last_audio_source = ""

                    st.download_button(
                        label="Download Transcript (.txt)",
                        data=transcript_text,
                        file_name=transcript_file.name,
                        mime="text/plain",
                    )

st.divider()
st.subheader("Fallback: Upload Audio")
st.caption("Use this when YouTube download is blocked on Streamlit Cloud.")

uploaded_audio = st.file_uploader(
    "Upload audio file",
    type=["mp3", "wav", "m4a", "webm", "aac", "ogg", "flac", "mp4"],
)

if uploaded_audio and st.button("Use Uploaded Audio"):
    try:
        uploaded_path = save_uploaded_audio(uploaded_audio, downloads_dir)
    except Exception as exc:
        st.error(f"Could not save uploaded audio: {exc}")
    else:
        st.success("Uploaded audio is ready.")
        st.write(f"Saved to: {uploaded_path}")
        st.session_state.last_audio_path = str(uploaded_path)
        st.session_state.last_audio_source = "upload"
