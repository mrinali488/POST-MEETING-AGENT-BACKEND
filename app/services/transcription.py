import os, tempfile, subprocess, shlex
from faster_whisper import WhisperModel

def _ffmpeg_resample(src_path: str) -> str:
    """Force 16k mono wav via ffmpeg into a temp file and return its path."""
    tmp_wav = tempfile.NamedTemporaryFile(suffix="_16k.wav", delete=False).name
    cmd = f"ffmpeg -y -hide_banner -loglevel error -i {shlex.quote(src_path)} -ac 1 -ar 16000 {shlex.quote(tmp_wav)}"
    subprocess.run(cmd, shell=True, check=True)
    return tmp_wav

def _run_whisper(model_name: str, wav_path: str) -> str:
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        wav_path,
        vad_filter=True,           
        language="en",
        beam_size=5, best_of=5,    # better decoding
        temperature=0.2,           # allows minor exploration for clarity
        condition_on_previous_text=True
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text

def transcribe(audio_path: str) -> str:
    wav16k = _ffmpeg_resample(audio_path)
    try:
        # Prefer 'small' first (better accuracy); fall back to 'tiny' for speed
        text = _run_whisper("small", wav16k)
        if not text:
            text = _run_whisper("tiny", wav16k)
        if not text:
            raise ValueError("Whisper produced no text.")
        return text
    finally:
        os.remove(wav16k)