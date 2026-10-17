"""Unit tests for correlate.py, using small synthetic WAV files."""
import sys, wave
from pathlib import Path
import numpy as np
import pytest
from scipy.signal import resample_poly

from streamsync import correlate

FS = 8000		# sample rate of the synthetic recordings
DUR = 60		# seconds of reference audio

def write_wav(path, x, fs=FS, channels=1, sampwidth=2):
	"""Write samples (n,) or (n, channels) as a WAV, scaled to fill 16 bits."""
	x = np.asarray(x, dtype=np.float64)
	if x.ndim == 1:
		x = np.repeat(x[:, None], channels, axis=1)
	peak = np.abs(x).max()
	if sampwidth == 2:
		data = np.round(x / peak * 30000 if peak > 0 else x).astype(np.int16)
	else:
		data = np.round(x / peak * 100 + 128 if peak > 0 else x + 128).astype(np.uint8)
	with wave.open(str(path), 'wb') as w:
		w.setnchannels(x.shape[1])
		w.setsampwidth(sampwidth)
		w.setframerate(fs)
		w.writeframes(data.tobytes())
	return str(path)

def bursty_noise(n, seed):
	"""Noise with a loudness envelope that changes every 0.25 s, so the coarse search has structure."""
	rng = np.random.default_rng(seed)
	block = FS // 4
	env = np.repeat(rng.random(n // block + 1) ** 3, block)[:n]
	return rng.standard_normal(n) * env

@pytest.fixture
def source():
	"""Long noise signal that references and subjects are cut from."""
	return bursty_noise((DUR + 10) * FS, seed=0)

@pytest.fixture
def ref_path(tmp_path, source):
	return write_wav(tmp_path / "ref.wav", source[:DUR * FS], channels=2)

def subject(tmp_path, source, shift, name="other.wav", noise=0.2):
	"""Subject recording where other[t] = ref[t + shift], i.e. an offset of +shift s."""
	k = round(shift * FS)
	x = source[k:k + (DUR - 5) * FS]
	x = x + noise * x.std() * np.random.default_rng(1).standard_normal(len(x))
	return write_wav(tmp_path / name, x)

# open_wav

def test_open_wav_accepts_16_bit(tmp_path):
	path = write_wav(tmp_path / "a.wav", np.ones(100))
	with correlate.open_wav(path) as w:
		assert w.getsampwidth() == 2

def test_open_wav_rejects_8_bit(tmp_path):
	path = write_wav(tmp_path / "a.wav", np.ones(100), sampwidth=1)
	with pytest.raises(ValueError, match="expected 16-bit"):
		correlate.open_wav(path)

# read_channel

def test_read_channel_picks_one_channel(tmp_path):
	left, right = np.arange(10.0), -np.arange(10.0)
	path = tmp_path / "stereo.wav"
	with wave.open(str(path), 'wb') as w:
		w.setnchannels(2)
		w.setsampwidth(2)
		w.setframerate(FS)
		w.writeframes(np.stack([left, right], axis=1).astype(np.int16).tobytes())
	with correlate.open_wav(str(path)) as w:
		assert np.array_equal(correlate.read_channel(w, 10, 0), left)
		w.setpos(0)
		x = correlate.read_channel(w, 10, 1)
	assert np.array_equal(x, right)
	assert x.dtype == np.float64

# envelope

def test_envelope_rms_and_length(tmp_path):
	t = np.arange(5 * FS) / FS
	# 800 Hz puts exactly two cycles in each 2.5 ms envelope block; a cosine's first sample is its peak
	path = write_wav(tmp_path / "sine.wav", np.cos(2 * np.pi * 800 * t))
	env, fs, n = correlate.envelope(path)
	assert (fs, n) == (FS, 5 * FS)
	assert len(env) == n * correlate.ENV_FS // fs
	# RMS of a full-scale (30000) sine is 30000 / sqrt(2)
	assert np.allclose(env, 30000 / np.sqrt(2), rtol=0.01)

def test_envelope_truncated_file(tmp_path):
	path = write_wav(tmp_path / "full.wav", bursty_noise(5 * FS, seed=2))
	raw = Path(path).read_bytes()
	trunc = tmp_path / "trunc.wav"
	trunc.write_bytes(raw[:len(raw) // 2])		# header still claims every frame
	with pytest.raises(ValueError, match="truncated"):
		correlate.envelope(str(trunc))

def test_envelope_sample_rate_below_env_fs(tmp_path):
	path = write_wav(tmp_path / "low.wav", bursty_noise(300 * 5, seed=3), fs=300)
	with pytest.raises(ValueError, match="below the 400 Hz"):
		correlate.envelope(path)

# read_segment

def test_read_segment_inside_file(tmp_path):
	x = np.arange(FS * 2, dtype=np.float64) % 1000
	path = write_wav(tmp_path / "a.wav", x)
	seg, t0 = correlate.read_segment(path, 0.5, 0.25, FS)
	with correlate.open_wav(path) as w:
		expected = correlate.read_channel(w, FS * 2, 0)[FS // 2:FS // 2 + FS // 4]
	assert t0 == 0.5
	assert np.array_equal(seg, expected)

def test_read_segment_zero_pads_outside_file(tmp_path):
	path = write_wav(tmp_path / "a.wav", np.ones(FS))
	seg, t0 = correlate.read_segment(path, -0.5, 2.0, FS)
	assert t0 == -0.5
	assert len(seg) == 2 * FS
	assert np.all(seg[:FS // 2] == 0) and np.all(seg[FS // 2:FS + FS // 2] != 0) and np.all(seg[FS + FS // 2:] == 0)

def test_read_segment_resamples(tmp_path):
	path = write_wav(tmp_path / "a.wav", bursty_noise(FS, seed=4))
	seg, _ = correlate.read_segment(path, 0.0, 1.0, FS * 2)
	assert len(seg) == FS * 2

# normalize

def test_normalize_zero_mean_unit_std():
	x = correlate.normalize(np.array([1.0, 2.0, 3.0, 10.0]))
	assert np.isclose(x.mean(), 0) and np.isclose(x.std(), 1)

def test_normalize_constant_input():
	assert np.array_equal(correlate.normalize(np.full(5, 7.0)), np.zeros(5))

# global_lag

@pytest.mark.parametrize("lag", [0, 37, -52])
def test_global_lag(lag):
	a = bursty_noise(2000, seed=5)
	c = np.roll(a, -lag)		# c[n] = a[n + lag]
	assert correlate.global_lag(a, c) == lag

# refine

def test_refine_finds_exact_shift_from_rough_guess(tmp_path, source, ref_path):
	other = subject(tmp_path, source, 3.21)
	shift, peak = correlate.refine(ref_path, other, 20.0, 2.0, 3.3, FS)
	assert shift == pytest.approx(3.21, abs=1 / FS)
	assert peak > 0.5

def test_refine_reports_inverted_polarity(tmp_path, source, ref_path):
	k = round(1.5 * FS)
	other = write_wav(tmp_path / "inv.wav", -source[k:k + 50 * FS])
	shift, peak = correlate.refine(ref_path, other, 20.0, 2.0, 1.5, FS)
	assert shift == pytest.approx(1.5, abs=1 / FS)
	assert peak < -0.5

# find_offset

def test_find_offset_constant_shift(tmp_path, source, ref_path):
	result = correlate.find_offset(ref_path, subject(tmp_path, source, 3.21))
	assert result.offset == pytest.approx(3.21, abs=1 / FS)
	assert len(result.segments) > 20
	assert all(s.offset == pytest.approx(3.21, abs=1 / FS) and s.stop > s.start for s in result.segments)
	assert result.drift_ppm == pytest.approx(0, abs=5)
	assert result.fine_matched and result.coarse_significant and correlate.coarse_only_note(result) is None

def test_find_offset_reuses_reference_envelope(tmp_path, source, ref_path):
	other = subject(tmp_path, source, 2.0)
	assert correlate.find_offset(ref_path, other, correlate.envelope(ref_path)) == correlate.find_offset(ref_path, other)

def test_find_offset_measures_drift(tmp_path, source, ref_path):
	k = 2 * FS
	fast = resample_poly(source[k:k + 55 * FS], 2000, 2001)		# runs 500 ppm fast
	result = correlate.find_offset(ref_path, write_wav(tmp_path / "drift.wav", fast))
	assert result.drift_ppm == pytest.approx(500, abs=25)

def test_find_offset_unrelated_recording_falls_back_to_coarse(tmp_path, ref_path):
	other = write_wav(tmp_path / "noise.wav", bursty_noise(50 * FS, seed=9))
	result = correlate.find_offset(ref_path, other)
	assert result.segments == [] and result.drift_ppm is None
	assert not result.matched and not result.coarse_significant
	assert correlate.no_match_reason(result).startswith("No match")

def test_find_offset_matches_on_loudness_alone(tmp_path):
	# Same loudness contour, independent waveforms: the coarse peak is decisive but no window can confirm it
	rng = np.random.default_rng(11)
	block = FS // 4
	n = (DUR + 10) * FS
	env = np.repeat(rng.random(n // block + 1) ** 3, block)[:n]
	ref = write_wav(tmp_path / "ref.wav", rng.standard_normal(n)[:DUR * FS] * env[:DUR * FS])
	k = round(3.21 * FS)
	other = np.random.default_rng(12).standard_normal(n) * env
	result = correlate.find_offset(ref, write_wav(tmp_path / "other.wav", other[k:k + (DUR - 5) * FS]))
	assert not result.fine_matched and result.coarse_significant and result.matched
	assert result.offset == pytest.approx(3.21, abs=2 / correlate.ENV_FS)
	assert correlate.coarse_only_note(result) is not None

def test_find_offset_keeps_lone_strong_window(tmp_path, source, ref_path, monkeypatch):
	# Only reference 30-32 s (one window) appears in the subject, at an offset of +4 s
	other = bursty_noise(DUR * FS, seed=10)
	other[26 * FS:28 * FS] = source[30 * FS:32 * FS]
	path = write_wav(tmp_path / "lone.wav", other)
	# Coarse estimate 2.5 ms off, more than the 2 ms tolerance
	monkeypatch.setattr(correlate, "lag_peaks", lambda a, c: [(round(4.0025 * correlate.ENV_FS), 1.0, 10.0)])
	result = correlate.find_offset(ref_path, path)
	assert [(s.start, s.stop) for s in result.segments] == [(30.0, 32.0)]
	assert result.offset == pytest.approx(4.0, abs=1 / FS)
