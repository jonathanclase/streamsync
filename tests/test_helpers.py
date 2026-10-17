"""Unit tests for helpers.py. audio_streams tests build tiny media files with ffmpeg."""
import math, shutil, subprocess, sys
from pathlib import Path
import pytest

from streamsync import helpers
from streamsync.fileobject import fileobject

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed")

def make_media(path, video=False, audio_tracks=1, dur=1):
	"""Write a file with an optional test-pattern video stream and audio_tracks sine tracks."""
	cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
	if video:
		cmd += ["-f", "lavfi", "-i", f"testsrc=size=64x48:rate=10:duration={dur}"]
	for k in range(audio_tracks):
		cmd += ["-f", "lavfi", "-i", f"sine=f={440 * (k + 1)}:sample_rate=8000:duration={dur}"]
	for k in range(int(video) + audio_tracks):
		cmd += ["-map", str(k)]
	if video:
		cmd += ["-c:v", "mpeg4"]
	cmd += [str(path)]
	subprocess.run(cmd, check=True)
	return fileobject(str(path))

# --- audio_streams ---

@needs_ffmpeg
def test_audio_streams_lists_every_audio_index(tmp_path):
	f = make_media(tmp_path / "movie.mkv", video=True, audio_tracks=2)
	assert helpers.audio_streams(f) == [1, 2]

@needs_ffmpeg
def test_audio_streams_audio_only_file(tmp_path):
	f = make_media(tmp_path / "audio.wav", audio_tracks=1)
	assert helpers.audio_streams(f) == [0]

@needs_ffmpeg
def test_audio_streams_empty_without_audio(tmp_path):
	f = make_media(tmp_path / "silent.mkv", video=True, audio_tracks=0)
	assert helpers.audio_streams(f) == []

@needs_ffmpeg
def test_audio_streams_missing_file_raises(tmp_path):
	with pytest.raises(subprocess.CalledProcessError):
		helpers.audio_streams(fileobject(str(tmp_path / "nope.mkv")))

# --- float_to_timestamp ---

@pytest.mark.parametrize("secs, expected", [
	(0, "00:00:00"),
	(1.2, "00:00:01"),
	(59, "00:00:59"),
	(61, "00:01:01"),
	(3723.456, "01:02:03"),
	(86400, "24:00:00"),		# hours do not wrap at 24
	(360000, "100:00:00"),		# ...and widen past two digits
])
def test_float_to_timestamp_formats(secs, expected):
	assert helpers.float_to_timestamp(secs) == expected

def test_float_to_timestamp_carries_rounding():
	# Rounds to the millisecond first, so this carries into the minutes instead of showing 60 seconds
	assert helpers.float_to_timestamp(59.9996) == "00:01:00"

def test_float_to_timestamp_negative():
	assert helpers.float_to_timestamp(-3723) == "-01:02:03"

def test_float_to_timestamp_negative_zero_has_no_sign():
	assert helpers.float_to_timestamp(-0.0001) == "00:00:00"

@pytest.mark.parametrize("secs", [math.nan, math.inf, -math.inf])
def test_float_to_timestamp_rejects_non_finite(secs):
	with pytest.raises(ValueError):
		helpers.float_to_timestamp(secs)
