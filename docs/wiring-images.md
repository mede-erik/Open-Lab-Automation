# Wiring diagram images: what to draw

List of the images that the modules look for. There are **19**. Each image is optional: while it is missing, the wiring
window shows the diagram drawn by the program; as soon as you put the file with the right name, your drawing appears.
You can make them one at a time, in any order.

How it works is explained in [`wiring.md`](wiring.md). Here there is only the work list.

## The placeholders

In every module folder there is **already a placeholder file** for each image (17 grey, dashed `.svg` files, with
the name written on them, when it is seen and what to draw). They serve to know **which file to replace** and where it is.

* The program **ignores the placeholders**: until you replace them, the wiring window keeps showing
  the diagram drawn by the program. A placeholder is recognised because it contains the tag `OLA-PLACEHOLDER`.
* **To replace one**: save your drawing **with the same name** over the file (`filter.svg`), or put it next to it
  with another extension (`filter.png`: the `.svg` placeholder is skipped).
* To recreate the missing placeholders (for example after adding an image to this list) and to see where you are:

```bash
python scripts/make_picture_placeholders.py --check
python scripts/make_picture_placeholders.py
```

The first says, for each image, whether it is your drawing (`drawn`), a placeholder (`placeholder`) or missing; the
second writes the missing placeholders and **never overwrites a real drawing**. The list is read from this file.

## Where to put the files and what they are called

* **Folder**: the module's folder, next to `wiring.json` (`ola/modules/<module>/`). Each image below says
  its folder.
* **Name**: exactly the one indicated, in lowercase, **without spaces**. The extension can be `.svg` (recommended),
  `.png`, `.jpg` or `.webp`. Example: `ola/modules/filter/filter.svg`.
* **Languages**: if the drawing has **no words**, one file is enough. If it has words, make one file per language with the
  suffix after the name: `filter_it.svg`, `filter_en.svg`, `filter_fr.svg`, `filter_es.svg`, `filter_de.svg`. The
  program uses the file of the application's language and, if it is missing, the English one (`_en`). If you only make the drawings with words
  in one language, name them with the right suffix and the rest keeps the program's drawing.
  **Advice**: drawings without words (only symbols, colours and arrows), because the numbered list under the image already
  says things in words and in the right language. At most very short labels, the same in all languages (`P1`, `P2`,
  `CH1`, `+`, `-`, `GND`).

## Common rules (valid for all)

| What | Indication |
|---|---|
| Format | **SVG** (stays sharp at any size). If PNG: at least **1500 px wide** |
| Proportions | **Landscape**, about 2:1 or 16:9 (for example 1600 x 800). Not taller than wide |
| Background | White or transparent. The window shows it on white even with the dark theme |
| Margins | Some white around (about 5 %): nothing touching the edge |
| Style | Always the same in all images: same symbols for the instruments, same way of drawing the connectors |
| Line weight | Lines thick enough to be read when the window is narrow (imagine the image 600 px wide) |
| Colours | Few. Proposal: **black** = signal / coaxial cable, **red** = positive / power supply, **blue** = negative / ground, **green** = the device under test (DUT) highlighted. If you use colours, do not rely only on them: the DUT must also be **drawn differently** (double or dashed frame) |
| Instruments | Draw them as you recognise them: the VNA as an instrument with the ports on the side, the oscilloscope with its screen, etc. A box with an icon is fine |
| Connectors | The **numbered ports** of the VNAs (P1, P2) and the **channels** of the oscilloscope (CH1) visible, with the number |
| DUT | Always clearly distinguishable from the instruments (colour, double frame or shadow) |
| Cables | The test cable is a thick stroke with the connectors at the ends. If it is a cable being measured, draw it differently (longer, wavy) so it is not confused with the test leads |

Each image must show **at a glance** where each wire goes from and to, without reading the list.

## Before you start: how to try it

After putting the file in the module's folder, to see it without starting any measurement:

```bash
python -m frontend.ui.WiringDialog filter
```

(replace `filter` with the module name). For the measurement with different parameters (e.g. the amplifier **with** an attenuator),
also give a measurement file and the language: `python -m frontend.ui.WiringDialog amplifier my_measurement.amp it`.

---

# The 19 images

Each card says: **file**, **folder**, **when it is shown**, **what to draw** and the **details that must be there**.

## 1. Cable, transmission

* **File**: `cable_transmission`
* **Folder**: `ola/modules/cable/`
* **When it is seen**: cable measurement in transmission (the normal case, loss between the two ports).
* **What to draw**: the **VNA** on the left with **P1 and P2** on the right side (or on the sides). The **cable under test** in the middle,
  drawn clearly visible and **folded or wavy** to show that it is the device under test (DUT).
  One end of the cable goes to **P1**, the other to **P2**, each with a **short test lead** (the test leads are
  those used for the calibration).
