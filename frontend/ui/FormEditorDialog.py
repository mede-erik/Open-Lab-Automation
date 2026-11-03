"""Editor of a measurement file, built from the ``form.json`` of its module.

A measurement module that has a ``form.json`` next to its ``module.json`` gets this editor with no
code of its own (see ``ola/form_model.py``). The window is a thin layer over ``FormModel``: it
draws the sections and fields of the form, writes every edit into the model, and shows the
problems the module itself reports (``check()``), each next to its field:

* a red (error) or amber (warning) border and a tooltip on the field;
* the list of all the problems at the bottom; a double click goes to the field;
* fields that depend on another one (``visible_if``) appear and disappear as it changes.

Numbers may be typed with an SI prefix (``433M``, ``2.4 GHz``). Strings of the module come from
its ``form.json`` in the language of the application; the ones of this window from
``frontend/lang/modules/form/<lang>.json``.
"""

import json
import os
import sys
from typing import Any, Dict, Optional, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.efficiency_widgets import mark_widget, text_color
from frontend.ui.module_translator import CatalogTranslator
from ola.form_model import (
    FormField,
    FormModel,
    check_from_measurement,
    load_form_spec,
    localized,
)
from ola.run_view import format_si, parse_si


class _Row:
    """One field of the form on screen: its widget and the container to show or hide."""

    def __init__(self, field: FormField, widget: QWidget, container: QWidget):
        self.field, self.widget, self.container = field, widget, container
        self.invalid = ""  # why what was typed cannot be used, or ""


def default_params_of(registry: Any, type_id: str) -> Dict[str, Any]:
    """The starting parameters of a built-in module (its ``default_params()``), or ``{}``."""
    info = registry.get(type_id)
    if not info.builtin:
        return {}  # code of a user module is not run just to open an editor
    module = sys.modules.get(registry.load_class(type_id).__module__)
    function = getattr(module, "default_params", None)
    return dict(function()) if callable(function) else {}


