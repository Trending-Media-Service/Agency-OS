# Agency OS — Multi-Tenant Multi-Goal Brand Governance OS

load("//devtools/python/blaze:pytype.bzl", "pytype_strict_library")
load("//third_party/bazel_rules/rules_python/python:py_test.bzl", "py_test")

package(default_visibility = [
    "//learning/gemini/agents/projects/agency_os:__subpackages__",
    "//learning/gemini/agents:__subpackages__",
])

licenses(["notice"])

filegroup(
    name = "sql_schemas",
    srcs = [
        "schema.sql",
    ],
)

pytype_strict_library(
    name = "ingestion",
    srcs = ["ingestion.py"],
)

py_test(
    name = "ingestion_test",
    srcs = ["ingestion_test.py"],
    deps = [
        ":ingestion",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "db_client",
    srcs = ["db_client.py"],
    deps = [
        ":ingestion",
    ],
)

py_test(
    name = "db_client_test",
    srcs = ["db_client_test.py"],
    deps = [
        ":db_client",
        ":ingestion",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "performance_formulas",
    srcs = ["performance_formulas.py"],
)

py_test(
    name = "performance_formulas_test",
    srcs = ["performance_formulas_test.py"],
    deps = [
        ":performance_formulas",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "var_reconciler",
    srcs = ["var_reconciler.py"],
)

py_test(
    name = "var_reconciler_test",
    srcs = ["var_reconciler_test.py"],
    deps = [
        ":var_reconciler",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "ayi_engine",
    srcs = ["ayi_engine.py"],
)

py_test(
    name = "ayi_engine_test",
    srcs = ["ayi_engine_test.py"],
    deps = [
        ":ayi_engine",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "ayi_engine_test_lib",
    srcs = ["ayi_engine_test.py"],
    deps = [
        ":ayi_engine",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "technical_sweep",
    srcs = ["technical_sweep.py"],
)

py_test(
    name = "technical_sweep_test",
    srcs = ["technical_sweep_test.py"],
    deps = [
        ":technical_sweep",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "feedx_alignment",
    srcs = ["feedx_alignment.py"],
)

py_test(
    name = "feedx_alignment_test",
    srcs = ["feedx_alignment_test.py"],
    deps = [
        ":feedx_alignment",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "sentiment_scraper",
    srcs = ["sentiment_scraper.py"],
)

py_test(
    name = "sentiment_scraper_test",
    srcs = ["sentiment_scraper_test.py"],
    deps = [
        ":sentiment_scraper",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "ats_calculator",
    srcs = ["ats_calculator.py"],
)

py_test(
    name = "ats_calculator_test",
    srcs = ["ats_calculator_test.py"],
    deps = [
        ":ats_calculator",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "context_constructor",
    srcs = ["context_constructor.py"],
)

py_test(
    name = "context_constructor_test",
    srcs = ["context_constructor_test.py"],
    deps = [
        ":context_constructor",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "action_card_validator",
    srcs = ["action_card_validator.py"],
)

py_test(
    name = "action_card_validator_test",
    srcs = ["action_card_validator_test.py"],
    deps = [
        ":action_card_validator",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "autonomy_runner",
    srcs = ["autonomy_runner.py"],
    deps = [
        ":action_card_validator",
        ":ats_calculator",
        ":context_constructor",
    ],
)

py_test(
    name = "autonomy_runner_test",
    srcs = ["autonomy_runner_test.py"],
    deps = [
        ":autonomy_runner",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "api_layer",
    srcs = ["api_layer.py"],
    deps = [
        ":autonomy_runner",
    ],
)

py_test(
    name = "api_layer_test",
    srcs = ["api_layer_test.py"],
    deps = [
        ":api_layer",
        ":autonomy_runner",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "approval_portal",
    srcs = ["approval_portal.py"],
)

py_test(
    name = "approval_portal_test",
    srcs = ["approval_portal_test.py"],
    deps = [
        ":approval_portal",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "gcp_provisioner",
    srcs = ["gcp_provisioner.py"],
)

py_test(
    name = "gcp_provisioner_test",
    srcs = ["gcp_provisioner_test.py"],
    deps = [
        ":gcp_provisioner",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "mmm_worker",
    srcs = ["mmm_worker.py"],
)

py_test(
    name = "mmm_worker_test",
    srcs = ["mmm_worker_test.py"],
    deps = [
        ":mmm_worker",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "pltv_engine",
    srcs = ["pltv_engine.py"],
)

py_test(
    name = "pltv_engine_test",
    srcs = ["pltv_engine_test.py"],
    deps = [
        ":pltv_engine",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "creative_analyzer",
    srcs = ["creative_analyzer.py"],
)

py_test(
    name = "creative_analyzer_test",
    srcs = ["creative_analyzer_test.py"],
    deps = [
        ":creative_analyzer",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "benchmarking_engine",
    srcs = ["benchmarking_engine.py"],
)

py_test(
    name = "benchmarking_engine_test",
    srcs = ["benchmarking_engine_test.py"],
    deps = [
        ":benchmarking_engine",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "edge_personalizer",
    srcs = ["edge_personalizer.py"],
)

py_test(
    name = "edge_personalizer_test",
    srcs = ["edge_personalizer_test.py"],
    deps = [
        ":edge_personalizer",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "account_discovery",
    srcs = ["account_discovery.py"],
)

py_test(
    name = "account_discovery_test",
    srcs = ["account_discovery_test.py"],
    deps = [
        ":account_discovery",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "error_sink",
    srcs = ["error_sink.py"],
)

py_test(
    name = "error_sink_test",
    srcs = ["error_sink_test.py"],
    deps = [
        ":error_sink",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "poas_scheduler",
    srcs = ["poas_scheduler.py"],
)

py_test(
    name = "poas_scheduler_test",
    srcs = ["poas_scheduler_test.py"],
    deps = [
        ":poas_scheduler",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "metrics_tracker",
    srcs = ["metrics_tracker.py"],
)

py_test(
    name = "metrics_tracker_test",
    srcs = ["metrics_tracker_test.py"],
    deps = [
        ":metrics_tracker",
        "//third_party/py/absl/testing:absltest",
    ],
)

pytype_strict_library(
    name = "commercialization",
    srcs = ["commercialization.py"],
)

py_test(
    name = "commercialization_test",
    srcs = ["commercialization_test.py"],
    deps = [
        ":commercialization",
        "//third_party/py/absl/testing:absltest",
    ],
)
