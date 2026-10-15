import numpy as np
from obspy import Trace, UTCDateTime

from rs3d.core.spectro import spectrogram, window_for


def _trace(data: np.ndarray, rate: float = 100.0) -> Trace:
    return Trace(data=data.astype("float64") if not np.ma.isMaskedArray(data) else data,
                 header={"sampling_rate": rate, "starttime": UTCDateTime("2026-10-12T00:00:00"),
                         "network": "AM", "station": "R77A7", "location": "00", "channel": "EHZ"})


def test_sine_peaks_in_its_own_frequency_bin():
    t = np.arange(0, 60, 0.01)
    times, freqs, power = spectrogram(_trace(np.sin(2 * np.pi * 5 * t)), window_s=4.0)
    mean_power = np.nanmean(power, axis=1)
    assert abs(freqs[np.argmax(mean_power)] - 5.0) <= 0.5
    assert freqs[-1] <= 50.0  # Nyquist for 100 Hz
    assert power.shape == (len(freqs), len(times))


def test_times_are_epoch_seconds_of_window_centres():
    t = np.arange(0, 20, 0.01)
    times, _, _ = spectrogram(_trace(np.sin(t)), window_s=4.0)
    start = UTCDateTime("2026-10-12T00:00:00").timestamp
    assert times[0] >= start + 2.0 - 1e-6 and times[-1] <= start + 20.0


def test_masked_gap_gives_nan_columns():
    data = np.sin(2 * np.pi * 5 * np.arange(0, 60, 0.01))
    mask = np.zeros(len(data), bool)
    mask[2000:4000] = True  # 20 s .. 40 s
    _, _, power = spectrogram(_trace(np.ma.masked_array(data, mask=mask)), window_s=4.0)
    assert np.isnan(power).all(axis=0).sum() >= 3
    assert not np.isnan(power[:, 0]).any()


def test_window_grows_with_duration():
    assert window_for(3600) < window_for(86400)
    assert window_for(60) >= 1.0


def test_psd_summary_peaks_at_sine_and_ignores_gap_columns():
    from rs3d.core.spectro import psd_summary
    data = np.sin(2 * np.pi * 5 * np.arange(0, 60, 0.01))
    mask = np.zeros(len(data), bool)
    mask[2000:4000] = True
    _, freqs, power = spectrogram(_trace(np.ma.masked_array(data, mask=mask)), window_s=4.0)
    f, lo, med, hi = psd_summary(freqs, power)
    assert abs(f[np.argmax(med)] - 5.0) <= 0.5
    assert not np.isnan(med).any()
    assert (lo <= med).all() and (med <= hi).all()
    assert f[0] > 0  # DC bin dropped (log axis)


def test_amplitude_spectrum_peak_and_scale():
    from rs3d.core.spectro import amplitude_spectrum
    t = np.arange(0, 120, 0.01)
    freqs, amp = amplitude_spectrum(_trace(1000 * np.sin(2 * np.pi * 5 * t)))
    i = np.argmax(amp)
    assert abs(freqs[i] - 5.0) < 0.05
    assert abs(amp[i] - 1000) / 1000 < 0.05
    assert freqs[0] > 0


def test_amplitude_spectrum_of_tiny_trace_is_empty():
    from rs3d.core.spectro import amplitude_spectrum
    f, a = amplitude_spectrum(_trace(np.ones(5)))
    assert len(f) == 0 and len(a) == 0
