# Trying the waveforms

A checklist for a first run with a real oscilloscope. Without hardware, make a project with a finished
simulated run and look at it:

```bash
python3 scripts/make_demo_project.py /tmp/demo
python frontend/launcher.py      # Project > Open > /tmp/demo/demo.json
```

In the *Measurements* tab select the run and press **Waveforms...**: steps, acquisitions and channels
on the left, the whole record in the plot (see [`waveform-files.md`](waveform-files.md)).

## Before the start

1. The project has at least one `.was` file (they are all on by default; switch off the ones you do not
   want from the right-click menu of the file) and the efficiency file has `scope_capture` with the
   oscilloscope in the role `scope` (Timing tab, *Waveforms*).
2. The summary under the Waveforms group shows the number of captures and the size. Above about 1 GB
   the window asks before the start.
3. Remote control > the scope settings button: the menu lists the files that are on; applying one only
   sets the oscilloscope, it does not start a measurement.

## During and after the run

* The **Waveforms** tab appears at the first capture. Check that the steps and the acquisitions in the
  list match the table (every *N* steps, or the steps where the condition was true, up to `max`).
* A capture whose trigger did not arrive is marked *forced trigger* under the plot: it is a picture of
  the screen at that moment, not of an event.
* Zoom with the wheel (Ctrl for the voltage), drag, click twice for the cursors A and B: dt and dV are
  written under the plot. Compare with the cursors of the oscilloscope itself on one capture.
* *Export CSV...*: open the file and check the time column and the channels.
* Two oscilloscopes with a channel of the same name: **Align now**, then *Common time axis*; a poor
  match is refused with the reason.

## Record on the Software test status list

When a run works on the real instrument, tick the box in the *Software test status* section of the
README and write the oscilloscope model next to it. A simulated run does not count.

## Old projects

Opening a project of the first format asks first: answering Yes writes `<name>.json.bkp` (a copy of
the original, never overwritten: `.bkp.1`, `.bkp.2`...) and then updates the file; No leaves it as it is.
