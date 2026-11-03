"""What a form-based editor of a measurement edits, without any screen.

A measurement module that wants an editor with no code of its own puts a ``form.json`` next to its
``module.json`` that says which fields there are (see ``load_form_spec`` and ``docs/measurement-
modules.md``). ``FormModel`` holds the parameters being edited and answers what the window asks:
the value of a field, setting it, which fields are visible now, and the problems of the
parameters (from the module's own ``check()`` or ``validate()``), each with the path of its field::

    spec = load_form_spec(registry.get("cable"))
    model = FormModel(spec, params, role_bindings,
                      check=lambda p: registry.create("cable", p).check())
    model.set("sweep.points", 401); model.problems_at("sweep"); model.save(path)

Text in ``form.json`` is a string or a dictionary ``{"en": "...", "it": "..."}``; ``localized``
picks the language, then English, then any.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from .efficiency_editor import get_path, set_path
from .efficiency_spec import Problem
from .project import MeasurementFile
from .registry import ModuleInfo

KINDS = ("text", "number", "int", "bool", "choice", "numlist", "json", "instrument")
Text = Union[str, Mapping[str, str]]
Check = Callable[[Dict[str, Any]], List[Problem]]


class FormSpecError(ValueError):
    """``form.json`` is not valid; the message says where."""


def localized(text: Optional[Text], lang: str = "en") -> str:
    """A text of ``form.json`` in language ``lang`` (or English, or the first one given)."""
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    return str(text.get(lang) or text.get("en") or next(iter(text.values()), ""))


@dataclass
class Choice:
    """One option of a ``choice`` field."""

    value: Any
    label: Text


@dataclass
class FormField:
    """One field of the form."""

    path: str  # in the params (``sweep.points``); for ``instrument`` the role name
    kind: str
    label: Text = ""
    help: Text = ""
    unit: str = ""  # for numbers: shown after the value, and accepted with or without it
    choices: List[Choice] = field(default_factory=list)
    placeholder: Text = ""
    visible_if: Optional[Dict[str, Any]] = None  # {"path": "mode", "equals": "reflection"}


@dataclass
class FormSection:
    """A titled group of fields."""

    title: Text
    fields: List[FormField]


@dataclass
class FormSpec:
    """The whole form."""

    sections: List[FormSection]

    def fields(self) -> List[FormField]:
        """Every field, in order."""
        return [f for s in self.sections for f in s.fields]


def parse_form_spec(raw: Any, where: str = "form.json") -> FormSpec:
    """Check and build a ``FormSpec`` from the loaded JSON. ``FormSpecError`` says what is wrong."""
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("sections"), list)
        or not raw["sections"]
    ):
        raise FormSpecError(f"{where}: needs a non-empty list 'sections'")
    sections: List[FormSection] = []
    for n, rs in enumerate(raw["sections"], 1):
        if not isinstance(rs, dict) or not isinstance(rs.get("fields"), list):
            raise FormSpecError(f"{where}: section {n} needs a list 'fields'")
        fields: List[FormField] = []
        for m, rf in enumerate(rs["fields"], 1):
            at = f"{where}: section {n}, field {m}"
            if not isinstance(rf, dict) or not isinstance(rf.get("path"), str) or not rf["path"]:
                raise FormSpecError(f"{at}: needs a 'path'")
            if rf.get("kind") not in KINDS:
                raise FormSpecError(
                    f"{at} ({rf['path']}): 'kind' must be one of {', '.join(KINDS)}"
                )
            choices = [
                Choice(c["value"], c.get("label", str(c["value"])))
                for c in rf.get("choices", [])
                if isinstance(c, dict) and "value" in c
            ]
            if rf["kind"] == "choice" and not choices:
                raise FormSpecError(f"{at} ({rf['path']}): a 'choice' needs 'choices'")
            visible = rf.get("visible_if")
            if visible is not None and not (
                isinstance(visible, dict)
                and "path" in visible
                and ("equals" in visible or "in" in visible)
            ):
                raise FormSpecError(
                    f"{at} ({rf['path']}): 'visible_if' needs 'path' and 'equals' or 'in'"
                )
            fields.append(
                FormField(
                    path=rf["path"],
                    kind=rf["kind"],
                    label=rf.get("label", rf["path"]),
                    help=rf.get("help", ""),
                    unit=str(rf.get("unit", "")),
                    choices=choices,
                    placeholder=rf.get("placeholder", ""),
                    visible_if=visible,
                )
            )
        sections.append(FormSection(rs.get("title", ""), fields))
    return FormSpec(sections)


def load_form_spec(info: ModuleInfo) -> Optional[FormSpec]:
    """The form of a module (its ``form.json``), or None if it has none."""
    path = Path(info.path) / "form.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FormSpecError(f"{path}: cannot read: {exc}") from exc
    return parse_form_spec(raw, str(path))


class FormModel:
    """The parameters of one measurement file while they are edited."""

    def __init__(
        self,
        spec: FormSpec,
        params: Mapping[str, Any],
        role_bindings: Optional[Mapping[str, Any]] = None,
        check: Optional[Check] = None,
        measurement_type: str = "",
        module_version: str = "",
        required_roles: Sequence[str] = (),
        role_message: Optional[Callable[[str], str]] = None,
    ):
        """``check(params)`` returns the ``Problem`` list of the parameters (the module's own
        ``check()``, or its ``validate()`` strings as problems without a path). A role in
        ``required_roles`` with no instrument chosen is an error at the field of that role
        (``role_message(role)`` is its text)."""
        self.spec = spec
        self.params: Dict[str, Any] = copy.deepcopy(dict(params))
        self.role_bindings: Dict[str, Any] = copy.deepcopy(dict(role_bindings or {}))
        self._check = check
        self.type, self.version = measurement_type, module_version
        self.required_roles = list(required_roles)
        self._role_message = role_message or (lambda role: f"no instrument chosen for '{role}'")
        self._problems: Optional[List[Problem]] = None

    # ----- values -----------------------------------------------------------------------------
    def get(self, path: str, default: Any = None) -> Any:
        """The value of a field."""
        return get_path(self.params, path, default)

    def set(self, path: str, value: Any) -> None:
        """Set a field; ``None`` removes it (an empty field means "not given"). Dictionaries left
        empty by the removal are removed too."""
        set_path(self.params, path, value)
        if value is None:
            self._prune(path)
        self._problems = None

    def _prune(self, path: str) -> None:
        parts = path.split(".")
        for depth in range(len(parts) - 1, 0, -1):
            parent = get_path(self.params, ".".join(parts[:depth]))
            if isinstance(parent, dict) and not parent:
                grand = (
                    get_path(self.params, ".".join(parts[: depth - 1]))
                    if depth > 1
                    else self.params
                )
                if isinstance(grand, dict):
                    grand.pop(parts[depth - 1], None)

    def instrument(self, role: str) -> Optional[str]:
        """The instrument chosen for a role (the first one), or None."""
        value = self.role_bindings.get(role)
        if isinstance(value, list):
            return value[0] if value else None
        return value or None

    def set_instrument(self, role: str, name: Optional[str]) -> None:
        """Choose the instrument of a role (None clears it)."""
        if name:
            self.role_bindings[role] = [name]
        else:
            self.role_bindings.pop(role, None)
        self._problems = None

    def visible(self, f: FormField) -> bool:
        """False if the field depends on another one that has a different value now."""
        if not f.visible_if:
            return True
        value = self.get(f.visible_if["path"])
        if "equals" in f.visible_if:
            return value == f.visible_if["equals"]
        return value in f.visible_if["in"]

    # ----- problems ---------------------------------------------------------------------------
    def problems(self) -> List[Problem]:
        """The problems of the parameters now (cached until the next change)."""
        if self._problems is None:
            found = list(self._check(self.params)) if self._check else []
            missing = [r for r in self.required_roles if not self.instrument(r)]
            self._problems = [Problem(r, self._role_message(r)) for r in missing] + found
        return self._problems

    def problems_at(self, prefix: str) -> List[Problem]:
        """The problems of a field or of everything under it."""
        return [
            p
            for p in self.problems()
            if p.path == prefix or p.path.startswith((prefix + ".", prefix + "["))
        ]

    def has_errors(self) -> bool:
        """True if the measurement could not start with these parameters."""
        return any(p.severity == "error" for p in self.problems())

    # ----- file -------------------------------------------------------------------------------
    def to_measurement_file(self) -> MeasurementFile:
        """What is saved: the type, the instruments chosen and the parameters."""
        return MeasurementFile(
            type=self.type,
            module_version=self.version,
            role_bindings=copy.deepcopy(self.role_bindings),
            params=copy.deepcopy(self.params),
        )

    def save(self, path: Union[str, Path]) -> None:
        """Write the measurement file."""
        self.to_measurement_file().save(path)

    @classmethod
    def from_file(
        cls,
        spec: FormSpec,
        path: Union[str, Path],
        check: Optional[Check] = None,
        expected_type: Optional[str] = None,
        required_roles: Sequence[str] = (),
        role_message: Optional[Callable[[str], str]] = None,
    ) -> "FormModel":
        """Open a measurement file (``MeasurementError`` if it is not one, or of another type)."""
        from .measurement import MeasurementError

        file = MeasurementFile.load(path)
        if expected_type and file.type != expected_type:
            raise MeasurementError(f"{path} is a '{file.type}' file, not a '{expected_type}' file")
        return cls(
            spec, file.params, file.role_bindings, check, file.type, file.module_version,
            required_roles, role_message,
        )  # fmt: skip


def check_from_measurement(create: Callable[[Dict[str, Any]], Any]) -> Check:
    """A ``check`` for ``FormModel`` from a function that builds the measurement from its params:
    uses its ``check()`` if it has one (problems with paths), else its ``validate()`` sentences."""

    def check(params: Dict[str, Any]) -> List[Problem]:
        try:
            measurement = create(params)
        except Exception as exc:  # parameters so wrong that the module cannot be built from them
            return [Problem("", str(exc))]
        if hasattr(measurement, "check"):
            return list(measurement.check())
        return [Problem("", text) for text in measurement.validate()]

    return check


__all__: Sequence[str] = [
    "FormModel", "FormSpec", "FormSpecError", "load_form_spec", "parse_form_spec", "localized",
    "check_from_measurement",
]  # fmt: skip
