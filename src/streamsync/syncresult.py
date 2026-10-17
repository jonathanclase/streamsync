"""Result of aligning two recordings: an overall offset, the clock drift and the matched segments behind them."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Segment:
	start: float			# seconds on the reference timeline
	stop: float
	offset: float			# seconds; same convention as SyncResult.offset

@dataclass(frozen=True)
class CoarsePeak:
	offset: float			# seconds; same convention as SyncResult.offset
	strength: float			# envelope correlation, ~1 for identical loudness contours
	z: float				# height above the correlation's noise floor, in robust standard deviations

@dataclass(frozen=True)
class Window:
	start: float			# seconds on the reference timeline
	stop: float
	offset: float			# best fine shift within the search range around the coarse offset
	peak: float				# signed full-rate correlation at that shift
	matched: bool			# strong enough and on the trend, i.e. reported as a Segment

@dataclass(frozen=True)
class SyncResult:
	offset: float			# overall offset: median of the segment offsets (coarse shift if none matched)
	segments: list[Segment]	# matched windows, in time order
	drift_ppm: float | None	# change in offset per second of reference, in ppm; None with fewer than 3 segments
	coarse_peaks: list[CoarsePeak]	# strongest envelope-correlation peaks, best first; the first is the coarse shift
	windows: list[Window]	# every window the fine stage tried, matched or not
	coarse_chance_z: float	# z the best coarse peak would reach from noise alone, given how many lags were searched

	AMBIGUOUS_RATIO = 0.8	# a runner-up coarse peak at least this fraction of the best makes the coarse shift a guess
	SIGNIFICANT_FACTOR = 1.5	# the best coarse peak's z must be this multiple of coarse_chance_z to stand on its own

	@property
	def fine_matched(self) -> bool:
		"""Whether the full-rate audio confirmed the offset in at least one window."""
		return bool(self.segments)

	@property
	def coarse_significant(self) -> bool:
		"""Whether the best coarse peak is clearly above chance and clearly ahead of the runner-up."""
		p = self.coarse_peaks
		return bool(p) and p[0].z >= self.SIGNIFICANT_FACTOR * self.coarse_chance_z and not self.coarse_ambiguous

	@property
	def matched(self) -> bool:
		"""Whether offset is a real alignment: confirmed at full rate, or from a significant coarse peak alone."""
		return self.fine_matched or self.coarse_significant

	@property
	def coarse_ambiguous(self) -> bool:
		"""Whether another coarse peak, at a different offset, is nearly as strong as the best."""
		p = self.coarse_peaks
		return len(p) >= 2 and p[1].strength >= self.AMBIGUOUS_RATIO * p[0].strength
