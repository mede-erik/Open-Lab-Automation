# Connection diagrams (`wiring.json`)

When a measurement is started the program shows **how to connect the instruments**: a picture (a **drawing made by you**
if the module has one for these parameters, otherwise a diagram drawn by the program), a **numbered list of what to
connect to what** ("Connect channel 101 of daq1 to «vin» of the converter") and the notes that matter before starting
("calibrate the VNA first", "ground spring, not a long ground lead"). *Start* goes on, *Cancel* does not start
anything. The window has a tick, **Show this before each measurement**, that turns it off (the choice is
remembered); the **Connections...** button of the project window shows it at any time, and **Save SVG...** writes the
diagram as a file.

What is drawn follows the parameters of the measurement file: the amplifier shows its input attenuator only if
`input_attenuation_db` is set, the cable shows port 2 or an open / short end depending on its mode, the ripple
measurement shows the electronic load only if it has `conditions`, the channel and the probe ratio come from the file.
Under each instrument box is the name of the instrument the file binds to that role (from the project's `.inst` file).

The diagram is in [`ola/wiring.py`](../ola/wiring.py) (no Qt; tested without a screen), the window is
`frontend/ui/WiringDialog.py`, and each measurement module brings its own `wiring.json`, so the diagram is updated
together with the module. A module without the file simply has no diagram.

## Your own pictures

The list of the pictures to draw, with what each must show, is in [`wiring-images.md`](wiring-images.md) (in Italian).

Draw the pictures you like and drop them **next to the module's `wiring.json`** (`ola/modules/<id>/`): when a picture
with the right name is there it is shown instead of the program's diagram; without it the program's diagram is shown, so
you can add them one at a time. The names each module is already looking for are:

| Module | Picture names (`.svg` preferred; `.png`, `.jpg`, `.webp` also work) |
|---|---|
| `cable` | `cable_transmission` (the cable between the two ports), `cable_reflection_open`, `cable_reflection_short` |
| `return_loss`, `antenna`, `filter`, `attenuator` | `return_loss`, `antenna`, `filter`, `attenuator` |
| `amplifier` | `amplifier` (direct), `amplifier_with_attenuator` (shown when `input_attenuation_db` is set) |
| `ripple` | `ripple` (probe on the output), `ripple_with_load` (shown when the file has `conditions`) |
| `efficiency` | `efficiency` |

Advice: **SVG** stays sharp at any size (a PNG should be at least 1500 pixels wide); a white or transparent
background; the picture is shown as wide as the window allows, keeping its proportions. If the drawing has words, make
one for each language with `_en`, `_it`, `_fr`, `_es`, `_de` after the name (`filter_it.svg`): the file for the
application's language is used, then the English one; a drawing with no words needs only one file. The steps below the
picture are always the program's, in the language of the application.

To try a picture without starting anything: `python -m frontend.ui.WiringDialog filter` (or give a measurement file and a
language: `python -m frontend.ui.WiringDialog amplifier my_amp.amp it`). To add a picture for a new case, list it in the
module's `wiring.json` (see `images` below).

## The file

```json
{
  "nodes": [
    {"id": "vna", "role": "vna", "at": [0, 0], "title": {"en": "VNA", "it": "VNA"},
     "ports": [{"id": "p1", "side": "right", "label": {"en": "Port 1", "it": "Porta 1"}},
               {"id": "p2", "side": "right", "label": {"en": "Port 2", "it": "Porta 2"}}]},
    {"id": "dut", "kind": "device", "at": [1, 0], "title": "{filter.label|Filter}",
     "ports": [{"id": "in", "side": "left", "label": "Input"},
               {"id": "out", "side": "left", "label": "Output"}]}
  ],
  "links": [
    {"from": "vna.p1", "to": "dut.in", "label": {"en": "test lead", "it": "cavo di test"}},
    {"from": "vna.p2", "to": "dut.out", "label": {"en": "test lead", "it": "cavo di test"}}
  ],
  "steps": [{"en": "Connect the filter input to port 1 of the VNA.", "it": "Collega l'ingresso del filtro alla porta 1 del VNA."}],
  "notes": [{"en": "Calibrate the VNA beforehand.", "it": "Calibra prima il VNA."}],
  "images": [{"file": "filter", "optional": true}]
}
```

| Part | Meaning |
|---|---|
| `nodes[].id` | name used by the links |
| `nodes[].at` | `[column, row]`: the boxes are laid out on that grid (a negative row is above row 0) |
| `nodes[].kind` | `instrument` (default) or `device`: the device under test has a double frame |
| `nodes[].role` | the role of the module: the names of the instruments bound to it are written under the title |
| `nodes[].title` | the name in the box |
| `nodes[].ports[]` | the connectors: `id`, `label`, `side` (`left` or `right`) |
| `links[]` | a cable from `node.port` to `node.port`, with a `label` and, for a line that is not a signal, `"style": "dashed"` |
| `steps[]` | what to connect, in order, as sentences; they are numbered in the window. A text, a dictionary of languages, or `{"text": ..., "when": ..., "foreach": ...}` (below) |
| `notes[]` | a sentence shown under the list; as `{"when": ..., "text": ...}` to show it only sometimes |
| `images[]` | `{"file": "name", "when": ..., "optional": true}`: a picture drawn by hand, the first one that applies and exists is shown instead of the diagram. A name without an extension is looked for as `.svg`, `.png`, `.jpg`, `.jpeg`, `.webp`; `{lang}` in it is the language. A missing file that is not `optional` is reported in the window |

* A **text** is a string or a dictionary of languages (`en`, `it`, `fr`, `es`, `de`; English is the fallback). A
  text written as a dictionary must have all five (a test checks it).
* `{path}` or `{path|default}` in a text is replaced by a parameter of the measurement file (`{scope.channel|1}`);
  without a value the default is used, or `?`.
* `"when"` on a node, port, link or note: a parameter path (shown if it is set: true, a non-empty text, a number
  other than 0, a non-empty list), `"!path"` (shown if it is not set), `"path=value"` or `"path!=value"` (compared
  with a text), or a list of these (all must hold).
* A step can be **repeated for every item of a list in the file**: `"foreach": [["variables", "v"], ["v.reads", "r"]]`
  makes one sentence for every reading of every variable, with `{v.name}` and `{r.args.channels}` available (for a
  dictionary the key is `{r.key}`, and `{v_number}` counts from 1). This is how the efficiency steps are written from the
  file the user edited: *"Connect channel 101 of daq1 to «vin» of the converter."*. A `when` inside a loop can use the
  loop names too (`"when": "r.args.channels"`).
* A link must go between ports that are drawn: a link to a port that is hidden by its `when` is an error that names it.

The layout is automatic: a box per node, its ports listed inside on the left or right, right-angled links with their
labels. A test checks, for every module and for the starting parameters and a variation of them, that the boxes do not
overlap, that everything is inside the page and that the names used in `{...}` and `"when"` are parameters of the
module. The drawing is a `Drawing` in millimetres like the labels ([`assets.md`](assets.md)), so it can be written as
SVG.

## Which measurements have one

The six RF measurements (cable, return loss, antenna, filter, amplifier, attenuator) with a VNA, ripple and noise with
an oscilloscope (and the electronic load), the efficiency measurement and the time log.

* The **steps** of the efficiency measurement and the time log are written from the file: for every parameter that is
  set (*"Connect channel 1 of psu1 to «vin» of the converter: it sets «vin» (set_voltage)"*) and every reading that
  uses a channel (*"Connect channel 102 of daq1 to «iin» of the converter (the reading is multiplied by 10)"*). The
  program does not know what the names mean (which pin is `vin`): it uses your names, so name the parameters as you
  would say them. A reading that comes from the instrument that sets the value (a supply reading its own voltage) needs
  no wire and has no step.
* The efficiency **diagram** is a typical set-up (input supply, converter, load).
* The time log has steps and no diagram.

## Not done yet

The program does not know what a name means (it writes «vin», not "the input of the converter"): a free text per
parameter in the efficiency editor ("converter input, + pin") would let the steps say it. The diagrams do not draw the
pins inside the device or the data-logger channels. A printable version with the project's name and the date, as part
of the report, is for the report feature.
