"""Unit tests for makewaves.py, using tiny media files built with ffmpeg."""
import shutil, subprocess, sys, wave
from pathlib import Path
import numpy as np
import pytest

from streamsync import makewaves
from streamsync.fileobject import fileobject

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed")

def make_media(path, video=False, rates=(8000,), channels=2, dur=1):
	"""Write a file with an optional video stream and one sine track per entry in rates."""
	cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
	if video:
		cmd += ["-f", "lavfi", "-i", f"testsrc=size=64x48:rate=10:duration={dur}"]
	for k, fs in enumerate(rates):
		cmd += ["-f", "lavfi", "-i", f"sine=f={440 * (k + 1)}:sample_rate={fs}:duration={dur}"]
	for k in range(int(video) + len(rates)):
		cmd += ["-map", str(k)]
	if video:
		cmd += ["-c:v", "mpeg4"]
	if rates:
		cmd += ["-ac", str(channels)]
	cmd += [str(path)]
	subprocess.run(cmd, check=True)
	return fileobject(str(path))

def wav_info(path):
	with wave.open(path, "rb") as w:
		data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
		return w.getnchannels(), w.getsampwidth(), w.getframerate(), data

# --- find_audio_stream ---

def test_find_audio_stream_skips_video(tmp_path):
	f = make_media(tmp_path / "movie.mkv", video=True, rates=(8000, 16000))
	assert makewaves.find_audio_stream(f) == 1

def test_find_audio_stream_no_audio_raises(tmp_path):
	f = make_media(tmp_path / "silent.mkv", video=True, rates=())
	with pytest.raises(ValueError, match="No audio tracks"):
		makewaves.find_audio_stream(f)

# --- create_wav ---

@pytest.mark.parametrize("name", ["clip.wav", "CLIP.WAV"])
def test_create_wav_passes_wav_through(tmp_path, name):
	f = make_media(tmp_path / name)
	out_dir = tmp_path / "out"
	out_dir.mkdir()
	assert makewaves.create_wav(f, str(out_dir)) == f.path
	assert not any(out_dir.iterdir())

def test_create_wav_converts_to_mono_16bit(tmp_path):
	f = make_media(tmp_path / "movie.mkv", video=True, channels=2)
	out = makewaves.create_wav(f, str(tmp_path))
	assert out == str(tmp_path / "movie.wav")
	channels, width, fs, data = wav_info(out)
	assert (channels, width, fs) == (1, 2, 8000)
	assert np.abs(data).max() > 1000

def test_create_wav_uses_first_audio_track(tmp_path):
	# The tracks differ in sample rate, which the conversion keeps
	f = make_media(tmp_path / "movie.mkv", video=True, rates=(16000, 8000))
	_, _, fs, _ = wav_info(makewaves.create_wav(f, str(tmp_path)))
	assert fs == 16000

def test_create_wav_avoids_name_collisions(tmp_path):
	out_dir = tmp_path / "out"
	out_dir.mkdir()
	(tmp_path / "a").mkdir()
	(tmp_path / "b").mkdir()
	first = makewaves.create_wav(make_media(tmp_path / "a" / "movie.mkv"), str(out_dir))
	second = makewaves.create_wav(make_media(tmp_path / "b" / "movie.mp3"), str(out_dir))
	assert first == str(out_dir / "movie.wav")
	assert second == str(out_dir / "movie_1.wav")

def test_create_wav_applies_audio_filter(tmp_path):
	f = make_media(tmp_path / "loud.mkv")
	_, _, _, data = wav_info(makewaves.create_wav(f, str(tmp_path), audio_filter="volume=0"))
	assert np.all(data == 0)

def test_create_wav_ffmpeg_failure_raises(tmp_path):
	f = make_media(tmp_path / "movie.mkv")
	with pytest.raises(RuntimeError, match="ffmpeg failed converting"):
		makewaves.create_wav(f, str(tmp_path), audio_filter="not_a_real_filter")

def test_create_wav_no_audio_raises(tmp_path):
	f = make_media(tmp_path / "silent.mkv", video=True, rates=())
	with pytest.raises(ValueError):
		makewaves.create_wav(f, str(tmp_path))
