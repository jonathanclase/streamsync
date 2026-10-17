import subprocess, json
from .fileobject import fileobject

def audio_streams(in_file: fileobject) -> list[int]:
	"""List the stream indices of all audio tracks in a media file.

	Args:
		in_file: The file to probe.

	Returns:
		The absolute stream indices, in file order. Empty if there are none.

	Raises:
		subprocess.CalledProcessError: If ffprobe fails.
	"""
	result = subprocess.run(
		["ffprobe", "-v", "error", "-select_streams", "a",
		 "-show_entries", "stream=index", "-of", "json", in_file.path],
		capture_output=True, text=True, check=True)
	return [s["index"] for s in json.loads(result.stdout).get("streams", [])]

def float_to_timestamp(secs: float) -> str:
	"""Format a duration in seconds as an "HH:MM:SS" timestamp.

	Returns an output like "00:01:00." Negative values (such as
	a negative offset) get a leading "-". Hours are not wrapped
	at 24 and widen past two digits when needed.

	Args:
		secs: Time in seconds. May be negative.

	Returns:
		The timestamp, e.g. "01:02:03" or "-00:01:00".

	Raises:
		ValueError: If secs is NaN or infinite.
	"""
	if secs != secs or secs in (float('inf'), float('-inf')):
		raise ValueError(f"cannot format {secs} as a timestamp")
	sign = '-' if secs < 0 else ''
	ms = round(abs(secs) * 1000)
	h, ms = divmod(ms, 3_600_000)
	m, ms = divmod(ms, 60_000)
	s, ms = divmod(ms, 1000)
	sign = sign if (h or m or s or ms) else ''  # avoid "-00:00:00.000"
	# return f"{sign}{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
	return f"{sign}{h:02d}:{m:02d}:{s:02d}"
