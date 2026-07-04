import argparse
import sys
import time

import numpy as np

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    print("Missing dependency 'PyAudioWPatch'. Install with:")
    print("    pip install PyAudioWPatch")
    sys.exit(1)

try:
    import mido
except ImportError:
    print("Missing dependency 'mido'/'python-rtmidi'. Install with:")
    print("    pip install mido python-rtmidi")
    sys.exit(1)


# --------------------------------------------------------------------------
# Launchpad Mini MK2 constants
# --------------------------------------------------------------------------
#
# The Launchpad Mini MK2 uses the classic 2-color (red/green) Launchpad
# protocol: plain Note On messages on MIDI channel 1, where the note
# number picks the pad and the velocity encodes color.
#
# Velocity byte layout (bits, LSB first):
#   bits 0-1 : Red brightness   (0-3)
#   bit  2   : Clear   (write 1 to clear the "other" double-buffer copy)
#   bit  3   : Copy    (write 1 to write to both double-buffers)
#   bits 4-5 : Green brightness (0-3)
#
# For simple non-buffered use you always set Clear+Copy, i.e. +12 (0x0C).
#   velocity = 16*Green + Red + 12
# e.g. full red = 3 + 12 = 15, full green = 48 + 12 = 60,
#      full amber (red+green) = 48 + 3 + 12 = 63, off = 0

GRID_SIZE = 8
CHANNEL = 0  # mido channel is 0-indexed; this is MIDI channel 1


def velocity_for(red, green):
    """red, green: 0-3 brightness. Returns the Launchpad velocity byte."""
    red = max(0, min(3, red))
    green = max(0, min(3, green))
    return 16 * green + red + 12


def grid_note(row, col):
    """Map (row, col) -> Launchpad Mini MK2 note number (default XY layout).

    row 0 = bottom row, row 7 = top row
    col 0 = left column, col 7 = right column

    The device's native XY numbering has y=0 as the TOP row, so we flip:
    note = 16 * (7 - row) + col
    If your grid ends up rendering upside down, that's just this flip
    being backwards for your unit -- change the (7 - row) to just row.
    """
    return 16 * (7 - row) + col


def level_meter_row_colors():
    """Return a list of 8 (red, green) brightness tuples (0-3 each), one
    per row, going green (bottom) -> yellow/amber (middle) -> red (top).
    This is the closest 'rainbow-like' gradient achievable on 2-color
    (red/green only) Launchpad Mini MK2 hardware."""
    return [
        (0, 3),  # row 0 (bottom): green
        (1, 3),
        (2, 3),
        (3, 3),  # amber/yellow
        (3, 2),
        (3, 1),
        (3, 0),  # red
        (3, 0),  # row 7 (top): red
    ]


# --------------------------------------------------------------------------
# MIDI output
# --------------------------------------------------------------------------

def find_launchpad_port():
    names = mido.get_output_names()
    for name in names:
        if "launchpad" in name.lower():
            return name
    return None


class Launchpad:
    def __init__(self, port_name):
        self.port = mido.open_output(port_name)
        self.prev_frame = None
        self.clear()

    def clear(self):
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                self.port.send(mido.Message(
                    "note_on", channel=CHANNEL, note=grid_note(row, col), velocity=0))
        self.prev_frame = [[0] * GRID_SIZE for _ in range(GRID_SIZE)]

    def render(self, frame):
        """frame: 2D list [row][col] of velocity bytes (0-127).
        Only sends pixels that changed since the last frame."""
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                v = frame[row][col]
                if v != self.prev_frame[row][col]:
                    self.port.send(mido.Message(
                        "note_on", channel=CHANNEL, note=grid_note(row, col), velocity=v))
        self.prev_frame = frame

    def close(self):
        try:
            self.clear()
        except Exception:
            pass
        self.port.close()

    def test_pattern(self):
        """Light every pad up briefly, one at a time, then show the full
        gradient, so you can visually confirm MIDI is reaching the
        device and the note mapping looks right, independent of audio."""
        print("Running test pattern... watch the grid.")
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                note = grid_note(row, col)
                self.port.send(mido.Message(
                    "note_on", channel=CHANNEL, note=note, velocity=velocity_for(3, 0)))
                time.sleep(0.02)
                self.port.send(mido.Message(
                    "note_on", channel=CHANNEL, note=note, velocity=0))
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                r, g = level_meter_row_colors()[row]
                self.port.send(mido.Message(
                    "note_on", channel=CHANNEL, note=grid_note(row, col),
                    velocity=velocity_for(r, g)))
        print("Full gradient should now be lit (green bottom -> red top).")
        print("Press Ctrl+C to clear and exit.")


# --------------------------------------------------------------------------
# Audio capture + analysis
# --------------------------------------------------------------------------

