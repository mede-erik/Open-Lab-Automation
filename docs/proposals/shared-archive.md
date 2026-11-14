# Shared archive of projects and measurements (proposal)

Status: proposal, **not to be implemented yet**. Decisions taken in the discussion with the project
owner are marked **Decided**. Section 6 lists the few small changes done *before* the archive, because they are cheap now and
expensive later (done).

## Goal

A team that works on the same projects needs to see and reuse each other's work: setups, measurements
already made, and the registry of cables and devices. The software has two modes:

- **Local**: everything lives on this computer (today's behaviour, stays the default).
- **Archive**: one shared place that holds the projects of the team. The user can *publish* a local
  project to it and open a project from it.

## Decisions

- **Decided.** One archive for a whole team, holding **all its projects and the registry of cables and
  devices** (one archive = one team, as one repository per team in a company).
- **Decided.** Everything the user publishes is readable by everyone who can reach the archive.
- **Decided.** Same network or VPN: no need to solve geographic distribution. The first backend is a
  **shared folder** (NAS, SMB/NFS); a server or git backend can come later behind the same interface.
- **Decided.** Nobody edits the same thing at the same moment. Conflicts are rare and must be
  *detected and shown*, not prevented by complex machinery.
- **Decided.** Publishing from a local project is the main flow. How versions are compared is in §3.
- Users and permissions: left for later (§7).

## 1. What already helps

| Existing piece | Why it matters |
|---|---|
| A project is a self-contained folder; file names are plain names (`check_plain_filename`) | The archive can hold the same folders; no absolute paths to fix. |
| Runs are append-only JSON Lines with a unique `run_id` | Runs never conflict: publishing them is a copy of the files that are not there yet. |
| Run headers keep a snapshot of the instruments and of the cards of that day (`ola/identity.py`, `snapshot`) | A run read by a colleague is still meaningful. |
| `ola/role_mapping.py`, `ola/compat.py` | A colleague runs *my* measurement with *their* instruments, and is warned if theirs is weaker. |
| Calibrations belong to one serial number | A shared calibration is never applied to the wrong apparatus. |
| `OLA_ASSETS_FILE` | The registry can already be moved to a shared folder. |

Legacy, to be decided when the archive is built: `frontend/core/ProjectDatabaseManager.py`,
`database.py`, `models.py`, `database_config.py` and the *Database configuration* dialog are the old
PostgreSQL storage of the **efficiency** flow. The program still tries to connect at startup if a
configuration exists, but the new engine (`ola/`) does not use it, so it plays no part in this
proposal. Its encrypted-credentials code could be reused by a future server backend.

## 2. What is missing

1. A place and a notion of "archive" (settings, list of projects).
2. A **stable project identity**: today a project is its folder and its name, and both can change.
3. **Who and where** in every run: no author, host or software version in the header.
4. **Unique run file names**: `<stem>_<date>_<time>[_n].jsonl` can collide between two people.
5. **Safe writes**: `Project.save()` writes in place (not atomic) and nothing notices that the file
   changed under us; the registry has no lock, and two people can be given the same code.
6. A **version model** for the files that change (§3).
7. A searchable **index** of the runs (the folder scan of `index_runs` does not scale on a network).

## 3. Versions: what "publish" does

Two kinds of content:

- **Append-only** (runs, calibration records): no versions. Publish copies what is missing; the
  `run_id` decides. Nothing to resolve.
- **Editable** (project file, instrument file, measurement files, golden samples, registry cards): they
  have *revisions*.

**Revision** = content hash + author + date + optional note. The archive keeps every revision of
an editable file (`history/`), so **nothing is ever lost or deleted by publishing**; "current" is only
a pointer.

A local project remembers where it came from in a small file in its folder (`.ola-origin.json`:
archive id, project id, and for each editable file the revision it was based on). Publishing compares:

| Archive head vs. my base | Meaning | Action |
|---|---|---|
| head = my base, I changed the file | I am the only one who changed it | publish: new revision |
| head = my base, I did not change it | nothing to do | skip |
| head != my base, I did not change it | someone else updated it | *update* the local copy |
| head != my base, I changed it | **conflict** | show who/when, what differs, and ask |

For a conflict the user chooses: **keep the archive's** (mine stays as a local copy), **replace with
mine** (becomes the new revision; the other stays in the history), or **publish mine as a new
measurement** (a copy under another name). The dialog shows a readable difference of the parameters
(not raw JSON). Publishing a project that is not yet in the archive just creates it.

Open: whether a revision can be marked **released / validated** so that the team measures with a
known-good setup (§7).

## 4. Layout of the archive (shared folder)

```
<archive>/
  archive.json                   format_version, name, created
  projects/<project_id>/         the project folder as it is locally
      project.json, *.inst, *.eff ...   current revision
      runs/<stem>_<date>_<time>_<run_id>.jsonl
      calibrations/, golden/
      .history/<file>/<revision>   old revisions
  assets/
      CBL-0042.json ...          one file per card
      history/
  index.sqlite                   optional, rebuildable cache (never the source of truth)
```

- **The files stay the source of truth**; any index can be rebuilt from them. A plain folder can be
  copied, backed up and read without the program.
- **One file per card** in `assets/`: a new code is allocated by creating the file in exclusive mode
  (`O_EXCL`), which fails if the file exists. Two people cannot get the same code and no lock is needed.
- The few places that need exclusion (publishing an editable file) use a lock marker created
  atomically (`mkdir`), with owner and expiry, so a crashed program does not block the team forever.
- All writes: temporary file + `os.replace` (atomic on the same share).

## 5. Phases

1. **Foundations** (§6) in local mode. Done.
2. `ola/archive.py` (no Qt): the `Archive` interface (`list_projects`, `open_project`,
   `publish`, `status`, history) and the shared-folder backend; the revision logic of §3; tests with
   two simulated users on one temporary folder (including crash during publish and a stale lock).
3. **Registry in the archive**: cards as files, allocation of codes, import of a local registry (§7).
4. **User interface**: archive settings, *Open from archive*, *Publish*, status of each file (new /
   changed / up to date / conflict), conflict dialog, author column in the run list.
5. **Index** (SQLite) for searching runs by measurement, author, date, DUT, state.
6. Later and only if needed: server or git backend, permissions, release marks.

## 6. Foundations (done, in local mode)

Implemented in the first step, tested in `tests/test_archive_preparation.py`:

1. **`project_id`** in the project file (a random UUID; given to a project that has none and saved;
   the name stays a label, renaming keeps the id).
2. **Who and where in the run header**: `author` (`$OLA_AUTHOR`, else the operating-system user),
   `host`, `software_version` (`ola/provenance.py`). A value that cannot be found is `"unknown"`.
   Still to do: a field in the settings window to declare the author.
3. **Unique run file names**: `<measurement>_<date>_<time>_<run id>.jsonl`. The `run_id` identifies
   one execution of a measurement (the measurement itself has its `id` `m1`, `m2`... in the project).
4. **Atomic writes** (`ola/fileio.py`) for project, measurement, instrument and calibration files and
   for the references rewritten by a rename; the registry uses it too (and keeps its `.bak`).
   The older editors in `frontend/ui` (`.eff`/`.was`/`.inst` dialogs) still write in place.
5. **`uid` and `former_codes` on every registry card**, copied in the snapshot a run saves.
   `ola.assets.runs_of` / `history(code, dirs, registry)` follow the object by `uid`, then by code
   and former codes for runs without a `uid`; two objects with the same code are never mixed.
6. **No absolute path in a project**: `attach_to_project` refuses a calibration outside the project
   folder (it used to store the absolute path), and a test checks the names a project lists.

Not done on purpose: archive settings, locks, history, index, user interface.

Note for the correction of a measurement (`resolve_correction`): it uses the **newest finished**
measurement of a cable by code. With two series of different frequency range the newest may not
cover the sweep; the choice should then take the range into account. To do together with the
registry in the archive.

## 7. Open points

- **Registry merge: "Upload my cables" (deferred: built with the archive, not before).** The
  foundations that it needs are already in local mode (`uid`, `former_codes`, the history found by
  `uid`), so nothing has to change when it is built. The procedure, as decided:
  - the program lists my cards and the archive's and proposes matches (same `uid`, else same code and
    kind and a similar description); for each of mine I answer **same object** or **different, import
    as new**;
  - *same*: the archive's card is kept (the first to arrive sets it); fields that differ are shown and
    I choose. My runs need no change: the history is found through the card, so the measurements of
    both people appear on the same cable; which one is used is a rule of the views (the newest, per
    kind of measurement and frequency range), not a merge;
  - *different*, code free in the archive: it keeps its code; code taken: it gets the next free code,
    the old one goes to `former_codes`, the measurement files of my projects are rewritten (as
    `project_rename` does for instruments), run files are never touched, and a sheet of labels to
    reprint is prepared. The QR code keeps holding the code, so only the cables that changed code are
    reprinted;
  - codes in the archive are allocated by creating the card file exclusively, so two people loading at
    the same time never get the same code.
- **Released revisions** (a validated setup for the team).
- **Users and permissions**: the declared author is enough on a shared folder (the file system gives
  read/write); a server would need real accounts. Roles (read only, editor, administrator) later.
- **Large waveforms**: traces are stored inline in the JSON. On a network share very large runs are
  slow; the binary sidecar mentioned in `ola/runs.py` becomes useful before the archive.
- **Offline**: a project opened from the archive is copied locally; publishing when the share is not
  reachable must fail with a clear sentence and lose nothing.
- **Archive version**: `archive.json` carries `format_version` so an old program refuses a newer archive
  instead of damaging it.
- **Legacy PostgreSQL code**: keep untouched for now; decide to remove it or to reuse it for a server
  backend when phase 6 comes.
