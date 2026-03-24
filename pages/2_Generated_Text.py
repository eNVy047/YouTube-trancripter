import os
import json
import time
from pathlib import Path

import cloudinary
import cloudinary.uploader
import streamlit as st
import streamlit.components.v1 as components


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


st.set_page_config(page_title="Generated Text", page_icon="📝", layout="centered")

st.title("Generated Text")
st.write("View and copy transcript text files generated by the Home page.")

transcripts_dir = Path("downloads") / "transcripts"
metadata_dir = Path("downloads") / "metadata"

cloudinary_ready = configure_cloudinary()

deleted_transcripts = cleanup_old_transcripts(transcripts_dir, max_age_hours=24)
if deleted_transcripts > 0:
    st.info(f"Auto-cleanup removed {deleted_transcripts} old local transcript file(s).")

if cloudinary_ready:
    deleted_cloud_files = cleanup_cloudinary_transcripts(metadata_dir, retention_hours=24)
    if deleted_cloud_files > 0:
        st.info(f"Auto-cleanup removed {deleted_cloud_files} old Cloudinary transcript file(s).")

st.caption("Transcript files are kept for 1 day and then deleted automatically.")

transcript_files = list_transcript_files(transcripts_dir)

if not transcript_files:
    st.warning("No transcript files available yet.")
else:
    transcript_names = [path.name for path in transcript_files]

    selected_name = st.selectbox(
        "Select transcript file",
        options=transcript_names,
        index=0,
    )

    selected_path = transcripts_dir / selected_name
    if selected_path.exists():
        transcript_text = selected_path.read_text(encoding="utf-8")
        st.subheader("Resulting Text")
        st.text_area("Transcript", transcript_text, height=320)
        render_copy_button(transcript_text, button_id="copy-transcript-page")
        st.download_button(
            label="Download Transcript (.txt)",
            data=transcript_text,
            file_name=selected_path.name,
            mime="text/plain",
        )
