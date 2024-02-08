"""
dash_wrapper

This module provides a DjangoDash class that can be used to
expose a Plotly Dasb application through a Django server

Copyright (c) 2018 Gibbs Consulting and others - see CONTRIBUTIONS.md

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import dash
from dash import Dash
from dash._utils import inputs_to_dict, split_callback_id
from django.utils.text import slugify
from flask import Flask

from django_plotly_dash.middleware import EmbeddedHolder
from django_plotly_dash.pseudo_flask import PseudoFlask
from django_plotly_dash.utils import DjangoPlotlyJSONEncoder


@dataclass(frozen=True)
class CallbackContext:
    inputs_list: list
    inputs: dict
    states_list: list
    states: dict
    outputs_list: list
    outputs: dict
    triggered: list


class Holder:
    """Helper class for holding configuration options."""

    def __init__(self):
        self.items = []

    def append_css(self, stylesheet):
        """Add an extra CSS file name to the component package."""
        self.items.append(stylesheet)

    def append_script(self, script):
        """Add an extra script file name to the component package."""
        self.items.append(script)


def wid2str(wid):
    """Convert a Python ID (``str`` or ``dict``) into its Dash representation.

    References
    ---------
    - https://github.com/plotly/dash/blob/c5ba38f0ae7b7f8c173bda10b4a8ddd035f1d867/dash-renderer/src/actions/dependencies.js#L114
    """
    if isinstance(wid, str):
        return wid
    data = ",".join(f"{json.dumps(k)}:{json.dumps(v)}" for k, v in sorted(wid.items()))
    return f"{{{data}}}"


class WrappedDash(Dash):
    """Wrapper around the Plotly Dash application instance."""

    # pylint: disable=too-many-arguments, too-many-instance-attributes
    def __init__(
        self,
        base_pathname: str | None = None,
        replacements: dict | None = None,
        ndid: str = None,
        serve_locally: bool = False,
        **kwargs,
    ):
        self._uid = ndid

        self._flask_app = Flask(self._uid)
        self._notflask = PseudoFlask()
        self._base_pathname = base_pathname

        kwargs["url_base_pathname"] = self._base_pathname
        kwargs["server"] = self._notflask

        super().__init__(__name__, **kwargs)

        self.css.config.serve_locally = serve_locally
        self.scripts.config.serve_locally = serve_locally

        self._adjust_id = False
        self._replacements = replacements or {}
        self._use_dash_layout = len(self._replacements) < 1

        self._return_embedded = False

    def use_dash_dispatch(self):
        """Return True if underlying dash dispatching should be used.

        This stub is present to allow older code to work. Following PR #304
        (see https://github.com/GibbsConsulting/django-plotly-dash/pull/304/files for
        details) this function is no longer needed and therefore should always
        return False"""
        return False

    def use_dash_layout(self):
        """Indicate if the underlying Dash layout can be used.

        If application state is in use, then the underlying dash layout functionality has to be
        augmented with the state information and this function returns False
        """
        return self._use_dash_layout

    def augment_initial_layout(
        self, base_response, initial_arguments: dict | None = None
    ) -> tuple[dict, str]:
        """Add application state to initial values, if needed.

        Parameters
        ----------
        base_response : _type_
            _description_
        initial_arguments : dict | None
            _description_, by default None

        Returns
        -------
        tuple[dict, str]
            The augmented initial layout and the mimetype of the response.
        """
        if self.use_dash_layout() and not initial_arguments and False:
            return base_response.data, base_response.mimetype

        initial_arguments = initial_arguments or {}

        # Adjust the base layout response
        baseDataInBytes = base_response.data
        baseData = json.loads(baseDataInBytes.decode("utf-8"))

        # Define overrides as self._replacements updated with initial_arguments
        overrides = {**self._replacements, **initial_arguments}

        # Walk tree. If at any point we have an element whose id
        # matches, then replace any named values at this level
        reworked_data = self.walk_tree_and_replace(baseData, overrides)

        response_data = json.dumps(reworked_data, cls=DjangoPlotlyJSONEncoder)

        return response_data, base_response.mimetype

    def walk_tree_and_extract(self, data: dict | list, target: dict) -> None:
        """Walk tree of properties and extract identifiers and associated values.

        Parameters
        ----------
        data : dict | list
            The data to walk.
        target : dict
            The target dictionary to populate.
        """
        if isinstance(data, dict):
            for key in ["children", "props"]:
                self.walk_tree_and_extract(data.get(key, None), target)
            ident = data.get("id", None)
            if ident is not None:
                ident = wid2str(ident)
                idVals = target.get(ident, {})
                for key, value in data.items():
                    if key not in ["props", "options", "children", "id"]:
                        idVals[key] = value
                if idVals:
                    target[ident] = idVals
        if isinstance(data, list):
            for element in data:
                self.walk_tree_and_extract(element, target)

    def walk_tree_and_replace(self, data: dict, overrides: dict) -> dict:
        """Walk the tree. Rely on JSON decoding to insert instances of ``dict`` and ``list``.

        Parameters
        ----------
        data : dict
            The data to walk.
        overrides : dict
            The dictionary of replacements to apply.

        Returns
        -------
        dict
            The updated data.
        """
        if isinstance(data, dict):
            response = {}
            replacements = {}
            # look for id entry
            thisID = data.get("id", None)
            if isinstance(thisID, dict):
                # handle case of thisID being a dict (pattern) => linear search in overrides dict
                thisID = wid2str(thisID)
                for k, v in overrides.items():
                    if thisID == k:
                        replacements = v
                        break
            elif thisID is not None:
                # handle standard case of string thisID => key lookup
                replacements = overrides.get(thisID, {})
            # walk all keys and replace if needed
            for k, v in data.items():
                r = replacements.get(k, None)
                if r is None:
                    r = self.walk_tree_and_replace(v, overrides)
                response[k] = r
            return response
        if isinstance(data, list):
            # process each entry in turn and return
            return [self.walk_tree_and_replace(x, overrides) for x in data]
        return data

    def flask_app(self) -> Flask:
        """Underlying flask application for stub implementation.

        Returns
        -------
        Flask
            The underlying flask application.
        """
        return self._flask_app

    def base_url(self) -> str:
        """Base URL of this component.

        Returns
        -------
        str
            The base URL of this component.
        """
        return self._base_pathname

    def app_context(self, *args, **kwargs) -> dict:
        """Returns the application context from underlying flask application.

        Returns
        -------
        dict
            The application context.
        """
        return self._flask_app.app_context(*args, **kwargs)

    def test_request_context(self, *args, **kwargs):
        """Returns a test request context from underlying flask application."""
        return self._flask_app.test_request_context(*args, **kwargs)

    def locate_endpoint_function(self, name: str | None = None):
        """Locate endpoint function given name of view.

        Parameters
        ----------
        name : str | None, optional
            The name of the view, by default None.
        """
        ep = self._base_pathname if name is None else f"{self._base_pathname}_{name}"
        return self._notflask.endpoints[ep]["view_func"]

    # pylint: disable=no-member
    @Dash.layout.setter
    def layout(self, value: str):
        """Overloaded layout function to fix component names as needed.

        Parameters
        ----------
        value : str
            The layout value to set.
        """

        if self._adjust_id:
            self._fix_component_id(value)
        return Dash.layout.fset(self, value)

    def _fix_component_id(self, component):
        """Fix the name of a component and all of its children."""
        component_id = getattr(component, "id", None)
        if component_id is not None:
            setattr(component, "id", self._fix_id(component_id))
        with suppress(Exception):
            for c in component.children:
                self._fix_component_id(c)

    def _fix_id(self, name: str) -> str:
        """Adjust an identifier to include the component name.

        Parameters
        ----------
        name : str
            The name to adjust.

        Returns
        -------
        str
            The adjusted name.
        """
        if not self._adjust_id:
            return name
        return f"{self._uid}_-_{name}"

    def _fix_callback_item(self, item):
        """Update component identifier."""
        item.component_id = self._fix_id(item.component_id)
        return item

    def callback(self, output, inputs, state, prevent_initial_call):
        """Invoke callback, adjusting variable names as needed."""
        if isinstance(output, (list, tuple)):
            fixed_outputs = [self._fix_callback_item(x) for x in output]
        else:
            fixed_outputs = self._fix_callback_item(output)

        return super().callback(
            fixed_outputs,
            [self._fix_callback_item(x) for x in inputs],
            [self._fix_callback_item(x) for x in state],
            prevent_initial_call=prevent_initial_call,
        )

    def clientside_callback(
        self, clientside_function, output, inputs, state, prevent_initial_call
    ):  # pylint: disable=dangerous-default-value
        """Invoke callback, adjusting variable names as needed."""
        if isinstance(output, (list, tuple)):
            fixed_outputs = [self._fix_callback_item(x) for x in output]
        else:
            fixed_outputs = self._fix_callback_item(output)

        return super().clientside_callback(
            clientside_function,
            fixed_outputs,
            [self._fix_callback_item(x) for x in inputs],
            [self._fix_callback_item(x) for x in state],
            prevent_initial_call=prevent_initial_call,
        )

    # pylint: disable=too-many-locals
    def dispatch_with_args(self, body: dict[str, Any], argMap: dict[str, Any]):
        """Perform callback dispatching, with enhanced arguments and recording of response."""
        inputs_list = body.get("inputs", [])
        input_values = inputs_to_dict(inputs_list)
        states = body.get("state", [])
        output = body["output"]
        outputs_list = body.get("outputs") or split_callback_id(output)
        changed_props = body.get("changedPropIds", [])
        triggered_inputs = [
            {"prop_id": x, "value": input_values.get(x)} for x in changed_props
        ]

        callback_context_info = {
            "inputs_list": inputs_list,
            "inputs": input_values,
            "states_list": states,
            "states": inputs_to_dict(states),
            "outputs_list": outputs_list,
            "outputs": outputs_list,
            "triggered": triggered_inputs,
        }

        callback_context = CallbackContext(**callback_context_info)

        # Overload dash global variable
        dash.callback_context = callback_context

        # Add context to arg map, if extended callbacks in use
        if len(argMap) > 0:
            argMap["callback_context"] = callback_context

        single_case = not (output.startswith("..") and output.endswith(".."))
        if single_case:
            # single Output (not in a list)
            outputs = [output]
        else:
            # multiple outputs in a list (the list could contain a single item)
            outputs = output[2:-2].split("...")

        da = argMap.get("dash_app", None)

        callback_info = self.callback_map[output]

        args = []

        for c in inputs_list + states:
            if isinstance(c, list):  # ALL, ALLSMALLER
                v = [ci.get("value") for ci in c]
                if da:
                    for ci, vi in zip(c, v):
                        da.update_current_state(ci["id"], ci["property"], vi)
            else:
                v = c.get("value")
                if da:
                    da.update_current_state(c["id"], c["property"], v)

            args.append(v)

        # Dash 1.11 introduces a set of outputs
        outputs_list = body.get("outputs") or split_callback_id(output)
        argMap["outputs_list"] = outputs_list

        # Special: intercept case of insufficient arguments
        # This happens when a property has been updated with a pipe component
        # TODO see if this can be attacked from the client end

        if len(args) < len(callback_info["inputs"]):
            return "EDGECASEEXIT"

        callback = callback_info["callback"]
        # smart injection of parameters if .expanded is defined
        if callback.expanded is not None:
            parameters_to_inject = {*callback.expanded, "outputs_list"}
            res = callback(
                *args, **{k: v for k, v in argMap.items() if k in parameters_to_inject}
            )
        else:
            res = callback(*args, **argMap)

        if da:
            root_value = json.loads(res).get("response", {})
            for output_item in outputs:
                if isinstance(output_item, str):
                    output_id, output_property = output_item.split(".")
                    if da.have_current_state_entry(output_id, output_property):
                        value = root_value.get(output_id, {}).get(output_property)
                        da.update_current_state(output_id, output_property, value)
                else:
                    # todo: implement saving of state for pattern matching ouputs
                    raise NotImplementedError(
                        "Updating state for dict keys (pattern matching) is not yet implemented"
                    )
        return res

    def slugified_id(self) -> str:
        """Return the app ID in a slug-friendly form.

        Returns
        -------
        str
            The slugified ID.
        """
        return slugify(self._uid)

    def extra_html_properties(
        self,
        prefix: str = "django-plotly-dash",
        postfix: str = "",
        template_type: str = "iframe",
    ):
        """Return extra HTML properties to allow individual apps to be styled separately.

        The content returned from this function is injected unescaped into templates.
        """
        post_part = f"-{postfix}" if postfix else ""
        slugified_id = self.slugified_id()
        return (
            f"{prefix} {prefix}-{template_type} {prefix}-app-{slugified_id}{post_part}"
        )

    def index(self, *args, **kwargs):  # pylint: disable=unused-argument
        scripts = self._generate_scripts_html()
        css = self._generate_css_dist_html()
        config = self._generate_config_html()
        metas = self._generate_meta_html()
        renderer = self._generate_renderer()
        title = getattr(self, "title", "Dash")
        if self._favicon:
            import flask

            favicon = '<link rel="icon" type="image/x-icon" href="{}">'.format(
                flask.url_for("assets.static", filename=self._favicon)
            )
        else:
            favicon = ""
            _app_entry = """
<div id="react-entry-point">
  <div class="_dash-loading">
    Loading...
  </div>
</div>
"""
        index = self.interpolate_index(
            metas=metas,
            title=title,
            css=css,
            config=config,
            scripts=scripts,
            app_entry=_app_entry,
            favicon=favicon,
            renderer=renderer,
        )
        return index

    def interpolate_index(self, **kwargs):  # pylint: disable=arguments-differ
        if not self._return_embedded:
            resp = super().interpolate_index(**kwargs)
            return resp
        self._return_embedded.add_css(kwargs["css"])
        self._return_embedded.add_config(kwargs["config"])
        self._return_embedded.add_scripts(kwargs["scripts"])
        return kwargs["app_entry"]

    def set_embedded(self, embedded_holder: EmbeddedHolder | None = None) -> None:
        """Set a handler for embedded references prior to evaluating a view function."""
        self._return_embedded = embedded_holder if embedded_holder else EmbeddedHolder()

    def exit_embedded(self) -> None:
        """Exit the embedded section after processing a view."""
        self._return_embedded = False
