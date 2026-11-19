# Glossary

**Calibration (VNA)**: the correction a network analyzer applies so that the reference plane sits at the end of the test leads. Done by the user before a measurement; OLA asks whether it has been done.

**Cable code**: the identifier of a measured object in the registry, such as `CBL-0042`. Never reused. Printed on the label and saved in each run.

**De-embedding**: taking a known fixture (cable, adapter, pad) out of a measurement, so the result describes the device alone.

**Golden sample**: a unit known to be good. New runs are checked against its saved result, with tolerances.

**Logical call**: an action such as `set_voltage` or `read_scan`, the same for every brand. The instrument library translates it into commands for each model.

**Manual instrument**: a bench supply or load without remote control. The operator is asked, by a pop-up, to set it by hand.

**Role**: the name a measurement gives to an instrument it needs (for example `psu`, `vna`). A project maps roles to the instruments you have.

**Run**: one execution of a measurement. Its file records the results and the identity of the instruments used.

**Touchstone**: the standard text format for S-parameters (`.s1p`, `.s2p`).

**VNA**: vector network analyzer, an instrument that measures S-parameters of RF devices.

**Velocity factor**: the speed of a signal along a cable as a fraction of the speed of light. Needed to turn a time-domain peak into a distance.