* **Details**: the two test leads **identical** and short; the two ends of the cable labelled **A** and **B** (A on P1,
  B on P2); a small mark showing the **calibration planes** (the two ends of the test leads, where the cable under test
  is attached).

## 2. Cable, reflection with open end

* **File**: `cable_reflection_open`
* **Folder**: `ola/modules/cable/`
* **When it is seen**: measurement in reflection, with the far end **open** (the default case of reflection).
* **What to draw**: the VNA with only **P1** connected. The cable under test starts from P1 (through the test lead) and
  **ends in the air**: the connector at the other end is **left free**, with a **open-circuit symbol**
  (broken line) or the word **OPEN**.
* **Details**: **P2 empty** (not connected, perhaps with a cap or simply without a wire); the far end clearly
  visible, because that is where the user must take care not to connect anything.

## 3. Cable, reflection with short-circuited end

* **File**: `cable_reflection_short`
* **Folder**: `ola/modules/cable/`
* **When it is seen**: measurement in reflection with the far end **short-circuited**.
* **What to draw**: like image 2, but the far connector has a **short circuit** (a short cap, or the
  short symbol: the two contacts joined), with the word **SHORT**.
* **Details**: **make images 2 and 3 with the same setup**, so that it is seen that only the far end changes.

## 4. Return loss

* **File**: `return_loss`
* **Folder**: `ola/modules/return_loss/`
* **When it is seen**: return loss / VSWR measurement of a device (an input, an adapter, a connector).
* **What to draw**: the VNA with **P1** connected, through a **test lead**, to the **connector of the device under
  test**. The device is a generic box (the DUT) with a single connector.
* **Details**: **P2 not used**; mark the **calibration plane** (the end of the test lead) with a
  dashed vertical line or a mark, because the calibration is done there (open / short / load).

## 5. Antenna

* **File**: `antenna`
* **Folder**: `ola/modules/antenna/`
* **When it is seen**: measurement of the impedance and return loss of an antenna.
* **What to draw**: the VNA with **P1** connected, with a test lead, to the **antenna connector** (draw
  a recognisable antenna: whip, patch or panel).
* **Details**: the antenna **far from metal objects and people**: you can draw a free area around
  the antenna, with a small **no-entry sign on the metal** or simply empty space and an arrow showing
  the distance. The antenna must be in its **position of use** (if it is to be mounted on a roof, in the image it is on
  a support, not resting on the table).

## 6. Filter

* **File**: `filter`
* **Folder**: `ola/modules/filter/`
* **When it is seen**: measurement of the response of a filter (low-pass, high-pass, band-pass, band-stop).
* **What to draw**: the VNA with **P1 and P2**; the **filter** in the middle, with the **input** connected to **P1** and the **output**
  connected to **P2**, each with a test lead.
* **Details**: the filter's **input (IN)** and **output (OUT)** clearly indicated (the filter is a directional device:
  the user must know which side goes to P1). The filter symbol can be the classic box with the curve
  (do not choose the type: it applies to all four).

## 7. Attenuator

* **File**: `attenuator`
* **Folder**: `ola/modules/attenuator/`
* **When it is seen**: measurement of an attenuator (fixed, or a step of a stepped one).
* **What to draw**: like the filter, but with the **symbol of an attenuator** (the box with the diagonal bar or the
  resistor "T / pi" network): **P1** at the input, **P2** at the output, with the test leads.
* **Details**: **do not overdo the colours**: it is a simple thing, two wires and the device. If you make the filter
  image first, this one will be almost the same: that is fine (only the symbol changes).

## 8. Amplifier, direct connection

* **File**: `amplifier`
* **Folder**: `ola/modules/amplifier/`
* **When it is seen**: measurement of the amplifier **without** an input attenuator.
* **What to draw**: the VNA with **P1 and P2**; the **amplifier** in the middle with **IN** connected to **P1** and **OUT**
  connected to **P2**; in addition the **power supply of the amplifier** (a power supply or a battery drawn separately,
  with **+ in red** and **− in blue**) going to its **supply pins**.
* **Details**: the **power supply clearly visible**, because the amplifier **does not work** without it; a **warning
  symbol** (triangle) or a **MAX IN** label on the VNA input connected to the amplifier output, to
  remind the user to check the maximum power.

## 9. Amplifier with an input attenuator

