from django.test import TransactionTestCase, override_settings
from django_prometheus.middleware import (
    Metrics,
    PrometheusAfterMiddleware,
    PrometheusBeforeMiddleware,
)
from django_prometheus.testutils import PrometheusTestCaseMixin
from testapp.helpers import get_middleware
from testapp.test_middleware import M, T

EXTENDED_METRICS = [
    M("requests_latency_seconds_by_view_method"),
    M("responses_total_by_status_view_method"),
]


class CustomMetrics(Metrics):
    def register_metric(
        self, metric_cls, name, documentation, labelnames=tuple(), **kwargs
    ):
        if name in EXTENDED_METRICS:
            labelnames.extend(("view_type", "user_agent_type"))
        return super(CustomMetrics, self).register_metric(
            metric_cls, name, documentation, labelnames=labelnames, **kwargs
        )


class AppMetricsBeforeMiddleware(PrometheusBeforeMiddleware):
    metrics_cls = CustomMetrics


class AppMetricsAfterMiddleware(PrometheusAfterMiddleware):
    metrics_cls = CustomMetrics

    def label_metric(self, metric, request, response=None, **labels):
        new_labels = labels
        if metric._name in EXTENDED_METRICS:
            new_labels = {"view_type": "foo", "user_agent_type": "browser"}
            new_labels.update(labels)
            print(f"ASHER: Add labels {new_labels} - {metric._name} - {metric._labelnames}")
        else:
            print(f"ASHER: same labels {metric._name} == {labels} - {metric._labelnames}")
        return super(AppMetricsAfterMiddleware, self).label_metric(
            metric, request, response=response, **new_labels
        )


@override_settings(
    MIDDLEWARE=get_middleware(
        "testapp.test_middleware_custom_labels.AppMetricsBeforeMiddleware",
        "testapp.test_middleware_custom_labels.AppMetricsAfterMiddleware",
    )
)
class TestMiddlewareMetricsWithCustomLabels(PrometheusTestCaseMixin, TransactionTestCase):
    def test_request_counters(self):
        registry = self.saveRegistry()
        self.client.get("/")
        self.client.get("/")
        self.client.get("/help")
        self.client.post("/", {"test": "data"})

        self.assertMetricDiff(registry, 4, M("requests_before_middlewares_total"))
        self.assertMetricDiff(registry, 4, M("responses_before_middlewares_total"))
        self.assertMetricDiff(registry, 3, T("requests_total_by_method"), method="GET")
        self.assertMetricDiff(registry, 1, T("requests_total_by_method"), method="POST")
        self.assertMetricDiff(
            registry, 4, T("requests_total_by_transport"), transport="http"
        )
        self.assertMetricDiff(
            registry,
            2,
            T("requests_total_by_view_transport_method"),
            view="testapp.views.index",
            transport="http",
            method="GET",
        )
        self.assertMetricDiff(
            registry,
            1,
            T("requests_total_by_view_transport_method"),
            view="testapp.views.help",
            transport="http",
            method="GET",
        )
        self.assertMetricDiff(
            registry,
            1,
            T("requests_total_by_view_transport_method"),
            view="testapp.views.index",
            transport="http",
            method="POST",
        )
        self.assertMetricDiff(
            registry,
            2.0,
            T("responses_total_by_status_view_method"),
            status="200",
            view="testapp.views.index",
            method="GET",
            view_type="foo",
            user_agent_type="browser",
        )
        self.assertMetricDiff(
            registry,
            1.0,
            T("responses_total_by_status_view_method"),
            status="200",
            view="testapp.views.help",
            method="GET",
            view_type="foo",
            user_agent_type="browser",
        )