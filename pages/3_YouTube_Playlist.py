import shutil
import time
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import streamlit as st
import yt_dlp
from faster_whisper import WhisperModel
from yt_dlp.utils import DownloadError


def load_stt_model(model_size: str) -> WhisperModel:
    """Load and cache a local Faster-Whisper model for CPU inference."""
    if "whisper_model" not in st.session_state:
        st.session_state.whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return st.session_state.whisper_model


def get_playlist_info(playlist_url: str) -> dict:
    """Extract playlist information (title and video URLs) from YouTube playlist URL."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "force_generic_extractor": False,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
            playlist_title = info.get("title", "Untitled Playlist")
            videos = info.get("entries", [])
            video_urls = [f"https://www.youtube.com/watch?v={video['id']}" for video in videos if video]
            return {"title": playlist_title, "urls": video_urls, "error": None}
    except Exception as e:
        return {"title": None, "urls": [], "error": str(e)}


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
        },
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "retries": 5,
        "fragment_retries": 5,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = Path(ydl.prepare_filename(info))
            return file_path
    except DownloadError as exc:
        raise RuntimeError(str(exc)) from exc


def transcribe_audio(audio_path: Path, model_size: str) -> str:
    """Transcribe audio locally and return transcript text."""
    model = load_stt_model(model_size)
    segments, _ = model.transcribe(str(audio_path), beam_size=5)
    transcript_text = " ".join(segment.text.strip() for segment in segments).strip()
    return transcript_text


def get_video_title(url: str) -> str:
    """Extract video title from YouTube URL."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title", "Unknown")
    except:
        return "Unknown"