* **File**: `amplifier_with_attenuator`
* **Folder**: `ola/modules/amplifier/`
* **When it is seen**: when the measurement file has `input_attenuation_db` (an attenuator in front of the amplifier).
* **What to draw**: like image 8, but between **P1** and the amplifier input there is the **attenuator**:
  P1 → attenuator → IN of the amplifier. The output of the amplifier goes, as before, to **P2**.
* **Details**: the attenuator with the **symbol of image 7**; write **"dB"** (without a number: the value depends on the
  file) or leave it empty. The attenuator must be **included in the calibration** (a hint: the calibration plane
  is after it, or a line that contains it).

## 10. Ripple and noise, probe only

* **File**: `ripple`
* **Folder**: `ola/modules/ripple/`
* **When it is seen**: ripple measurement **without** an electronic load (the power supply already has its load).
* **What to draw**: the **power supply (or the board) under test** with its **output** (+ and −) and the **output capacitor**
  drawn. An **oscilloscope probe** with the **tip on +** and the **ground spring on −**, **both very close
  to the capacitor**; the probe goes to **CH1** of the oscilloscope.
* **Details**: **the ground spring must be visible**, next to the tip (it is the most important detail of
  this measurement: a long ground lead shows false peaks). Better an **enlargement** (a circle with zoom) on the
  probe point on the capacitor. Add the words **20 MHz** (bandwidth limit) near the oscilloscope.

## 11. Ripple and noise, with load

* **File**: `ripple_with_load`
* **Folder**: `ola/modules/ripple/`
* **When it is seen**: when the measurement file has the **load currents** (`conditions`): the program switches on the
  electronic load.
* **What to draw**: like image 10, but with in addition the **electronic load**, connected to the output of the power supply
  (**+ to +**, **− to −**) with **short, thick cables**.
* **Details**: the **load cables** drawn **thick** and different from the probe, so that they are not confused; **the probe stays
  on the capacitor**, not on the load.

## 12. Efficiency

* **File**: `efficiency`
* **Folder**: `ola/modules/efficiency/`
* **When it is seen**: efficiency measurement (input, output, load, datalogger). One image for all cases,
  therefore **generic**.
* **What to draw**: from left to right: the **input power supply**, the **converter under test**, the **electronic load**. Between the power supply and the converter a **shunt** in series on the positive (to measure the input
  current). The **datalogger** below, with three wires going to: **the input voltage** (upstream of the shunt,
  near the converter input), **the shunt ends** (input current) and **the output voltage** (at the load terminals or at the converter output).
* **Details**: short labels, the same in all languages: **VIN**, **IIN**, **VOUT**, **GND**; **do not write
  the datalogger channel numbers**: they change from one file to another (the numbered list, written from the file, gives them).
  An **auxiliary power supply** (for the control of the converter) drawn **dashed**, because it is not
  always there.

## 13. Line and load regulation

* **File**: `regulation`
* **Folder**: `ola/modules/regulation/`
* **When it is seen**: line and load regulation measurement of a converter (one image for all cases).
* **What to draw**: from left to right: the **power supply** (with **+ in red** and **− in blue**) going to the **input**
  of the **converter under test**; the **output** of the converter goes to the **electronic load** (**short and thick** cables) and,
  with **thin** wires, to the **voltmeter** (or to a channel of the **datalogger**).
* **Details**: the thin voltmeter wires **attached to the output terminals of the converter**, not at the end of the load
  cables (the drop in the cables is not regulation); if you wish, a **second thin wire** from the voltmeter to the
  **input terminals** (dashed: needed only if the input is also read). Short labels: **VIN**, **VOUT**, **GND**.

## 14. Return loss, device behind a measured cable

* **File**: `return_loss_with_cable`
* **Folder**: `ola/modules/return_loss/`
* **When it is seen**: when the measurement file has the correction for a cable (`correction`): the device is not on the
  VNA but at the end of a cable of which you already have the measurements.
* **What to draw**: like image 4, but between the **test lead** and the device there is the **measured cable**,
  drawn **long and wavy** to distinguish it from the test leads. **P1** goes to the test lead, the lead to the
  **end A of the cable**, the **end B** to the device.
* **Details**: the **calibration plane** drawn at the **end of the test lead, BEFORE the cable** (a
  dashed vertical line with the word CAL): it is the point that changes compared with image 4. The cable is **not** in
  the calibration.

## 15. Antenna behind a measured cable

* **File**: `antenna_with_cable`
* **Folder**: `ola/modules/antenna/`
* **When it is seen**: like 14, but for the antenna measurement.
* **What to draw**: like image 5 (recognisable antenna, far from metal and people), with in between the **measured cable**
  (long and wavy) and the **calibration plane before the cable**, as in 14.
* **Details**: same setup as 14, so that it is seen that only the device changes.

## 16. Filter with accessories (cables or attenuators) on one or two ports

