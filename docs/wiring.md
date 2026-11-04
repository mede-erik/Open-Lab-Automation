# Connection diagrams (`wiring.json`)

When a measurement is started the program shows **how to connect the instruments**: a diagram with the instruments and
the device under test, the cable of each connection, a list of the connections as sentences, and the notes that matter
before starting ("calibrate the VNA first", "ground spring, not a long ground lead"). *Start* goes on, *Cancel* does
not start anything. The window has a tick, **Show this before each measurement**, that turns it off (the choice is
remembered); the **Connections...** button of the project window shows it at any time, and **Save SVG...** writes the
diagram as a file.

What is drawn follows the parameters of the measurement file: the amplifier shows its input attenuator only if
`input_attenuation_db` is set, the cable shows port 2 or an open / short end depending on its mode, the ripple
measurement shows the electronic load only if it has `conditions`, the channel and the probe ratio come from the file.
Under each instrument box is the name of the instrument the file binds to that role (from the project's `.inst` file).

The diagram is in [`ola/wiring.py`](../ola/wiring.py) (no Qt; tested without a screen), the window is
`frontend/ui/WiringDialog.py`, and each measurement module brings its own `wiring.json`, so the diagram is updated
together with the module. A module without the file simply has no diagram.

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
  "notes": [{"en": "Calibrate the VNA beforehand.", "it": "Calibra prima il VNA."}]
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
| `notes[]` | a sentence shown under the diagram; as `{"when": ..., "text": ...}` to show it only sometimes |

* A **text** is a string or a dictionary of languages (`en`, `it`, `fr`, `es`, `de`; English is the fallback). A
  text written as a dictionary must have all five (a test checks it).
* `{path}` or `{path|default}` in a text is replaced by a parameter of the measurement file (`{scope.channel|1}`);
  without a value the default is used, or `?`.
* `"when"` on a node, port, link or note: a parameter path (shown if it is set: true, a non-empty text, a number
  other than 0, a non-empty list), `"!path"` (shown if it is not set), `"path=value"` or `"path!=value"` (compared
  with a text), or a list of these (all must hold).
* A link must go between ports that are drawn: a link to a port that is hidden by its `when` is an error that names it.

The layout is automatic: a box per node, its ports listed inside on the left or right, right-angled links with their
labels. A test checks, for every module and for the starting parameters and a variation of them, that the boxes do not
overlap, that everything is inside the page and that the names used in `{...}` and `"when"` are parameters of the
module. The drawing is a `Drawing` in millimetres like the labels ([`assets.md`](assets.md)), so it can be written as
SVG.

## Which measurements have one

The six RF measurements (cable, return loss, antenna, filter, amplifier, attenuator) with a VNA, ripple and noise with
an oscilloscope (and the electronic load), and the efficiency measurement. The efficiency diagram is a **typical**
set-up (input supply, converter, load): the instruments and channels are those named in the file, and the note says so.
The time log has none, because what it measures is whatever the file lists.

## Not done yet

The diagrams show the connections between instruments and the device, not the pins inside the device (where on the
converter the probe goes). The efficiency diagram does not yet draw the data-logger channels and the shunt. A
printable version with the project's name and the date, as part of the report, is for the report feature.
