# Software test status

The automatic tests need no instrument (see [Testing and CI](Testing-and-CI)). What they cannot show is whether a feature works on a **real instrument**. The list of what still has to be run on real hardware is the section *Software test status* of the repository [README](https://github.com/mede-erik/Open-Lab-Automation/blob/main/README.md#software-test-status).

How the list works:

- A box is checked only when the feature was run on the real instrument, with the model written next to it. A simulated run does not count.
- A feature with sub-items is checked only when all of them are.
- A new feature is added to the list unchecked, in its category.
- The status of the instrument *library* is a separate thing, kept in the [library repository](Instrument-Library).

Categories of the list: instrument connection, remote control panel, measurements, projects and data, tools, interface, languages and installation (including the packages on a clean Windows machine).

The goals for the first alpha are tracked in the milestone *First Alpha* of the repository: [Roadmap](Roadmap).
