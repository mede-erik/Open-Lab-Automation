# The waveform files of a run

A converter measurement can acquire the waveform of the oscilloscope channels at some of its steps (issues #108 and #113). A whole
acquisition memory is megabytes, so it does **not** go in the run file (JSON Lines): every capture is a **binary file of its own**,
in a folder of the run, and the run file keeps only an index. The measurement file and the run file stay light, and the folder can
be deleted at will: the results stay and still open.

This page is about the **format and the folder** ([`ola/wavefiles.py`](../ola/wavefiles.py), no Qt). Taking the captures during a
measurement is the next step.

## Where

Next to the run file, in a folder named like it: for `runs/eff_20261123_101500_ab12.jsonl` the files are in
`runs/eff_20261123_101500_ab12_waves/`. In the index of the run file the path of each file is **relative** to the folder of the run
file, so a project can be moved.

## One file per capture

A *capture* is the channels of **one oscilloscope** acquired **together**, for **one step** and **one acquisition** (a settings file:
a long view, a rising edge, a falling edge...). The channels of a capture share one trigger and one time base, so they can be drawn
together and compared. The name is `s<step>_<acquisition>_<oscilloscope>.npz`, for example `s00012_rise_scope1.npz`; characters that
a file name does not like become `-`.

With two oscilloscopes, or several acquisitions at one step, there is one file for each.

## The format

A NumPy `.npz` file (readable by any program with NumPy, no pickle), not compressed:

| Array | What |
|---|---|
| `voltage_<channel>` | the samples of a channel, **float32**, in volts at the probe tip as the instrument gave them |
| `time` | the time of each sample (float64, s), **only if the sampling is not regular** (a segmented memory). Otherwise it is `t0 + dt * k`: no array is stored |
| `meta` | a JSON text, below |

`meta` has: `format_version` (1), `step`, `acquisition`, `scope`, `t0` (time of the first sample relative to the trigger, s), `dt`
(sample interval, s), `points`, `forced` (the trigger did not arrive and was forced), `captured_at` (seconds since 1970),
`setpoints` (what the converter was set to at that step), `settings` (what the settings file said) and `channels` (for each channel
the acquisition values of the instrument: vertical gain and offset, trigger delay, timebase...).

Read one with `ola.wavefiles.load_capture(path)`; `Capture.times()` gives the time of every sample. A file made by a newer version of
the program is refused with a message.

## The index in the run file

`index_entry(capture, path, run_path)` is the row that goes in the run file: `file`, `step`, `acquisition`, `scope`, `channels`,
`points`, `dt`, `forced`, `bytes`, and the setpoints of the step. `missing_files(index, run_path)` lists the files that are no
longer there, and `delete_waves(run_path)` deletes the folder.

## How big

`estimate_bytes(points, channels, captures)` is `points x channels x captures x 4`: one million points, two channels, 30 captures
(5 steps, 3 acquisitions, 2 oscilloscopes) are 240 MB. It is meant to be shown **before** a run starts.

## Not done yet

* Taking the captures during a run (the `scope` role, the scope settings file, the step loop): issues #108 and #113.
* Showing the waveforms in the run window and exporting them.
