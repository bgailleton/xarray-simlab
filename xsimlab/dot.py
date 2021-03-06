"""
Model visualization using graphviz/dot.

Part of the code below is copied and modified from:

- dask 0.14.3 (Copyright (c) 2014-2015, Continuum Analytics, Inc.
  and contributors)
  Licensed under the BSD 3 License
  http://dask.pydata.org

"""
import os
from functools import partial

from .utils import variables_dict, import_required, maybe_to_list
from .variable import VarIntent, VarType


graphviz = import_required(
    "graphviz",
    "Drawing dask graphs requires the "
    "`graphviz` python library and the "
    "`graphviz` system library to be "
    "installed.",
)


PROC_NODE_ATTRS = {
    "shape": "oval",
    "color": "#3454b4",
    "fontcolor": "#131f43",
    "style": "filled",
    "fillcolor": "#c6d2f6",
}
PROC_EDGE_ATTRS = {"color": "#3454b4", "style": "bold"}
INPUT_NODE_ATTRS = {
    "shape": "box",
    "color": "#b49434",
    "fontcolor": "#2d250d",
    "style": "filled",
    "fillcolor": "#f3e3b3",
}
INPUT_EDGE_ATTRS = {"arrowhead": "none", "color": "#b49434"}
VAR_NODE_ATTRS = {"shape": "box", "color": "#555555", "fontcolor": "#555555"}
VAR_EDGE_ATTRS = {"arrowhead": "none", "color": "#555555"}


def _hash_variable(var):
    # issue with variables with the same name declared in different processes
    # return str(hash(var))
    return str(id(var))


def _get_target_keys(p_obj, var_name):
    return maybe_to_list(
        p_obj.__xsimlab_state_keys__.get(var_name, [])
    ) + maybe_to_list(p_obj.__xsimlab_od_keys__.get(var_name, []))


class _GraphBuilder:
    def __init__(self, model, graph_attr):
        self.model = model
        self.g = graphviz.Digraph(graph_attr=graph_attr)

    def add_processes(self):
        seen = set()

        for p_name, p_obj in self.model._processes.items():
            if p_name not in seen:
                seen.add(p_name)
                self.g.node(p_name, label=p_name, **PROC_NODE_ATTRS)

            for dep_p_name in self.model.dependent_processes[p_name]:
                self.g.edge(dep_p_name, p_name, **PROC_EDGE_ATTRS)

    def _add_var(self, var, p_name):
        if (p_name, var.name) in self.model._input_vars:
            node_attrs = INPUT_NODE_ATTRS.copy()
            edge_attrs = INPUT_EDGE_ATTRS.copy()
        else:
            node_attrs = VAR_NODE_ATTRS.copy()
            edge_attrs = VAR_EDGE_ATTRS.copy()

        var_key = _hash_variable(var)
        var_intent = var.metadata["intent"]
        var_type = var.metadata["var_type"]

        if var_type == VarType.ON_DEMAND:
            node_attrs["style"] = "diagonals"

        elif var_type == VarType.FOREIGN:
            node_attrs["style"] = "dashed"
            edge_attrs["style"] = "dashed"

        elif var_type == VarType.GROUP:
            node_attrs["shape"] = "box3d"

        if var_intent == VarIntent.OUT:
            edge_attrs.update({"arrowhead": "empty"})
            edge_ends = p_name, var_key
        else:
            edge_ends = var_key, p_name

        self.g.node(var_key, label=var.name, **node_attrs)
        self.g.edge(*edge_ends, weight="200", **edge_attrs)

    def add_inputs(self):
        for p_name, var_name in self.model._input_vars:
            p_cls = type(self.model[p_name])
            var = variables_dict(p_cls)[var_name]

            self._add_var(var, p_name)

    def add_variables(self):
        for p_name, p_obj in self.model._processes.items():
            p_cls = type(p_obj)

            for var_name, var in variables_dict(p_cls).items():
                self._add_var(var, p_name)

    def add_var_and_targets(self, p_name, var_name):
        this_p_name = p_name
        this_var_name = var_name

        this_p_obj = self.model._processes[this_p_name]
        this_target_keys = _get_target_keys(this_p_obj, this_var_name)

        for p_name, p_obj in self.model._processes.items():
            p_cls = type(p_obj)

            for var_name, var in variables_dict(p_cls).items():
                target_keys = _get_target_keys(p_obj, var_name)

                if (p_name, var_name) == (this_p_name, this_var_name) or len(
                    set(target_keys) & set(this_target_keys)
                ):
                    self._add_var(var, p_name)

    def get_graph(self):
        return self.g


