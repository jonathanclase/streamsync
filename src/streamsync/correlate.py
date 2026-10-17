import sys, wave
import numpy as np
from . import helpers
from argparse import ArgumentParser, ArgumentTypeError
from scipy.signal import resample_poly, correlate, find_peaks
from scipy.stats import theilslopes
from .syncresult import CoarsePeak, Segment, SyncResult, Window

ENV_FS = 400			# envelope rate (Hz) for the coarse search

def open_wav(path):
	w = wave.open(path, 'rb')
	if w.getsampwidth() != 2:
		w.close()
		raise ValueError(f"{path}: expected 16-bit samples, got {8 * w.getsampwidth()}-bit")
	return w

def read_channel(w, n_frames, channel):
	data = np.frombuffer(w.readframes(n_frames), dtype=np.int16).reshape(-1, w.getnchannels())
	return data[:, channel].astype(np.float64)

def envelope(path, channel=0):
	"""RMS envelope at ENV_FS Hz, built chunk by chunk. Returns (env, sample rate, frame count)."""
	CHUNK_S = 30		# seconds of audio read at a time
	with open_wav(path) as w:
		fs, n = w.getframerate(), w.getnframes()
		n_env = n * ENV_FS // fs
		# Block k covers frames bounds[k]:bounds[k+1]; rounding keeps the average rate exact for any fs
		bounds = np.round(np.arange(n_env + 1) * (fs / ENV_FS)).astype(np.int64)
		env = np.empty(n_env)
		per_chunk = CHUNK_S * ENV_FS
		try:
			for k0 in range(0, n_env, per_chunk):
				k1 = min(k0 + per_chunk, n_env)
				b = bounds[k0:k1 + 1]
				w.setpos(int(b[0]))
				x = read_channel(w, int(b[-1] - b[0]), channel)
				x -= x.mean()
				# Empty blocks (fs below ENV_FS) would divide by zero
				with np.errstate(divide='raise', invalid='raise'):
					env[k0:k1] = np.sqrt(np.add.reduceat(x * x, b[:-1] - b[0]) / np.diff(b))
		except FloatingPointError:
			raise ValueError(f"{path}: sample rate {fs} Hz is below the {ENV_FS} Hz envelope rate") from None
		except (ValueError, IndexError):
			raise ValueError(f"{path}: holds fewer frames than its header claims; the file may be truncated") from None
	return env, fs, n