class AudioAnalyzer:
    def __init__(self, samplerate, chunk, n_bands=GRID_SIZE, smoothing=0.6,
                 gain=1.0, freq_min=40, freq_max=12000):
        self.samplerate = samplerate
        self.chunk = chunk
        self.n_bands = n_bands
        self.smoothing = smoothing
        self.gain = gain
        self.levels = np.zeros(n_bands)
        self.window = np.hanning(chunk)

        # log-spaced band edges from freq_min to freq_max
        edges = np.logspace(np.log10(freq_min), np.log10(freq_max), n_bands + 1)
        freqs = np.fft.rfftfreq(chunk, d=1.0 / samplerate)
        self.bin_ranges = []
        for i in range(n_bands):
            lo = np.searchsorted(freqs, edges[i])
            hi = max(lo + 1, np.searchsorted(freqs, edges[i + 1]))
            self.bin_ranges.append((lo, min(hi, len(freqs))))

    def process(self, samples):
        """samples: mono float32 array of length == self.chunk"""
        windowed = samples * self.window
        spectrum = np.abs(np.fft.rfft(windowed))

        raw = np.zeros(self.n_bands)
        for i, (lo, hi) in enumerate(self.bin_ranges):
            if hi > lo:
                raw[i] = np.mean(spectrum[lo:hi])

        # log compression + gain, then normalize to ~0-1
        raw = np.log1p(raw * self.gain)
        raw = raw / 6.0  # empirical scale so typical music sits in a good range
        raw = np.clip(raw, 0.0, 1.0)

        # smoothing: fast attack, slower decay for a nicer visual falloff
        for i in range(self.n_bands):
            if raw[i] > self.levels[i]:
                self.levels[i] = raw[i]
            else:
                self.levels[i] = self.levels[i] * self.smoothing + raw[i] * (1 - self.smoothing)

        return self.levels.copy()


def list_devices():
    p = pyaudio.PyAudio()
    print("\n=== Audio output (loopback) devices ===")
    try:
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError:
        print("WASAPI not available on this system.")
        p.terminate()
        return
    default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
    print(f"Default output device: {default_speakers['name']}")
    for loopback in p.get_loopback_device_info_generator():
        print(f"  [{loopback['index']}] {loopback['name']}")
    p.terminate()

    print("\n=== MIDI output devices ===")
    for name in mido.get_output_names():
        print(f"  {name}")
    print()


def get_default_loopback_device(p):
    wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
    if not default_speakers.get("isLoopbackDevice", False):
        for loopback in p.get_loopback_device_info_generator():
            if default_speakers["name"] in loopback["name"]:
                return loopback
        raise RuntimeError(
            "Could not find a loopback device matching your default output. "
            "Run with --list-devices to see what's available."
        )
    return default_speakers


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true",
                         help="List audio loopback and MIDI devices, then exit.")
    parser.add_argument("--fps", type=float, default=30.0, help="Target frame rate.")
    parser.add_argument("--gain", type=float, default=1.0,
                         help="Sensitivity multiplier. Raise if bars barely move, "
                              "lower if everything maxes out instantly.")
    parser.add_argument("--smoothing", type=float, default=0.55,
                         help="0-0.95. Higher = smoother/slower decay.")
    parser.add_argument("--brightness", type=float, default=1.0,
                         help="0-1 overall brightness multiplier (there are only "
                              "4 real levels per color on this hardware, so this "
                              "mainly matters for --test/quiet passages).")
    parser.add_argument("--test", action="store_true",
                         help="Run a test pattern on the grid (no audio needed) "
                              "to confirm MIDI wiring/mapping, then exit.")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    port_name = find_launchpad_port()
    if port_name is None:
        print("Could not find a 'Launchpad' MIDI output port.")
        print("Available MIDI outputs:")
        for name in mido.get_output_names():
            print(f"  {name}")
        print("\nMake sure the Launchpad Mini MK2 is plugged in and not exclusively")
        print("claimed by another app (e.g. Ableton Live).")
        sys.exit(1)
    print(f"Using MIDI output: {port_name}")

    row_colors = level_meter_row_colors()

    lp = Launchpad(port_name)

    if args.test:
        try:
            lp.test_pattern()
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            lp.close()
        return

    p = pyaudio.PyAudio()
    try:
        device = get_default_loopback_device(p)
    except RuntimeError as e:
        print(str(e))
        lp.close()
        p.terminate()
        sys.exit(1)

    samplerate = int(device["defaultSampleRate"])
    channels = device["maxInputChannels"]
    chunk = 1024

    print(f"Capturing system audio from: {device['name']}")
    print(f"Sample rate: {samplerate} Hz, channels: {channels}")
    print("Play music/video in any app or browser now. Press Ctrl+C to stop.\n")

    analyzer = AudioAnalyzer(samplerate, chunk, n_bands=GRID_SIZE,
                              smoothing=max(0.0, min(0.95, args.smoothing)),
                              gain=args.gain)

    frame_interval = 1.0 / args.fps
    latest_samples = np.zeros(chunk, dtype=np.float32)

    def audio_callback(in_data, frame_count, time_info, status):
        nonlocal latest_samples
        data = np.frombuffer(in_data, dtype=np.float32)
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
        if len(data) >= chunk:
            latest_samples = data[-chunk:]
        else:
            latest_samples = np.pad(data, (chunk - len(data), 0))
        return (None, pyaudio.paContinue)

    stream = p.open(
        format=pyaudio.paFloat32,
        channels=channels,
        rate=samplerate,
        frames_per_buffer=chunk,
        input=True,
        input_device_index=device["index"],
        stream_callback=audio_callback,
    )
    stream.start_stream()

    try:
        while True:
            t0 = time.time()
            levels = analyzer.process(latest_samples)  # array of 8 values, 0-1

            frame = [[0] * GRID_SIZE for _ in range(GRID_SIZE)]
            for col, level in enumerate(levels):
                height = int(round(level * GRID_SIZE))
                for row in range(height):
                    r, g = row_colors[row]
                    frame[row][col] = velocity_for(r, g)

            lp.render(frame)

            elapsed = time.time() - t0
            time.sleep(max(0.0, frame_interval - elapsed))
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        lp.close()


if __name__ == "__main__":
    main()
