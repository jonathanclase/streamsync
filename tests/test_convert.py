"""Unit tests for convert.py, muxing tiny media files built with ffmpeg."""
import json, shutil, subprocess, sys
from pathlib import Path
import pytest

from streamsync.convert import comm, combine_files
from streamsync.fileobject import fileobject

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed")

def make_media(path, video=False, audio_tracks=1, subtitles=False, dur=2):
	"""Write a file with an optional video stream, audio_tracks sine tracks and an optional subtitle track."""
	cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
	n = 0
	if video:
		cmd += ["-f", "lavfi", "-i", f"testsrc=size=64x48:rate=10:duration={dur}"]
		n += 1
	for k in range(audio_tracks):
		cmd += ["-f", "lavfi", "-i", f"sine=f={440 * (k + 1)}:sample_rate=8000:duration={dur}"]
		n += 1
	if subtitles:
		srt = Path(path).with_suffix(".srt")
		srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
		cmd += ["-i", str(srt)]
		n += 1
	for k in range(n):
		cmd += ["-map", str(k)]
	if video:
		cmd += ["-c:v", "mpeg4"]
	cmd += [str(path)]
	subprocess.run(cmd, check=True)
	return fileobject(str(path))

def probe(path):
	result = subprocess.run(
		["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type,codec_name,start_time:stream_tags=title,language",
		 "-of", "json", str(path)],
		capture_output=True, text=True, check=True)
	return json.loads(result.stdout)["streams"]

# --- comm ---

def test_comm_holds_fields():
	f = fileobject("/x/commentary.mp3")
	c = comm(file=f, offset=-1.25, titletag="Director", titlelang="eng")
	assert (c.file, c.offset, c.titletag, c.titlelang) == (f, -1.25, "Director", "eng")

def test_comm_instances_are_independent():
	a = comm(fileobject("a.mp3"), 1.0, "A", "eng")
	b = comm(fileobject("b.mp3"), 2.0, "B", "fra")
	assert a != b and a.titletag == "A"

# --- combine_files ---

def answer_titles(monkeypatch, comms):
	"""Answer combine_files' title prompts with each commentary's existing titletag, in order."""
	titles = iter([c.titletag for c in comms])
	monkeypatch.setattr("builtins.input", lambda prompt="": next(titles))

@needs_ffmpeg
def test_combine_files_copies_baseline_and_tags_commentary(tmp_path, monkeypatch):
	base = make_media(tmp_path / "movie.mkv", video=True, audio_tracks=2, subtitles=True)
	c = comm(make_media(tmp_path / "comm.mka"), 0.0, "Director commentary", "eng")
	out = tmp_path / "out.mkv"
	answer_titles(monkeypatch, [c])
	combine_files(base.path, [c], str(out))

	before, after = probe(base.path), probe(out)
	# The commentary follows the baseline's audio; subtitles come last
	assert [s["codec_type"] for s in after] == ["video", "audio", "audio", "audio", "subtitle"]
	# Stream copy: the baseline's codecs are unchanged
	assert [s["codec_name"] for s in after[:3] + after[4:]] == [s["codec_name"] for s in before]
	tags = after[3]["tags"]
	assert tags["title"] == "Director commentary"
	assert tags["language"] == "eng"
	# The baseline's own audio keeps its (absent) title
	assert "title" not in after[1].get("tags", {})

@needs_ffmpeg
def test_combine_files_multiple_commentaries_in_order(tmp_path, monkeypatch):
	base = make_media(tmp_path / "movie.mkv", video=True)
	comms = [comm(make_media(tmp_path / "one.mka"), 0.0, "One", "eng"),
			 comm(make_media(tmp_path / "two.mka"), 0.0, "Two", "fra")]
	out = tmp_path / "out.mkv"
	answer_titles(monkeypatch, comms)
	combine_files(base.path, comms, str(out))

	audio = [s for s in probe(out) if s["codec_type"] == "audio"]
	assert [(s["tags"].get("title"), s["tags"]["language"]) for s in audio[1:]] == [("One", "eng"), ("Two", "fra")]

@needs_ffmpeg
def test_combine_files_applies_offset(tmp_path, monkeypatch):
	base = make_media(tmp_path / "movie.mkv", video=True)
	c = comm(make_media(tmp_path / "comm.mka"), 1.5, "Late", "eng")
	out = tmp_path / "out.mkv"
	answer_titles(monkeypatch, [c])
	combine_files(base.path, [c], str(out))

	streams = probe(out)
	assert float(streams[-1]["start_time"]) - float(streams[0]["start_time"]) == pytest.approx(1.5, abs=0.05)

@needs_ffmpeg
def test_combine_files_takes_only_commentary_audio(tmp_path, monkeypatch):
	# A commentary with its own video (like mp3 cover art) adds just its first audio track
	base = make_media(tmp_path / "movie.mkv", video=True)
	c = comm(make_media(tmp_path / "comm.mkv", video=True, audio_tracks=2), 0.0, "C", "eng")
	out = tmp_path / "out.mkv"
	answer_titles(monkeypatch, [c])
	combine_files(base.path, [c], str(out))
	assert [s["codec_type"] for s in probe(out)] == ["video", "audio", "audio"]

@needs_ffmpeg
def test_combine_files_ffmpeg_failure_raises(tmp_path, monkeypatch):
	base = make_media(tmp_path / "movie.mkv", video=True)
	c = comm(make_media(tmp_path / "comm.mka"), 0.0, "C", "eng")
	answer_titles(monkeypatch, [c])
	with pytest.raises(RuntimeError, match="ffmpeg failed muxing"):
		combine_files(base.path, [c], str(tmp_path / "missing_dir" / "out.mkv"))

@needs_ffmpeg
def test_combine_files_missing_baseline_raises(tmp_path, monkeypatch):
	c = comm(make_media(tmp_path / "comm.mka"), 0.0, "C", "eng")
	answer_titles(monkeypatch, [c])
	with pytest.raises(subprocess.CalledProcessError):
		combine_files(str(tmp_path / "nope.mkv"), [c], str(tmp_path / "out.mkv"))
