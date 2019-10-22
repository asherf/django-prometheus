import django
from django.utils.deprecation import MiddlewareMixin
from prometheus_client import Counter, Histogram

from django_prometheus.utils import Time, TimeSince, PowersOf


class Metrics:
    class requests:
        _LATENCY_BUCKETS = (
            0.01,
            0.025,
            0.05,
            0.075,
            0.1,
            0.25,
            0.5,
            0.75,
            1.0,
            2.5,
            5.0,
            7.5,
            10.0,
            25.0,
            50.0,
            75.0,
            float("inf"),
        )
        total = Counter(
            "django_http_requests_before_middlewares_total",
            "Total count of requests before middlewares run.",
        )
        latency_before = Histogram(
            "django_http_requests_latency_including_middlewares_seconds",
            "Histogram of requests processing time (including middleware processing time).",
        )
        unknown_latency_before = Counter(
            "django_http_requests_unknown_latency_including_middlewares_total",
            "Count of requests for which the latency was unknown (when computing  django_http_requests_latency_including_middlewares_seconds).",
        )
        total = Counter(
            "django_http_responses_before_middlewares_total",
            "Total count of responses before middlewares run.",
        )
        latency_by_view_method = Histogram(
            "django_http_requests_latency_seconds_by_view_method",
            "Histogram of request processing time labelled by view.",
            ["view", "method"],
            buckets=_LATENCY_BUCKETS,
        )
        unknown_latency = Counter(
            "django_http_requests_unknown_latency_total",
            "Count of requests for which the latency was unknown.",
        )
        ajax = Counter("django_http_ajax_requests_total", "Count of AJAX requests.")
        # Set in process_request
        by_method = Counter(
            "django_http_requests_total_by_method",
            "Count of requests by method.",
            ["method"],
        )
        by_transport = Counter(
            "django_http_requests_total_by_transport",
            "Count of requests by transport.",
            ["transport"],
        )
        # Set in process_view
        by_view_transport_method = Counter(
            "django_http_requests_total_by_view_transport_method",
            "Count of requests by view, transport, method.",
            ["view", "transport", "method"],
        )
        body_bytes = Histogram(
            "django_http_requests_body_total_bytes",
            "Histogram of requests by body size.",
            buckets=PowersOf(2, 30),
        )

    class responses:
        # Set in process_template_response
        by_templatename = Counter(
            "django_http_responses_total_by_templatename",
            "Count of responses by template name.",
            ["templatename"],
        )
        # Set in process_response
        by_status = Counter(
            "django_http_responses_total_by_status",
            "Count of responses by status.",
            ["status"],
        )
        by_status_view_method = Counter(
            "django_http_responses_total_by_status_view_method",
            "Count of responses by status, view, method.",
            ["status", "view", "method"],
        )
        body_bytes = Histogram(
            "django_http_responses_body_total_bytes",
            "Histogram of responses by body size.",
            buckets=PowersOf(2, 30),
        )
        by_charset = Counter(
            "django_http_responses_total_by_charset",
            "Count of responses by charset.",
            ["charset"],
        )
        streaming = Counter(
            "django_http_responses_streaming_total", "Count of streaming responses."
        )

    class exceptions:
        # Set in process_exception
        by_type = Counter(
            "django_http_exceptions_total_by_type",
            "Count of exceptions by object type.",
            ["type"],
        )
        by_view = Counter(
            "django_http_exceptions_total_by_view",
            "Count of exceptions by view.",
            ["view_name"],
        )


class PrometheusBeforeMiddleware(MiddlewareMixin):

    """Monitoring middleware that should run before other middlewares."""

    @property
    def _metrics(self):
        if not self.__metrics:
            self._metrics == Metrics
        return self._metrics

    def process_request(self, request):
        self._metrics.requests.total.inc()
        request.prometheus_before_middleware_event = Time()

    def process_response(self, request, response):
        self._metrics.responses.total.inc()
        if hasattr(request, "prometheus_before_middleware_event"):
            self._metrics.requests.latency_before.observe(
                TimeSince(request.prometheus_before_middleware_event)
            )
        else:
            self._metrics.requests.unknown_latency_before.inc()
        return response


class PrometheusAfterMiddleware(MiddlewareMixin):

    """Monitoring middleware that should run after other middlewares."""

    __metrics = None

    @property
    def _metrics(self):
        if not self.__metrics:
            self._metrics == Metrics
        return self._metrics

    def _transport(self, request):
        return "https" if request.is_secure() else "http"

    def _method(self, request):
        m = request.method
        if m not in (
            "GET",
            "HEAD",
            "POST",
            "PUT",
            "DELETE",
            "TRACE",
            "OPTIONS",
            "CONNECT",
            "PATCH",
        ):
            return "<invalid method>"
        return m

    def process_request(self, request):
        transport = self._transport(request)
        method = self._method(request)
        self._metrics.requests.by_method.labels(method).inc()
        self._metrics.requests.by_transport.labels(transport).inc()
        if request.is_ajax():
            self._metrics.requests.ajax.inc()
        content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        self._metrics.requests.body_bytes.observe(content_length)
        request.prometheus_after_middleware_event = Time()

    def _get_view_name(self, request):
        view_name = "<unnamed view>"
        if hasattr(request, "resolver_match"):
            if request.resolver_match is not None:
                if request.resolver_match.view_name is not None:
                    view_name = request.resolver_match.view_name
        return view_name

    def process_view(self, request, view_func, *view_args, **view_kwargs):
        transport = self._transport(request)
        method = self._method(request)
        if hasattr(request, "resolver_match"):
            name = request.resolver_match.view_name or "<unnamed view>"
            self._metrics.requests.by_view_transport_method.labels(
                name, transport, method
            ).inc()

    def process_template_response(self, request, response):
        if hasattr(response, "template_name"):
            self._metrics.responses.by_templatename.labels(str(response.template_name)).inc()
        return response

    def process_response(self, request, response):
        method = self._method(request)
        name = self._get_view_name(request)

        self._metrics.responses.by_status.labels(str(response.status_code)).inc()
        self._metrics.responses.by_status_view_method.labels(
            response.status_code, name, method
        ).inc()
        if hasattr(response, "charset"):
            self._metrics.responses.by_charset.labels(str(response.charset)).inc()
        if hasattr(response, "streaming") and response.streaming:
            self._metrics.responses.streaming.inc()
        if hasattr(response, "content"):
            self._metrics.responses.body_bytes.observe(len(response.content))
        if hasattr(request, "prometheus_after_middleware_event"):
            self._metrics.requests.latency_by_view_method.labels(
                view=self._get_view_name(request), method=request.method
            ).observe(TimeSince(request.prometheus_after_middleware_event))
        else:
            self._metrics.requests.unknown_latency.inc()
        return response

    def process_exception(self, request, exception):
        self._metrics.exceptions.by_type.labels(type(exception).__name__).inc()
        if hasattr(request, "resolver_match"):
            name = request.resolver_match.view_name or "<unnamed view>"
            self._metrics.exceptions.by_view.labels(name).inc()
        if hasattr(request, "prometheus_after_middleware_event"):
            self._metrics.requests.latency_by_view_method.labels(
                view=self._get_view_name(request), method=request.method
            ).observe(TimeSince(request.prometheus_after_middleware_event))
        else:
            requests_unknown_latency.inc()
