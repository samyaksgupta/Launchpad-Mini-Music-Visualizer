# Linear Spectrum Music Visualizer — Launchpad Mini MK2

Turns your Launchpad Mini MK2's 8x8 grid into a spectrum visualizer that
reacts to **any audio playing on your Windows PC** — any browser tab,
YouTube, Spotify, a game, anything going through your default
speakers/headphones. No special routing needed: it uses WASAPI loopback
to "listen in" on your default output device.

- Columns = 8 frequency bands, bass on the left, treble on the right
- Rows = green (bottom) → yellow/amber (middle) → red (top)
- Louder = the column fills further up

**Note on color:** the "Launchpad Mini MK2" pads are 2-color (red +
green) LEDs, not full RGB — that's a hardware limit of this specific
model (the larger, non-"Mini" "Launchpad MK2" is the RGB one). True
rainbow hues like blue/purple/cyan aren't physically possible here, so
this uses the classic green→amber→red gradient instead, which is the
standard "VU meter" look and the closest thing to a rainbow this
hardware can actually display.

## 1. Install Python packages

Open a terminal (PowerShell or CMD) in this folder and run:

```
pip install -r requirements.txt
```

`python-rtmidi` and `PyAudioWPatch` both ship prebuilt Windows wheels, so
this should just work without needing to install any compiler/build tools.

## 2. Plug in the Launchpad

Connect your Launchpad Mini MK2 via USB. It's class-compliant, so Windows
needs no extra driver. Close any other software that might be holding on
to it (Ableton Live, the Novation Components app, etc.) — only one program
can talk to a MIDI device's output at a time.

## 3. Confirm the grid lights up at all (recommended first step)

```
python launchpad_visualizer.py --test
```

This runs through every pad individually, then leaves the full gradient
lit. If you see nothing here, the problem is MIDI wiring, not audio —
double check the port name printed matches your device and that nothing
else (Ableton, Novation Components, etc.) is holding it open.

## 4. Run it

```
python launchpad_visualizer.py
```

Then just play something — a YouTube video, Spotify, a game — through your
normal speakers/headphones and the grid should start reacting.

To sanity-check what the script sees before running it:

```
python launchpad_visualizer.py --list-devices
```

This prints the detected loopback audio device and all MIDI output ports,
so you can confirm "Launchpad" shows up.

## 4. Tuning it

- `--gain 1.5` — turn this up if the grid barely reacts to quiet audio,
  down if everything instantly maxes out.
- `--smoothing 0.7` — higher = smoother, slower-falling bars (0–0.95).
- `--brightness 0.6` — dim the LEDs if they're too intense.
- `--fps 40` — frame rate of the visualizer.

Example:

```
python launchpad_visualizer.py --gain 1.8 --smoothing 0.6 --brightness 0.8
```

## Notes / troubleshooting

- **"Could not find a 'Launchpad' MIDI output port"** — check the USB
  connection and that no other app has it open exclusively.
- **Nothing lights up while music plays** — run with `--list-devices` and
  confirm the loopback device matches whatever your system's default
  playback device actually is (Settings → Sound → Output). If you switch
  outputs (e.g. plug in headphones) while the script is running, restart it.
- **Bars feel too twitchy or too laggy** — adjust `--smoothing`.
- The color mapping is computed live from HSV, not the Launchpad's
  built-in 128-color palette, so colors are true rainbow hues rather than
  an approximation.
