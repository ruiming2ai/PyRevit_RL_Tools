# -*- coding: utf-8 -*-
"""Copy one source parameter value to one or more target parameters."""

# pylint: disable=import-error,invalid-name,broad-except,too-many-instance-attributes
from collections import defaultdict

from pyrevit import DB
from pyrevit import forms
from pyrevit import revit
from pyrevit import script
from pyrevit.compat import get_elementid_value_func
from pyrevit.framework import System


logger = script.get_logger()
get_elementid_value = get_elementid_value_func()
ALL_TOKEN = "<All>"


def _eid_int(element_id):
    if not element_id:
        return None
    try:
        return int(get_elementid_value(element_id))
    except Exception:
        return None


def _safe_text(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _origin_from_parameter(param, pid_int):
    try:
        if getattr(param, "IsShared", False):
            return "Shared"
    except Exception:
        pass
    if pid_int is not None and pid_int < 0:
        return "Built-in"
    return "Project"


def _data_type_from_parameter(param):
    """Return (key, display_label, discipline_label) across API versions."""
    definition = getattr(param, "Definition", None)
    storage_label = _safe_text(getattr(param, "StorageType", "Unknown"))

    data_key = storage_label
    data_label = storage_label
    discipline_label = "Other"

    # Revit 2021+ ForgeTypeId API
    try:
        spec_id = definition.GetDataType() if definition else None
        spec_typeid = _safe_text(getattr(spec_id, "TypeId", "")) if spec_id else ""
        if spec_typeid:
            data_key = spec_typeid
            # Prefer Revit label, fallback to readable tail.
            try:
                data_label = DB.LabelUtils.GetLabelForSpec(spec_id)
            except Exception:
                data_label = spec_typeid.split(":")[-1] or spec_typeid
            try:
                discipline_id = DB.UnitUtils.GetDiscipline(spec_id)
                try:
                    discipline_label = DB.LabelUtils.GetLabelForDiscipline(discipline_id)
                except Exception:
                    discipline_label = (
                        _safe_text(getattr(discipline_id, "TypeId", "")).split(":")[-1]
                        or _safe_text(discipline_id)
                    )
            except Exception:
                discipline_label = "Other"
            return data_key, data_label, discipline_label
    except Exception:
        pass

    # Older API fallback
    try:
        ptype = definition.ParameterType if definition else None
        ptype_text = _safe_text(ptype)
        if ptype_text:
            data_key = ptype_text
            data_label = ptype_text
    except Exception:
        pass

    return data_key, data_label, discipline_label


def _is_param_match(param, desc):
    if not param or not getattr(param, "Definition", None):
        return False

    pid_int = _eid_int(param.Id)
    if pid_int == desc.param_id_int:
        return True

    if _safe_text(param.Definition.Name) != desc.name:
        return False

    if _safe_text(param.StorageType) != desc.storage_type:
        return False

    data_key, _, _ = _data_type_from_parameter(param)
    return data_key == desc.data_key


def _get_param_by_descriptor(element, desc):
    if not element:
        return None

    param = None
    try:
        if desc.param_id_int < 0:
            bip = System.Enum.ToObject(DB.BuiltInParameter, desc.param_id_int)
            param = element.get_Parameter(bip)
        else:
            param = element.get_Parameter(DB.ElementId(desc.param_id_int))
    except Exception:
        param = None

    if _is_param_match(param, desc):
        return param

    # Fallback by name + storage + datatype (for duplicated API edge cases).
    try:
        for candidate in element.Parameters:
            if _is_param_match(candidate, desc):
                return candidate
    except Exception:
        pass

    return None


def _copy_param_value(source_param, target_param):
    storage = source_param.StorageType

    if storage == DB.StorageType.String:
        target_param.Set(source_param.AsString() or "")
        return True
    if storage == DB.StorageType.Integer:
        target_param.Set(source_param.AsInteger())
        return True
    if storage == DB.StorageType.Double:
        target_param.Set(source_param.AsDouble())
        return True
    if storage == DB.StorageType.ElementId:
        target_param.Set(source_param.AsElementId())
        return True

    return False


def _source_has_value(source_param):
    try:
        return bool(source_param.HasValue)
    except Exception:
        if source_param.StorageType == DB.StorageType.String:
            return bool(source_param.AsString())
        return True


class ParamDescriptor(object):
    def __init__(
        self,
        param_id_int,
        name,
        is_instance,
        origin,
        storage_type,
        data_key,
        data_label,
        discipline_label,
        has_writable=False,
    ):
        self.param_id_int = param_id_int
        self.name = name
        self.is_instance = is_instance
        self.origin = origin
        self.storage_type = storage_type
        self.data_key = data_key
        self.data_label = data_label
        self.discipline_label = discipline_label
        self.has_writable = has_writable
        self.key = "{}|{}".format("I" if is_instance else "T", param_id_int)
        self.sort_key = (
            name.lower(),
            0 if is_instance else 1,
            data_label.lower(),
            origin.lower(),
            param_id_int,
        )

    @property
    def kind_label(self):
        return "Instance" if self.is_instance else "Type"

    @property
    def display(self):
        return "{} [{} | {} | {}]".format(
            self.name,
            self.kind_label,
            self.data_label,
            self.origin,
        )

    def __repr__(self):
        return self.display


def _collect_scope_elements():
    doc = revit.doc
    uidoc = revit.uidoc

    selected_ids = []
    try:
        selected_ids = list(uidoc.Selection.GetElementIds())
    except Exception:
        selected_ids = []

    selected_elements = [doc.GetElement(x) for x in selected_ids if doc.GetElement(x)]
    selected_instances = []
    selected_types = []

    for elem in selected_elements:
        if isinstance(elem, DB.ElementType):
            selected_types.append(elem)
        else:
            selected_instances.append(elem)

    if selected_instances or selected_types:
        scope_note = "Scope: {} selected element(s)".format(len(selected_elements))
        instance_elements = list(selected_instances)
        type_map = {_eid_int(t.Id): t for t in selected_types if t}
        for inst in selected_instances:
            try:
                type_id = inst.GetTypeId()
                if type_id and _eid_int(type_id) not in (-1, None):
                    t_elem = doc.GetElement(type_id)
                    if t_elem and isinstance(t_elem, DB.ElementType):
                        type_map[_eid_int(type_id)] = t_elem
            except Exception:
                pass
        return instance_elements, list(type_map.values()), scope_note

    use_all = forms.alert(
        "No elements selected.\nUse all model elements in the active document?",
        title="Parameter Copy",
        yes=True,
        no=True,
    )
    if not use_all:
        return [], [], "Scope: canceled"

    all_instances = []
    collector = DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
    for elem in collector:
        try:
            if elem is None:
                continue
            if not getattr(elem, "Category", None):
                continue
            all_instances.append(elem)
        except Exception:
            continue

    type_map = {}
    for inst in all_instances:
        try:
            type_id = inst.GetTypeId()
            type_id_int = _eid_int(type_id)
            if type_id_int in (None, -1):
                continue
            if type_id_int in type_map:
                continue
            t_elem = doc.GetElement(type_id)
            if t_elem and isinstance(t_elem, DB.ElementType):
                type_map[type_id_int] = t_elem
        except Exception:
            continue

    scope_note = "Scope: all model instances ({})".format(len(all_instances))
    return all_instances, list(type_map.values()), scope_note


def _collect_parameter_catalog(instance_elements, type_elements):
    catalog = {}

    def scan_element_parameters(element, is_instance):
        try:
            for param in element.Parameters:
                definition = getattr(param, "Definition", None)
                if not definition:
                    continue
                name = _safe_text(definition.Name).strip()
                if not name:
                    continue

                param_id_int = _eid_int(param.Id)
                if param_id_int is None:
                    continue

                storage_type = _safe_text(param.StorageType)
                data_key, data_label, discipline_label = _data_type_from_parameter(param)
                origin = _origin_from_parameter(param, param_id_int)
                descriptor_key = "{}|{}".format("I" if is_instance else "T", param_id_int)

                if descriptor_key in catalog:
                    desc = catalog[descriptor_key]
                    if not param.IsReadOnly:
                        desc.has_writable = True
                    continue

                desc = ParamDescriptor(
                    param_id_int=param_id_int,
                    name=name,
                    is_instance=is_instance,
                    origin=origin,
                    storage_type=storage_type,
                    data_key=data_key,
                    data_label=data_label,
                    discipline_label=discipline_label,
                    has_writable=(not param.IsReadOnly),
                )
                catalog[descriptor_key] = desc
        except Exception:
            return

    for inst in instance_elements:
        scan_element_parameters(inst, is_instance=True)
    for typ in type_elements:
        scan_element_parameters(typ, is_instance=False)

    return sorted(catalog.values(), key=lambda x: x.sort_key)


def _are_compatible(source_desc, target_desc):
    return (
        source_desc.is_instance == target_desc.is_instance
        and source_desc.storage_type == target_desc.storage_type
        and source_desc.data_key == target_desc.data_key
    )


class ParameterCopyWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        self.is_ready = False

        self.instance_elements, self.type_elements, scope_note = _collect_scope_elements()
        if not (self.instance_elements or self.type_elements):
            return

        self.all_descriptors = _collect_parameter_catalog(
            self.instance_elements, self.type_elements
        )
        if not self.all_descriptors:
            forms.alert(
                "No parameters found in selected scope.",
                title="Parameter Copy",
            )
            return

        self.source_descriptors = list(self.all_descriptors)
        self.target_descriptors = [x for x in self.all_descriptors if x.has_writable]
        if not self.target_descriptors:
            forms.alert(
                "No writable target parameters found in selected scope.",
                title="Parameter Copy",
            )
            return

        self.scope_tb.Text = scope_note
        self.status_tb.Text = "Loaded {} source / {} target parameters".format(
            len(self.source_descriptors),
            len(self.target_descriptors),
        )

        self._bind_filter_options()
        self._refresh_source_list()
        self._refresh_target_list()
        self.is_ready = True

    def _bind_filter_options(self):
        source_ptypes = [ALL_TOKEN] + sorted(
            {x.origin for x in self.source_descriptors}
        )
        source_dtypes = [ALL_TOKEN] + sorted(
            {x.data_label for x in self.source_descriptors}
        )
        source_discs = [ALL_TOKEN] + sorted(
            {x.discipline_label for x in self.source_descriptors}
        )

        target_ptypes = [ALL_TOKEN] + sorted(
            {x.origin for x in self.target_descriptors}
        )
        target_dtypes = [ALL_TOKEN] + sorted(
            {x.data_label for x in self.target_descriptors}
        )
        target_discs = [ALL_TOKEN] + sorted(
            {x.discipline_label for x in self.target_descriptors}
        )

        self.source_ptype_cb.ItemsSource = source_ptypes
        self.source_dtype_cb.ItemsSource = source_dtypes
        self.source_disc_cb.ItemsSource = source_discs
        self.target_ptype_cb.ItemsSource = target_ptypes
        self.target_dtype_cb.ItemsSource = target_dtypes
        self.target_disc_cb.ItemsSource = target_discs

        self.source_ptype_cb.SelectedIndex = 0
        self.source_dtype_cb.SelectedIndex = 0
        self.source_disc_cb.SelectedIndex = 0
        self.target_ptype_cb.SelectedIndex = 0
        self.target_dtype_cb.SelectedIndex = 0
        self.target_disc_cb.SelectedIndex = 0

        self.source_type_cb.IsChecked = True
        self.source_inst_cb.IsChecked = True
        self.target_type_cb.IsChecked = True
        self.target_inst_cb.IsChecked = True

    def _apply_filters(
        self,
        descriptors,
        search_text,
        ptype_value,
        dtype_value,
        disc_value,
        allow_type,
        allow_instance,
    ):
        search_token = _safe_text(search_text).strip().lower()
        ptype_value = _safe_text(ptype_value)
        dtype_value = _safe_text(dtype_value)
        disc_value = _safe_text(disc_value)

        allow_type = bool(allow_type)
        allow_instance = bool(allow_instance)
        if not allow_type and not allow_instance:
            return []

        filtered = []
        for item in descriptors:
            if search_token and search_token not in item.name.lower():
                continue
            if ptype_value and ptype_value != ALL_TOKEN and item.origin != ptype_value:
                continue
            if dtype_value and dtype_value != ALL_TOKEN and item.data_label != dtype_value:
                continue
            if disc_value and disc_value != ALL_TOKEN and item.discipline_label != disc_value:
                continue
            if item.is_instance and not allow_instance:
                continue
            if (not item.is_instance) and not allow_type:
                continue
            filtered.append(item)
        return filtered

    def _refresh_source_list(self):
        selected_key = None
        try:
            selected = self.source_lb.SelectedItem
            if selected:
                selected_key = selected.key
        except Exception:
            selected_key = None

        filtered = self._apply_filters(
            self.source_descriptors,
            self.source_search_tb.Text,
            self.source_ptype_cb.SelectedItem,
            self.source_dtype_cb.SelectedItem,
            self.source_disc_cb.SelectedItem,
            self.source_type_cb.IsChecked,
            self.source_inst_cb.IsChecked,
        )
        self.source_lb.ItemsSource = filtered

        if selected_key:
            for item in filtered:
                if item.key == selected_key:
                    self.source_lb.SelectedItem = item
                    break

        self.source_count_tb.Text = "{} item(s)".format(len(filtered))

    def _refresh_target_list(self):
        filtered = self._apply_filters(
            self.target_descriptors,
            self.target_search_tb.Text,
            self.target_ptype_cb.SelectedItem,
            self.target_dtype_cb.SelectedItem,
            self.target_disc_cb.SelectedItem,
            self.target_type_cb.IsChecked,
            self.target_inst_cb.IsChecked,
        )
        self.target_lb.ItemsSource = filtered
        self.target_count_tb.Text = "{} item(s)".format(len(filtered))

    def _get_selected_targets(self):
        try:
            return [x for x in self.target_lb.SelectedItems]
        except Exception:
            return []

    def source_filter_changed(self, sender, args):
        self._refresh_source_list()

    def target_filter_changed(self, sender, args):
        self._refresh_target_list()

    def source_selection_changed(self, sender, args):
        source_desc = self.source_lb.SelectedItem
        if not source_desc:
            self.status_tb.Text = "Select one source parameter."
            return
        self.status_tb.Text = (
            "Source: {} | {} | {} | {}".format(
                source_desc.name,
                source_desc.kind_label,
                source_desc.data_label,
                source_desc.origin,
            )
        )

    def select_compatible_targets(self, sender, args):
        source_desc = self.source_lb.SelectedItem
        if not source_desc:
            forms.alert(
                "Select a source parameter first.",
                title="Parameter Copy",
            )
            return

        visible_targets = [x for x in (self.target_lb.ItemsSource or [])]
        compatible = [x for x in visible_targets if _are_compatible(source_desc, x)]

        self.target_lb.UnselectAll()
        for item in compatible:
            try:
                self.target_lb.SelectedItems.Add(item)
            except Exception:
                continue

        self.status_tb.Text = "Selected {} compatible target(s).".format(len(compatible))

    def cancel_click(self, sender, args):
        self.Close()

    def run_click(self, sender, args):
        source_desc = self.source_lb.SelectedItem
        if not source_desc:
            forms.alert(
                "Please select one source parameter.",
                title="Parameter Copy",
            )
            return

        target_descs = self._get_selected_targets()
        if not target_descs:
            forms.alert(
                "Please select one or more target parameters.",
                title="Parameter Copy",
            )
            return

        incompatible = [x for x in target_descs if not _are_compatible(source_desc, x)]
        if incompatible:
            lines = [
                "Selected targets include incompatible parameter types.",
                "Source: {}".format(source_desc.display),
                "",
                "Incompatible targets:",
            ]
            for item in incompatible[:20]:
                lines.append(" - {}".format(item.display))
            forms.alert(
                "\n".join(lines),
                title="Parameter Copy",
            )
            return

        processing_elements = (
            self.instance_elements if source_desc.is_instance else self.type_elements
        )
        if not processing_elements:
            forms.alert(
                "No elements available in scope for this source parameter kind.",
                title="Parameter Copy",
            )
            return

        stats = defaultdict(int)
        sample_ids = defaultdict(set)
        error_rows = []

        with revit.Transaction("Parameter Copy"):
            for elem in processing_elements:
                elem_id_int = _eid_int(elem.Id)
                stats["elements_processed"] += 1

                source_param = _get_param_by_descriptor(elem, source_desc)
                if not source_param:
                    stats["missing_source"] += 1
                    if elem_id_int is not None:
                        sample_ids["missing_source"].add(elem_id_int)
                    continue

                if not _source_has_value(source_param):
                    stats["empty_source"] += 1
                    if elem_id_int is not None:
                        sample_ids["empty_source"].add(elem_id_int)
                    continue

                for target_desc in target_descs:
                    target_param = _get_param_by_descriptor(elem, target_desc)
                    if not target_param:
                        stats["missing_target"] += 1
                        if elem_id_int is not None:
                            sample_ids["missing_target"].add(elem_id_int)
                        continue
                    if target_param.IsReadOnly:
                        stats["readonly_target"] += 1
                        if elem_id_int is not None:
                            sample_ids["readonly_target"].add(elem_id_int)
                        continue

                    try:
                        if _copy_param_value(source_param, target_param):
                            stats["writes"] += 1
                        else:
                            stats["unsupported_storage"] += 1
                            if elem_id_int is not None:
                                sample_ids["unsupported_storage"].add(elem_id_int)
                    except Exception as ex:
                        stats["errors"] += 1
                        if elem_id_int is not None:
                            sample_ids["errors"].add(elem_id_int)
                        if len(error_rows) < 30:
                            error_rows.append("id {} -> {}".format(elem_id_int, ex))

        summary = [
            "Parameter Copy completed.",
            "Source: {}".format(source_desc.display),
            "Targets: {}".format(len(target_descs)),
            "Elements processed: {}".format(stats["elements_processed"]),
            "Values written: {}".format(stats["writes"]),
            "Missing source: {}".format(stats["missing_source"]),
            "Empty source: {}".format(stats["empty_source"]),
            "Missing target: {}".format(stats["missing_target"]),
            "Read-only target: {}".format(stats["readonly_target"]),
            "Unsupported storage: {}".format(stats["unsupported_storage"]),
            "Errors: {}".format(stats["errors"]),
        ]

        def append_sample(label_key, label):
            if not sample_ids[label_key]:
                return
            ids = sorted(sample_ids[label_key])[:20]
            summary.append("{} sample element ids: {}".format(label, ", ".join(str(x) for x in ids)))

        summary.append("")
        append_sample("missing_source", "Missing source")
        append_sample("empty_source", "Empty source")
        append_sample("missing_target", "Missing target")
        append_sample("readonly_target", "Read-only target")
        append_sample("unsupported_storage", "Unsupported storage")
        append_sample("errors", "Errors")

        if error_rows:
            summary.append("")
            summary.append("Error details:")
            summary.extend(error_rows)

        summary_text = "\n".join(summary)
        self.status_tb.Text = "Done. Wrote {} value(s).".format(stats["writes"])
        forms.alert(summary_text, title="Parameter Copy", warn_icon=False)


def main():
    window = ParameterCopyWindow("Script.xaml")
    if not window.is_ready:
        return
    window.ShowDialog()


if __name__ == "__main__":
    main()