def sanitize_filename(filename: str) -> str:
    """Remove invalid characters from filename."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "")
    return filename.strip()


def get_playlist_folders() -> list[Path]:
    """Return list of playlist folders in the playlists directory."""
    playlists_dir = Path("playlists")
    if not playlists_dir.exists():
        return []
    return sorted([f for f in playlists_dir.iterdir() if f.is_dir()])


def delete_playlist_folder(folder_path: Path) -> bool:
    """Delete entire playlist folder."""
    try:
        if folder_path.exists() and folder_path.is_dir():
            shutil.rmtree(folder_path)
            return True
    except Exception as e:
        st.error(f"Error deleting folder: {e}")
    return False


def count_transcripts(folder_path: Path) -> int:
    """Count number of transcript files in a folder."""
    if not folder_path.exists():
        return 0
    return len(list(folder_path.glob("*.txt")))


def build_playlist_zip(folder_path: Path) -> bytes:
    """Build an in-memory zip containing all transcript files in playlist folder."""
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zip_file:
        for transcript_file in sorted(folder_path.glob("*.txt")):
            archive_name = f"{folder_path.name}/{transcript_file.name}"
            zip_file.write(transcript_file, archive_name)
    buffer.seek(0)
    return buffer.read()


st.set_page_config(page_title="Playlist Transcriber | YouTube to Text", page_icon="📹", layout="centered")

st.title("📹 YouTube Playlist Transcriber")
st.write("Enter a YouTube playlist URL to download and transcribe all videos automatically.")

# Sidebar configuration
with st.sidebar:
    st.header("⚙️ Settings")
    model_size = st.radio("Whisper Model Size", ["tiny", "base", "small", "medium"], index=1)
    st.caption("Larger models are more accurate but slower.")

# Main content
tab1, tab2 = st.tabs(["Transcribe", "Manage Playlists"])

with tab1:
    st.subheader("Start New Transcription")

    playlist_url = st.text_input(
        "YouTube Playlist URL",
        placeholder="https://www.youtube.com/playlist?list=PLxxx...",
        help="Paste a full YouTube playlist URL"
    )

    if st.button("📥 Load Playlist", use_container_width=True):
        if not playlist_url.strip():
            st.error("Please enter a playlist URL")
        else:
            with st.spinner("Loading playlist information..."):
                result = get_playlist_info(playlist_url)

            if result["error"]:
                st.error(f"Error loading playlist: {result['error']}")
            else:
                st.session_state.playlist_title = result["title"]
                st.session_state.playlist_urls = result["urls"]
                st.session_state.ready_to_transcribe = True
                st.success(f"✓ Loaded {len(result['urls'])} videos from '{result['title']}'")

    # Display loaded playlist info
    if st.session_state.get("ready_to_transcribe"):
        st.markdown("---")
        st.subheader(f"📋 {st.session_state.playlist_title}")
        st.info(f"**{len(st.session_state.playlist_urls)} videos ready to transcribe**")

        if st.button("🚀 Start Transcription", use_container_width=True, type="primary"):
            st.session_state.start_transcription = True

    # Transcription progress
    if st.session_state.get("start_transcription"):
        playlists_dir = Path("playlists")
        playlist_folder_name = sanitize_filename(st.session_state.playlist_title)
        playlist_folder = playlists_dir / playlist_folder_name
        playlist_folder.mkdir(parents=True, exist_ok=True)
        playlist_temp_root = Path("temp_audio") / playlist_folder_name

        progress_bar = st.progress(0)
        status_text = st.empty()
        results_container = st.container()

        total_videos = len(st.session_state.playlist_urls)
        successful = 0
        failed = 0

        with results_container:
            with st.spinner("Processing videos..."):
                for idx, video_url in enumerate(st.session_state.playlist_urls, 1):
                    temp_audio_dir = playlist_temp_root / f"video_{idx}"
                    try:
                        # Get video title
                        status_text.text(f"Fetching video {idx}/{total_videos}...")
                        video_title = get_video_title(video_url)
                        safe_title = sanitize_filename(video_title)

                        # Download audio
                        status_text.text(f"[{idx}/{total_videos}] Downloading: {safe_title[:50]}...")
                        audio_file = download_audio(video_url, temp_audio_dir)

                        # Transcribe audio
                        status_text.text(f"[{idx}/{total_videos}] Transcribing: {safe_title[:50]}...")
                        transcript_text = transcribe_audio(audio_file, model_size)

                        # Save transcript with numbered filename
                        transcript_filename = f"{idx} - {safe_title}.txt"
                        transcript_path = playlist_folder / transcript_filename
                        transcript_path.write_text(transcript_text, encoding="utf-8")

                        successful += 1
                        st.success(f"✓ {transcript_filename}")

                    except Exception as e:
                        failed += 1
                        st.error(f"✗ Video {idx}: {str(e)[:100]}")

                    finally:
                        # Remove per-video temporary audio directory after each run.
                        if temp_audio_dir.exists() and temp_audio_dir.is_dir():
                            shutil.rmtree(temp_audio_dir, ignore_errors=True)

                    # Update progress
                    progress = (idx / total_videos)
                    progress_bar.progress(progress)

        # Final summary
        st.markdown("---")
        st.subheader("📊 Transcription Complete")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Videos", total_videos)
        col2.metric("✓ Successful", successful)
        col3.metric("✗ Failed", failed)

        st.info(f"📁 All transcripts saved to: `playlists/{playlist_folder_name}/`")

        if playlist_temp_root.exists() and playlist_temp_root.is_dir():
            shutil.rmtree(playlist_temp_root, ignore_errors=True)

        # Reset state
        st.session_state.start_transcription = False
        st.session_state.ready_to_transcribe = False

with tab2:
    st.subheader("📂 Manage Saved Playlists")

    playlists = get_playlist_folders()

    if not playlists:
        st.info("No playlists saved yet. Transcribe a playlist to create one!")
    else:
        st.write(f"You have **{len(playlists)}** saved playlist(s)")
        st.markdown("---")

        for playlist_path in playlists:
            col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

            with col1:
                num_transcripts = count_transcripts(playlist_path)
                st.write(f"📁 **{playlist_path.name}**")
                st.caption(f"{num_transcripts} transcripts")

            with col2:
                if st.button("📂 Open", key=f"open_{playlist_path.name}", use_container_width=True):
                    # List files in the folder
                    files = sorted(playlist_path.glob("*.txt"))
                    if files:
                        st.write(f"\n**Transcripts in {playlist_path.name}:**")
                        for file in files:
                            st.write(f"- {file.name}")

            with col3:
                transcripts_count = count_transcripts(playlist_path)
                if transcripts_count > 0:
                    zip_data = build_playlist_zip(playlist_path)
                    st.download_button(
                        "⬇️ ZIP",
                        data=zip_data,
                        file_name=f"{playlist_path.name}.zip",
                        mime="application/zip",
                        key=f"download_{playlist_path.name}",
                        use_container_width=True,
                    )
                else:
                    st.button("⬇️ ZIP", key=f"download_disabled_{playlist_path.name}", disabled=True, use_container_width=True)

            with col4:
                if st.button("🗑️ Delete", key=f"delete_{playlist_path.name}", use_container_width=True):
                    with st.spinner(f"Deleting {playlist_path.name}..."):
                        if delete_playlist_folder(playlist_path):
                            st.success("Playlist folder deleted!")
                            st.rerun()
                        else:
                            st.error("Failed to delete folder")

            st.markdown("---")

# Initialize session state
if "ready_to_transcribe" not in st.session_state:
    st.session_state.ready_to_transcribe = False
if "start_transcription" not in st.session_state:
    st.session_state.start_transcription = False