* **File**: `filter_with_fixtures`
* **Folder**: `ola/modules/filter/`
* **When it is seen**: when the measurement file has the correction (`correction`): the filter is not connected directly to the
  VNA but through cables, adapters or attenuators already measured, on one port or on both.
* **What to draw**: like image 6, but between each VNA port and the filter there is an **accessory** (a stretch of **wavy**
  cable or the symbol of an attenuator), on **P1**, on **P2** or on both: draw both, with **P2 dashed** to
  show that it is not always there.
* **Details**: the **calibration plane** at the **end of the test leads, BEFORE the accessories** (dashed vertical line
  with the word CAL); the accessories are **outside** the calibration. IN and OUT of the filter clearly visible.

## 17. Attenuator with accessories on one or two ports

* **File**: `attenuator_with_fixtures`
* **Folder**: `ola/modules/attenuator/`
* **When it is seen**: like 16, for the attenuator measurement.
* **What to draw**: like image 7 (VNA, attenuator in the middle) with the **accessories** on P1 and on P2 (P2 dashed)
  and the calibration plane before the accessories, as in 16.
* **Details**: same setup as 16, so that it is seen that only the device changes.

## 18. Bode plot

* **File**: `bode`
* **Folder**: `ola/modules/bode/`
* **When it is seen**: Bode plot measurement (gain and phase of a circuit) with a function generator and an oscilloscope.
* **What to draw**: from left to right: the **function generator** (with a sine wave on its display), the **circuit under
  test** (a box with the input on the left and the output on the right) and the **oscilloscope**. The generator output goes to the **circuit
  input** and, with a separate wire, to the **reference channel** of the oscilloscope (**CH1**); the **circuit output** goes to the
  second channel (**CH2**).
* **Details**: the **two probes identical**, with a short ground spring; the **input pick-up point close to the circuit** (not
  at the generator output). If you wish, a smaller box showing the **loop gain** case (generator in series with
  the loop through a resistor or an injection transformer, dashed because it is not always there).

## 19. Time domain (TDR): where a fault is along a cable

* **File**: `tdr`
* **Folder**: `ola/modules/tdr/`
* **When it is seen**: time-domain measurement of a line (cable) with the VNA.
* **What to draw**: the VNA with **P1** connected, with a test lead, to the **near end** of a **long cable** (draw it wavy or
  coiled, clearly different from the test lead). At the other end three possibilities, drawn as **three alternative endings** (or one end with
  three symbols side by side): **open** (free connector), **short** (short cap), **device** (a box, for example an antenna).
* **Details**: on the cable a **fault point** (a crush, a connector) with an arrow and the letter **d**, and a **dimension line** that
  goes from the calibration plane (the end of the test lead, dashed with CAL) to that point: the distance is measured from there.

---

# Checklist

Tick off as you go. The file goes in the indicated folder.

- [ ] 1. `cable_transmission` — `ola/modules/cable/`
- [ ] 2. `cable_reflection_open` — `ola/modules/cable/`
- [ ] 3. `cable_reflection_short` — `ola/modules/cable/`
- [ ] 4. `return_loss` — `ola/modules/return_loss/`
- [ ] 5. `antenna` — `ola/modules/antenna/`
- [ ] 6. `filter` — `ola/modules/filter/`
- [ ] 7. `attenuator` — `ola/modules/attenuator/`
- [ ] 8. `amplifier` — `ola/modules/amplifier/`
- [ ] 9. `amplifier_with_attenuator` — `ola/modules/amplifier/`
- [ ] 10. `ripple` — `ola/modules/ripple/`
- [ ] 11. `ripple_with_load` — `ola/modules/ripple/`
- [ ] 12. `efficiency` — `ola/modules/efficiency/`
- [ ] 13. `regulation` — `ola/modules/regulation/`
- [ ] 14. `return_loss_with_cable` — `ola/modules/return_loss/`
- [ ] 15. `antenna_with_cable` — `ola/modules/antenna/`
- [ ] 16. `filter_with_fixtures` — `ola/modules/filter/`
- [ ] 17. `attenuator_with_fixtures` — `ola/modules/attenuator/`
- [ ] 18. `bode` — `ola/modules/bode/`
- [ ] 19. `tdr` — `ola/modules/tdr/`

## An idea to do less work

Make **first one basic image for the VNA** (the two ports, the test leads, the calibration-plane line):
it is reused in images 1-9. Only the device in the middle changes.

The **time log** has no image: its connections depend on the file (the numbered list says what to connect).

## When a new measurement needs an image

Every measurement added in the future lists its images in its own `wiring.json`, and this file must be updated
with its card (name, when it is seen, what to draw).
