from __future__ import annotations

import inspect
import itertools
import warnings
from typing import Callable

from dash import dependencies
from django.urls import reverse

from django_plotly_dash.app_name import app_name, main_view_label
from django_plotly_dash.app_registry import registry
from django_plotly_dash.dash_wrapper import WrappedDash
from django_plotly_dash.utils import serve_locally as serve_locally_setting
from django_plotly_dash.utils import static_asset_path

#: The keys used to store the parts of a callback.
CALLBACK_PART_KEYS: tuple[str] = "output", "inputs", "state", "prevent_initial_call"

#: The expanded parameters to inject when calling a function.
expanded_parameters: dict[Callable, list[str] | None] = {}


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


class DjangoDash:
    """Wrapper class that provides Dash functionality in a form that can be served by Django.

    To use, construct an instance of DjangoDash() in place of a Dash() one.
    """

    # pylint: disable=too-many-instance-attributes
    def __init__(
        self,
        name: str = None,
        serve_locally: bool | None = None,
        add_bootstrap_links: bool = False,
        suppress_callback_exceptions: bool = False,
        external_stylesheets: list = None,
        external_scripts: list = None,
        **kwargs,
    ):  # pylint: disable=unused-argument, too-many-arguments
        # store arguments to pass them later to the WrappedDash instance
        self.external_stylesheets = external_stylesheets or []
        self.external_scripts = external_scripts or []
        self.kwargs = kwargs
        if kwargs:
            warnings.warn(
                "You are passing extra arguments {kwargs} that will be passed to Dash(...) "
                "but may not be properly handled by django-plotly-dash.".format(
                    kwargs=kwargs
                )
            )

        if name is None:
            self.uid = f"djdash_{len(registry.apps) + 1}"
        else:
            self._uid = name
        self.layout = None
        self._callback_sets = []
        self._clientside_callback_sets = []

        self.css = Holder()
        self.scripts = Holder()

        registry.apps[self._uid] = self

        if serve_locally is None:
            self._serve_locally = serve_locally_setting()
        else:
            self._serve_locally = serve_locally

        self._suppress_callback_exceptions = suppress_callback_exceptions

        if add_bootstrap_links:
            from bootstrap4.bootstrap import css_url

            bootstrap_source = css_url()["href"]

            if self._serve_locally:
                # Ensure package is loaded; if not present then pip install dpd-static-support
                hard_coded_package_name = "dpd_static_support"
                base_file_name = bootstrap_source.split("/")[-1]

                self.css.append_script(
                    {
                        "external_url": [
                            bootstrap_source,
                        ],
                        "relative_package_path": base_file_name,
                        "namespace": hard_coded_package_name,
                    }
                )
            else:
                self.css.append_script(
                    {
                        "external_url": [
                            bootstrap_source,
                        ],
                    }
                )

        # Remember some caller info for static files
        caller_frame = inspect.stack()[1]
        self.caller_module = inspect.getmodule(caller_frame[0])
        try:
            self.caller_module_location = inspect.getfile(self.caller_module)
        except TypeError:
            self.caller_module_location = None
        self.assets_folder = "assets"

    def get_asset_static_url(self, asset_path):
        module_name = self.caller_module.__name__
        return static_asset_path(module_name, asset_path)

    def as_dash_instance(self, cache_id=None):
        """Form a Dash instance, for stateless use of this app."""
        return self.do_form_dash_instance(cache_id=cache_id)

    def handle_current_state(self):
        """Do nothing. Should be overridden for stateful apps."""
        pass

    def update_current_state(self, wid, key, value):
        """Do nothing. Should be overridden for stateful apps."""
        pass

    def have_current_state_entry(self, wid, key):
        """Do nothing. Should be overridden for stateful apps."""
        pass

    def get_base_pathname(
        self, specific_identifier: str | None, cache_id: str | None
    ) -> tuple[str, str]:
        """Return the base pathname for this app, and the unique identifier for this instance.

        Parameters
        ----------
        specific_identifier : str | None
            A specific identifier for this instance, if any.
        cache_id : str | None
            A cache identifier for this instance, if any.

        Returns
        -------
        tuple[str, str]
            The unique identifier and the full URL for this instance.
        """
        if not specific_identifier:
            app_pathname = "%s:app-%s" % (app_name, main_view_label)
            ndid = self._uid
        else:
            app_pathname = "%s:%s" % (app_name, main_view_label)
            ndid = specific_identifier

        kwargs = {"ident": ndid}

        if cache_id:
            kwargs["cache_id"] = cache_id
            app_pathname = app_pathname + "--args"

        full_url = reverse(app_pathname, kwargs=kwargs)
        if full_url[-1] != "/":
            full_url = full_url + "/"
        return ndid, full_url

    def do_form_dash_instance(
        self,
        replacements: dict | None = None,
        specific_identifier: str | None = None,
        cache_id: str | None = None,
    ) -> WrappedDash:
        """Form a Dash instance, for stateless use of this app.

        Parameters
        ----------
        replacements : dict | None
            A dictionary of replacements to apply to the layout.
        specific_identifier : str | None
            A specific identifier for this instance, if any.
        cache_id : str | None
            A cache identifier for this instance, if any.

        Returns
        -------
        WrappedDash
            A Dash instance.
        """
        ndid, base_pathname = self.get_base_pathname(specific_identifier, cache_id)
        return self.form_dash_instance(replacements, ndid, base_pathname)

    def form_dash_instance(
        self,
        replacements: dict | None = None,
        ndid: str | None = None,
        base_pathname: str | None = None,
    ) -> WrappedDash:
        """Construct a Dash instance taking into account state

        Parameters
        ----------
        replacements : dict | None
            A dictionary of replacements to apply to the layout.
        ndid : _type_, optional
            _description_, by default None.
        base_pathname : str | None
            The base pathname for this instance, by default None.

        Returns
        -------
        WrappedDash
            A wrapped Dash instance.
        """

        if ndid is None:
            ndid = self._uid

        rd = WrappedDash(
            base_pathname=base_pathname,
            replacements=replacements,
            ndid=ndid,
            serve_locally=self._serve_locally,
            external_stylesheets=self.external_stylesheets,
            external_scripts=self.external_scripts,
            **self.kwargs,
        )

        rd.layout = self.layout
        rd.config["suppress_callback_exceptions"] = self._suppress_callback_exceptions

        for cb, func in self._callback_sets:
            rd.callback(**cb)(func)
        for cb in self._clientside_callback_sets:
            rd.clientside_callback(**cb)
        for s in self.css.items:
            rd.css.append_css(s)
        for s in self.scripts.items:
            rd.scripts.append_script(s)

        return rd

    @staticmethod
    def get_expanded_arguments(
        func: Callable, inputs: dict | None, state: dict | None
    ) -> list | None:
        """Analyse a callback function signature to detect the expanded arguments to add when called.
        It uses the inputs and the state information to identify what arguments are already coming from Dash.

        It returns a list of the expanded parameters to inject (can be [] if nothing should be injected)
        or None if all parameters should be injected.

        Parameters
        ----------
        func : Callable
            The function to analyse.
        inputs : dict | None
            The inputs to the function.
        state : dict | None
            The state of the function.

        Returns
        -------
        list | None
            The expanded arguments to add when called.
        """
        n_dash_parameters = len(inputs or []) + len(state or [])

        parameters_by_kind = {
            kind: [p.name for p in parameters]
            for kind, parameters in itertools.groupby(
                inspect.signature(func).parameters.values(), lambda p: p.kind
            )
        }
        keyword_only = parameters_by_kind.get(inspect.Parameter.KEYWORD_ONLY, [])
        if inspect.Parameter.VAR_KEYWORD in parameters_by_kind:
            # there is some **kwargs, inject all parameters
            return
        elif inspect.Parameter.VAR_POSITIONAL in parameters_by_kind:
            # there is a *args, assume all parameters afterwards (KEYWORD_ONLY) are to be injected
            # some of these parameters may not be expanded arguments but that is ok
            return keyword_only
        else:
            # there is no **kwargs, filter argMap to take only the keyword arguments
            non_dash_parameters = parameters_by_kind.get(
                inspect.Parameter.POSITIONAL_OR_KEYWORD, []
            )[n_dash_parameters:]
            return non_dash_parameters + keyword_only

    def callback(self, *args, **kwargs):
        """Form a callback function by wrapping, in the same way as the underlying Dash application would
        but handling extra arguments provided by dpd.

        It will inspect the signature of the function to ensure only relevant expanded arguments are passed to the callback.

        If the function accepts a **kwargs => all expanded arguments are sent to the function in the kwargs.
        If the function has a *args => expanded arguments matching parameters after the *args are injected.
        Otherwise, take all arguments beyond the one provided by Dash (based on the Inputs/States provided).
        """
        callback_parts = dependencies.handle_callback_args(args, kwargs)
        callback_set = dict(zip(CALLBACK_PART_KEYS, callback_parts))

        def wrap_func(func: Callable):
            self._callback_sets.append((callback_set, func))
            # add an expanded attribute to the function with the information to use in dispatch_with_args
            # to inject properly only the expanded arguments the function can accept
            # if .expanded is None => inject all
            # if .expanded is a list => inject only
            expanded_parameters[func.__qualname__] = self.get_expanded_arguments(
                func,
                callback_set["inputs"],
                callback_set["state"],
            )
            return func

        return wrap_func

    expanded_callback = callback

    def clientside_callback(self, clientside_function: Callable, *args, **kwargs):
        """Form a clientside callback function by wrapping, in the same way as the underlying Dash application would.

        Parameters
        ----------
        clientside_function : Callable
            The client-side function to wrap.
        """
        output, inputs, state, prevent_initial_call = dependencies.handle_callback_args(
            args, kwargs
        )
        callback_set = {
            "clientside_function": clientside_function,
            "output": output,
            "inputs": inputs,
            "state": state,
            "prevent_initial_call": prevent_initial_call,
        }
        self._clientside_callback_sets.append(callback_set)

    def get_asset_url(self, asset_name: str) -> str:
        """URL of an asset associated with this component.

        Use a placeholder and insert later.
        """

        return f"assets/{asset_name}"
        # return self.as_dash_instance().get_asset_url(asset_name)