class FormEditorDialog(QDialog):
    """Editor of a ``.cbl``-like file with live validation."""

    def __init__(
        self,
        file_path: str,
        registry: Any,
        type_id: str,
        translator: Any = None,
        instruments: Sequence[str] = (),
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.tr_ = CatalogTranslator("form", translator)
        self._t = self.tr_.t
        self.lang = self.tr_.lang
        self.file_path, self.registry, self.type_id = file_path, registry, type_id
        self.instruments = list(instruments)
        self.dirty = False
        self._loading = False
        self.rows: Dict[str, _Row] = {}
        info = registry.get(type_id)
        spec = load_form_spec(info)
        if spec is None:
            raise ValueError(self._t("form_no_form", module=info.name))
        check = check_from_measurement(lambda params: registry.create(type_id, params))
        roles = [r.name for r in info.roles if r.required]
        say = lambda role: self._t("form_choose_instrument", role=role)  # noqa: E731
        if os.path.isfile(file_path):
            self.model = FormModel.from_file(
                spec, file_path, check, type_id, required_roles=roles, role_message=say
            )
        else:
            self.model = FormModel(spec, {}, {}, check, type_id, info.version, roles, say)
        if not self.model.params:
            self.model.params = default_params_of(registry, type_id)
        self.setWindowTitle(f"{info.name} - {os.path.basename(file_path)}")
        self.resize(900, 760)
        self._build_ui(info.name)
        self._refresh_all()

    # ================================================================ building the window
    def _text(self, text: Any) -> str:
        return localized(text, self.lang)

    def _build_ui(self, module_name: str) -> None:
        root = QVBoxLayout(self)
        self.summary_label = QLabel()
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.summary_label)
        page = QWidget()
        layout = QVBoxLayout(page)
        for section in self.model.spec.sections:
            group = QGroupBox(self._text(section.title))
            form = QFormLayout(group)
            for field in section.fields:
                container, widget = self._make_row(field)
                label = QLabel(self._text(field.label))
                if field.kind == "bool":
                    label.hide()
                    form.addRow(container)
                else:
                    form.addRow(label, container)
                container.label = label  # shown and hidden together with the field
                self.rows[field.path] = _Row(field, widget, container)
            layout.addWidget(group)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)

        self.problem_title = QLabel()
        self.problem_tree = QTreeWidget()
        self.problem_tree.setHeaderLabels(["", self._t("form_field"), self._t("form_problem")])
        self.problem_tree.setRootIsDecorated(False)
        self.problem_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.problem_tree.setColumnWidth(0, 28)
        self.problem_tree.setColumnWidth(1, 180)
        self.problem_tree.itemDoubleClicked.connect(
            lambda item, _c: self.navigate(item.data(0, Qt.ItemDataRole.UserRole))
        )
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(self.problem_title)
        bottom_layout.addWidget(self.problem_tree)
        bottom.setMinimumHeight(150)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(scroll)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self.status_label = QLabel()
        self.save_btn = QPushButton(self._t("form_save"))
        self.save_btn.clicked.connect(self.save)
        self.close_btn = QPushButton(self._t("form_close"))
        self.close_btn.clicked.connect(self.close)
        buttons.addWidget(self.status_label, 1)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.close_btn)
        root.addLayout(buttons)

    def _make_row(self, field: FormField):
        """The widget of one field, with its help text and unit, in a container."""
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 2)
        top = QHBoxLayout()
        widget: QWidget
        if field.kind == "bool":
            widget = QCheckBox(self._text(field.label))
            widget.toggled.connect(lambda _on, f=field: self._edited(f))
        elif field.kind == "choice":
            widget = QComboBox()
            for choice in field.choices:
                widget.addItem(self._text(choice.label), choice.value)
            widget.currentIndexChanged.connect(lambda _i, f=field: self._edited(f))
        elif field.kind == "instrument":
            widget = QComboBox()
            widget.setEditable(True)
            widget.addItem("", None)
            for name in self.instruments:
                widget.addItem(name, name)
            widget.currentTextChanged.connect(lambda _t, f=field: self._edited(f))
        elif field.kind == "json":
            widget = QPlainTextEdit()
            widget.setMaximumHeight(90)
            widget.setPlaceholderText('{"max": 1.5}')
            widget.textChanged.connect(lambda f=field: self._edited(f))
        else:  # text, number, int, numlist
            widget = QLineEdit()
            widget.setPlaceholderText(self._text(field.placeholder))
            widget.textChanged.connect(lambda _t, f=field: self._edited(f))
        top.addWidget(widget, 1)
        if field.unit and field.kind in ("number", "numlist"):
            top.addWidget(QLabel(field.unit))
        box.addLayout(top)
        if field.help:
            help_label = QLabel(self._text(field.help))
            help_label.setWordWrap(True)
            help_label.setStyleSheet(f"color: {text_color('muted', self)}; font-size: 90%;")
            box.addWidget(help_label)
        return container, widget

    # ================================================================ model <-> widgets
    def _show_value(self, row: _Row) -> None:
        f, w = row.field, row.widget
        if f.kind == "instrument":
            name = self.model.instrument(f.path) or ""
            if w.findText(name) < 0 and name:
                w.addItem(name, name)  # a name the project does not list: kept, not lost
            w.setCurrentText(name)
            return
        value = self.model.get(f.path)
        if f.kind == "bool":
            w.setChecked(bool(value))
        elif f.kind == "choice":
            position = w.findData(value)
            w.setCurrentIndex(position if position >= 0 else 0)
        elif f.kind == "json":
            w.setPlainText(
                json.dumps(value, indent=2, ensure_ascii=False) if value is not None else ""
            )
        elif f.kind in ("number", "int"):
            w.setText("" if value is None else self._format(value, f.unit))
        elif f.kind == "numlist":
            w.setText(
                ", ".join(self._format(v, f.unit) for v in value) if isinstance(value, list) else ""
            )
        else:
            w.setText("" if value is None else str(value))

    @staticmethod
    def _format(value: Any, unit: str) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return format_si(float(value), unit) if unit else f"{value:g}"
        return str(value)

    def _read(self, row: _Row):
        """What is typed: ``(ok, value)``; ``ok`` is False if it cannot be used (``row.invalid``
        says why)."""
        f, w = row.field, row.widget
        row.invalid = ""
        if f.kind == "bool":
            return True, w.isChecked()
        if f.kind == "choice":
            return True, w.currentData()
        if f.kind == "instrument":
            return True, w.currentText().strip() or None
        if f.kind == "json":
            text = w.toPlainText().strip()
            if not text:
                return True, None
            try:
                return True, json.loads(text)
            except ValueError as exc:
                row.invalid = self._t("form_json_invalid", error=exc)
                return False, None
        text = w.text().strip()
        if f.kind == "text":
            return True, text or None
        if f.kind == "numlist":
            parts = [p for p in text.replace(";", ",").split(",") if p.strip()]
            values = [parse_si(p, f.unit) for p in parts]
            if any(v is None for v in values):
                row.invalid = self._t("form_not_a_number")
                return False, None
            return True, [int(v) if float(v).is_integer() else v for v in values] or None
        if not text:
            return True, None
        value = parse_si(text, f.unit)
        if value is None:
            row.invalid = self._t("form_not_a_number")
            return False, None
        if f.kind == "int":
            if not float(value).is_integer():
                row.invalid = self._t("form_not_an_integer")
                return False, None
            return True, int(value)
        return True, int(value) if float(value).is_integer() and abs(value) < 1e15 else value

    def _edited(self, field: FormField) -> None:
        if self._loading:
            return
        row = self.rows[field.path]
        ok, value = self._read(row)
        if ok:
            if field.kind == "instrument":
                self.model.set_instrument(field.path, value)
            else:
                self.model.set(field.path, value)
        self.dirty = True
        self._refresh_state()

    # ================================================================ showing the state
    def _refresh_all(self) -> None:
        self._loading = True
        for row in self.rows.values():
            self._show_value(row)
            row.invalid = ""
        self._loading = False
        self._refresh_state()

    def _refresh_state(self) -> None:
        """Visibility of the dependent fields, the marks on the fields, the problem list."""
        for row in self.rows.values():
            visible = self.model.visible(row.field)
            row.container.setVisible(visible)
            label = getattr(row.container, "label", None)
            if label is not None and row.field.kind != "bool":
                label.setVisible(visible)
        problems = sorted(self.model.problems(), key=lambda p: p.severity != "error")
        for path, row in self.rows.items():
            found = [
                p
                for p in problems
                if p.path == path
                or p.path.startswith(path + ".")
                or path.startswith(p.path + ".")  # a problem of the whole group (passband)
            ]
            if row.invalid:
                mark_widget(row.widget, "error", row.invalid)
            elif found:
                severity = "error" if any(p.severity == "error" for p in found) else "warning"
                mark_widget(row.widget, severity, found[0].message)
            else:
                mark_widget(row.widget, None)
        self.problem_tree.clear()
        for p in problems:
            error = p.severity == "error"
            item = QTreeWidgetItem(["●" if error else "▲", p.path, p.message])
            item.setForeground(0, QBrush(QColor(text_color("error" if error else "warning", self))))
            item.setData(0, Qt.ItemDataRole.UserRole, p.path)
            self.problem_tree.addTopLevelItem(item)
        errors = sum(p.severity == "error" for p in problems)
        warnings = len(problems) - errors
        self.problem_title.setText(self._t("form_problems", errors=errors, warnings=warnings))
        color = text_color("error" if errors else "ok", self)
        text = (
            self._t("form_summary_errors", errors=errors) if errors else self._t("form_summary_ok")
        )
        self.summary_label.setText(f"<span style='color:{color}'>{text}</span>")

    def navigate(self, path: Optional[str]) -> None:
        """Put the cursor on the field a problem is about."""
        if not path:
            return
        for key, row in self.rows.items():
            if path == key or path.startswith(key + "."):
                row.widget.setFocus()
                return

    # ================================================================ saving and closing
    def save(self) -> bool:
        """Write the file (after a confirmation if there are errors). True if saved."""
        if self.model.has_errors():
            errors = sum(p.severity == "error" for p in self.model.problems())
            answer = QMessageBox.question(
                self, self.windowTitle(), self._t("form_save_with_errors", errors=errors)
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            self.model.save(self.file_path)
        except Exception as exc:
            QMessageBox.critical(self, self.windowTitle(), self._t("form_save_failed", error=exc))
            return False
        self.dirty = False
        self.status_label.setText(self._t("form_saved"))
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self.dirty:
            box = QMessageBox.StandardButton
            answer = QMessageBox.question(
                self,
                self.windowTitle(),
                self._t("form_unsaved_changes"),
                box.Save | box.Discard | box.Cancel,
            )
            if answer == box.Cancel or (answer == box.Save and not self.save()):
                event.ignore()
                return
        event.accept()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the editor of a measurement file (``... FormEditorDialog file.cbl``)."""
    from ola.registry import default_registry

    argv = list(sys.argv[1:] if argv is None else argv)
    path = argv[0] if argv else "new.cbl"
    registry = default_registry()
    ext = os.path.splitext(path)[1].lower()
    info = registry.by_extension(ext)
    if info is None:
        print(f"no measurement type has the extension {ext!r}")
        return 1
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = FormEditorDialog(path, registry, info.id, instruments=["vna1", "vna2"])
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
