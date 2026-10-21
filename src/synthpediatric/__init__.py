"""synthpediatric - privacy-safe synthetic cancer registry cohorts from published marginals.

Phase 0 generates synthetic cohorts by sampling each variable independently from
its published marginal (permissible-value frequencies) and then repairing
clinically incoherent records with a consistency-rules engine.

Because Phase 0 consumes only published *aggregate* frequencies (no individual
records), the synthetic output is privacy-safe by construction: there is no
training set of real people to leak.

Later phases add joint-structure modeling (learned from a public individual-level
proxy such as SEER) calibrated to these marginals, which is what makes the
multivariate structure realistic.
"""

from .analyze import KMResult, kaplan_meier, kaplan_meier_by_group, logrank_test
from .calibrate import (
    CalibrationResult,
    JointDistribution,
    calibrate_to_dictionary,
    generate_calibrated,
    raking_ipf,
    targets_from_dictionary,
)
from .conformance import assert_conformant, conformance_report, coverage_report
from .constraints import AllowedValuesConstraint, Constraint, RuleSet
from .dictionary import DataDictionary, VariableMarginal
from .evaluate import PROVENANCE_STATEMENT, marginal_fidelity, overall_score
from .generate import GenerationResult, generate
from .inputs import (
    CohortFilter,
    CohortSpec,
    apply_cohort,
    cohort_from_dict,
    dictionary_from_frequencies,
    override_marginals,
)
from .recipe import run_recipe, write_run
from .render import survival_to_figure, write_survival_html
from .resample import (
    oversample_rare,
    oversample_values,
    rare_categories,
    reweight_variable,
)
from .survival_gen import sample_survival

__version__ = "0.0.1"


def load_nccr_dictionary(*args, **kwargs):
    """Lazy wrapper around :func:`synthpediatric.nccr_rdf.load_nccr_dictionary`.

    Imported lazily so the core package does not require the optional ``rdflib``
    dependency unless the real NCCR RDF metadata is actually loaded.
    """
    from .nccr_rdf import load_nccr_dictionary as _impl

    return _impl(*args, **kwargs)


__all__ = [
    "DataDictionary",
    "VariableMarginal",
    "Constraint",
    "AllowedValuesConstraint",
    "RuleSet",
    "generate",
    "GenerationResult",
    "marginal_fidelity",
    "overall_score",
    "PROVENANCE_STATEMENT",
    "load_nccr_dictionary",
    "JointDistribution",
    "CalibrationResult",
    "raking_ipf",
    "calibrate_to_dictionary",
    "targets_from_dictionary",
    "generate_calibrated",
    "kaplan_meier",
    "KMResult",
    "kaplan_meier_by_group",
    "logrank_test",
    "survival_to_figure",
    "write_survival_html",
    "sample_survival",
    "dictionary_from_frequencies",
    "override_marginals",
    "apply_cohort",
    "cohort_from_dict",
    "CohortSpec",
    "CohortFilter",
    "coverage_report",
    "conformance_report",
    "assert_conformant",
    "reweight_variable",
    "oversample_values",
    "oversample_rare",
    "rare_categories",
    "run_recipe",
    "write_run",
    "__version__",
]