def read_segment(path, t0, dur, fs_out, channel=0):
	"""Full-rate audio for [t0, t0 + dur) s, zero-padded outside the file and resampled to fs_out.
	Returns (samples, actual start time)."""
	with open_wav(path) as w:
		fs, n = w.getframerate(), w.getnframes()
		i0 = round(t0 * fs)
		i1 = i0 + round(dur * fs)
		j0, j1 = max(i0, 0), min(i1, n)
		x = np.zeros(i1 - i0)
		if j1 > j0:
			w.setpos(j0)
			x[j0 - i0:j1 - i0] = read_channel(w, j1 - j0, channel)
	if fs != fs_out:
		g = np.gcd(fs, fs_out)
		x = resample_poly(x, fs_out // g, fs // g)
	return x, i0 / fs

def normalize(x):
	x = x - x.mean()
	sd = x.std()
	return x / sd if sd > 0 else x

def lag_peaks(a, c, n=5, min_sep=ENV_FS):
	"""The n strongest lags L (samples) of sum a[n+L] c[n], at least min_sep apart, best first.
	Returns [(L, strength, z)]: strength is the correlation over the shorter input (~1 for a perfect
	match of normalized inputs), z its height above the median in robust standard deviations."""
	xc = correlate(a, c, mode='full', method='fft')
	med = np.median(xc)
	noise = 1.4826 * np.median(np.abs(xc - med)) or 1.0
	best = int(np.argmax(xc))			# find_peaks skips the ends, so the global maximum is added by hand
	idx, _ = find_peaks(xc, distance=min_sep)
	idx = idx[np.abs(idx - best) >= min_sep]
	idx = [best] + list(idx[np.argsort(xc[idx])[::-1][:n - 1]])
	scale = min(len(a), len(c))
	return [(int(i) - (len(c) - 1), float(xc[i] / scale), float((xc[i] - med) / noise)) for i in idx]

def global_lag(a, c):
	"""Lag L (samples) maximising sum a[n+L] c[n], i.e. c[n] lines up with a[n+L]."""
	return lag_peaks(a, c, 1)[0][0]

def refine(ref_path, other_path, t_ref, dur, coarse_shift, fs):
	"""Sample-accurate shift for `dur` s of reference centred on t_ref, searching ±FINE_SEARCH_S
	around coarse_shift. Returns (shift s, signed peak)."""
	FINE_SEARCH_S = 0.5		# must cover any clock drift
	a, a_t0 = read_segment(ref_path, t_ref - dur / 2, dur, fs)
	c, c_t0 = read_segment(other_path, a_t0 - coarse_shift - FINE_SEARCH_S, dur + 2 * FINE_SEARCH_S, fs)
	a, c = normalize(a), normalize(c)
	x = correlate(c, a, mode='valid', method='fft') / len(a)
	k = np.argmax(np.abs(x))
	return a_t0 - (c_t0 + k / fs), x[k]

def find_offset(ref_path, other_path, ref_env=None):
	"""Offset between two recordings, overall and per matched window. Returns a SyncResult.
	ref_env: the result of envelope(ref_path), to reuse when aligning several files to one reference."""
	N_WINDOWS = 40			# target number of windows for the per-window estimates
	MIN_WINDOW_S = 2.0		# ...but never shorter than this
	FINE_S = 10.0			# at most this much full-rate audio (centre of each window) is correlated
	MIN_PEAK = 0.15			# windows with a weaker full-rate correlation peak are ignored
	SHIFT_TOL = 0.002		# windows within this of the fitted trend count as matched

	a_env, fs, n_a = ref_env if ref_env is not None else envelope(ref_path)
	c_env, _, _ = envelope(other_path)
	peaks = [CoarsePeak(lag / ENV_FS, s, z) for lag, s, z in lag_peaks(normalize(a_env), normalize(c_env))]
	coarse = peaks[0].offset

	W = max(MIN_WINDOW_S, n_a / fs / N_WINDOWS)
	n_win = int(n_a / fs // W)
	t_mid = (np.arange(n_win) + 0.5) * W
	fine_len = min(W, FINE_S)
	fine = np.empty(n_win)
	fine_peak = np.empty(n_win)
	for i, t in enumerate(t_mid):
		fine[i], fine_peak[i] = refine(ref_path, other_path, t, fine_len, coarse, fs)

	# Fit a trend through the strong windows, then keep the ones that sit on it
	strong = np.abs(fine_peak) >= MIN_PEAK
	if strong.sum() >= 2:
		slope, icept = theilslopes(fine[strong], t_mid[strong])[:2]
	elif strong.any():
		# A lone strong window is its own trend; the coarse shift (1 / ENV_FS resolution) is too rough to test it against
		slope, icept = 0.0, fine[strong][0]
	else:
		slope, icept = 0.0, coarse
	ok = strong & (np.abs(fine - (icept + slope * t_mid)) <= SHIFT_TOL)

	segments = [Segment(float(t_mid[i] - W / 2), float(t_mid[i] + W / 2), float(fine[i])) for i in np.flatnonzero(ok)]
	offset = float(np.median(fine[ok])) if ok.any() else float(coarse)
	drift_ppm = float(theilslopes(fine[ok], t_mid[ok])[0] * 1e6) if ok.sum() >= 3 else None
	windows = [Window(float(t - W / 2), float(t + W / 2), float(f), float(p), bool(m))
			for t, f, p, m in zip(t_mid, fine, fine_peak, ok)]
	# Expected maximum of this many independent standard normals; envelope samples are correlated, so this errs high
	chance_z = float(np.sqrt(2 * np.log(len(a_env) + len(c_env) - 1)))
	return SyncResult(offset, segments, drift_ppm, peaks, windows, chance_z)

def no_match_reason(result):
	"""Why an unmatched result has no trustworthy offset, as one line."""
	reasons = ["no window confirmed the coarse offset"]
	need = result.SIGNIFICANT_FACTOR * result.coarse_chance_z
	if result.coarse_peaks and result.coarse_peaks[0].z < need:
		reasons.append(f"the best coarse peak (z {result.coarse_peaks[0].z:.1f}) is not clearly above chance (needs z {need:.1f})")
	if result.coarse_ambiguous:
		reasons.append("the coarse peaks are ambiguous")
	return f"No match: {'; '.join(reasons)} (unverified guess {result.offset:+.3f} s)"

def coarse_only_note(result):
	"""Caveat for a match that rests on the coarse peak alone, or None for a full-rate match."""
	if result.fine_matched:
		return None
	return f"Coarse estimate (±{1000 / ENV_FS:.1f} ms): the loudness matches but no window confirmed it at full rate"

def print_diagnostics(result):
	"""Print the coarse peaks and every window's fine result, for judging a doubtful offset."""
	print(f"\tCoarse peaks (envelope correlation; chance alone reaches z {result.coarse_chance_z:.1f}):")
	for p in result.coarse_peaks:
		print(f"\t\tOffset {p.offset:+10.3f} s   strength {p.strength:.3f}   z {p.z:6.1f}")
	print("\tWindows (fine correlation around the first coarse peak):")
	for w in result.windows:
		mark = "matched" if w.matched else ""
		print(f"\t\t{helpers.float_to_timestamp(w.start)} - {helpers.float_to_timestamp(w.stop)}: "
			f"Offset {w.offset:+.3f} s   peak {w.peak:+.3f}   {mark}")

if __name__ == "__main__":

	argparser = ArgumentParser()
	argparser.add_argument('-b', '--baseline', required=True, help="The .wav file representing the baseline (the video stream)")
	argparser.add_argument('-s', '--subject', required=True, action="append", help="The .wav file used for the comparison (the comment stream[s])")
	argparser.add_argument('-v', '--verbose', action="store_true", help="Also print the coarse peaks and every window's fine result")
	args = argparser.parse_args()

	baseline = args.baseline
	subjects = args.subject

	# baseline = "/path"
	# subjects = ["/paths"]

	try:
		baseline_env = envelope(baseline)
	except (OSError, wave.Error, ValueError) as e:
		sys.exit(f"Baseline: {e}")

	print(f"Baseline: {baseline}")
	for subj in subjects:
		print(f"{subj}:")
		try:
			result = find_offset(baseline, subj, baseline_env)
		except (OSError, wave.Error, ValueError) as e:
			print(f"\tError: {e}", file=sys.stderr)
			continue
		if not result.matched:
			print(f"\t{no_match_reason(result)}")
			if args.verbose:
				print_diagnostics(result)
			continue
		print(f"\tOffset: {result.offset:+.5f} s")
		if note := coarse_only_note(result):
			print(f"\t{note}")
		if result.drift_ppm is not None:
			print(f"\tDrift: {result.drift_ppm:+.1f} ppm")
		for s in result.segments:
			print(f"\t\t{helpers.float_to_timestamp(s.start)} - {helpers.float_to_timestamp(s.stop)}: Offset {s.offset:+.3f} s")
		if args.verbose:
			print_diagnostics(result)