def to_graphviz(
    model,
    rankdir="LR",
    show_only_variable=None,
    show_inputs=False,
    show_variables=False,
    graph_attr={},
    **kwargs,
):
    graph_attr = graph_attr or {}
    graph_attr["rankdir"] = rankdir
    graph_attr.update(kwargs)

    builder = _GraphBuilder(model, graph_attr)

    builder.add_processes()

    if show_only_variable is not None:
        p_name, var_name = show_only_variable
        builder.add_var_and_targets(p_name, var_name)

    elif show_variables:
        builder.add_variables()

    elif show_inputs:
        builder.add_inputs()

    return builder.get_graph()


IPYTHON_IMAGE_FORMATS = frozenset(["jpeg", "png"])
IPYTHON_NO_DISPLAY_FORMATS = frozenset(["dot", "pdf"])


def _get_display_cls(format):
    """
    Get the appropriate IPython display class for `format`.

    Returns `IPython.display.SVG` if format=='svg', otherwise
    `IPython.display.Image`.

    If IPython is not importable, return dummy function that swallows its
    arguments and returns None.
    """
    dummy = lambda *args, **kwargs: None
    try:
        import IPython.display as display
    except ImportError:
        # Can't return a display object if no IPython.
        return dummy

    if format in IPYTHON_NO_DISPLAY_FORMATS:
        # IPython can't display this format natively, so just return None.
        return dummy
    elif format in IPYTHON_IMAGE_FORMATS:
        # Partially apply `format` so that `Image` and `SVG` supply a uniform
        # interface to the caller.
        return partial(display.Image, format=format)
    elif format == "svg":
        return display.SVG
    else:
        raise ValueError(f"Unknown format '{format}' passed to `dot_graph`")


def dot_graph(
    model,
    filename=None,
    format=None,
    show_only_variable=None,
    show_inputs=False,
    show_variables=False,
    **kwargs,
):
    """
    Render a model as a graph using dot.

    Parameters
    ----------
    model : object
        The Model instance to display.
    filename : str or None, optional
        The name (without an extension) of the file to write to disk. If
        `filename` is None (default), no file will be written, and we
        communicate with dot using only pipes.
    format : {'png', 'pdf', 'dot', 'svg', 'jpeg', 'jpg'}, optional
        Format in which to write output file.  Default is 'png'.
    show_only_variable : tuple, optional
        Show only a variable (and all other variables sharing the
        same value) given as a tuple ``(process_name, variable_name)``.
        Deactivated by default.
    show_inputs : bool, optional
        If True, show all input variables in the graph (default: False).
        Ignored if `show_only_variable` is not None.
    show_variables : bool, optional
        If True, show also the other variables (default: False).
        Ignored if `show_only_variable` is not None.
    **kwargs
        Additional keyword arguments to forward to `to_graphviz`.

    Returns
    -------
    result : None or IPython.display.Image or IPython.display.SVG
        (See below.)

    Notes
    -----
    If IPython is installed, we return an IPython.display object in the
    requested format.  If IPython is not installed, we just return None.
    We always return None if format is 'pdf' or 'dot', because IPython can't
    display these formats natively. Passing these formats with filename=None
    will not produce any useful output.

    See Also
    --------
    to_graphviz

    """
    g = to_graphviz(
        model,
        show_only_variable=show_only_variable,
        show_inputs=show_inputs,
        show_variables=show_variables,
        **kwargs,
    )

    if filename is None:
        filename = ""

    fmts = [".png", ".pdf", ".dot", ".svg", ".jpeg", ".jpg"]
    if format is None and any(filename.lower().endswith(fmt) for fmt in fmts):
        filename, format = os.path.splitext(filename)
        format = format[1:].lower()

    if format is None:
        format = "png"

    data = g.pipe(format=format)
    if not data:  # pragma: no cover
        raise RuntimeError(
            "Graphviz failed to properly produce an image. "
            "This probably means your installation of graphviz "
            "is missing png support. See: "
            "https://github.com/ContinuumIO/anaconda-issues/"
            "issues/485 for more information."
        )

    display_cls = _get_display_cls(format)

    if not filename:
        return display_cls(data=data)

    full_filename = ".".join([filename, format])
    with open(full_filename, "wb") as f:
        f.write(data)

    return display_cls(filename=full_filename)
