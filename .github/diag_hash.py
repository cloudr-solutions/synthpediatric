import hashlib
import sys

import numpy as np

import synthpediatric
from synthpediatric.recipe import run_recipe

tag = sys.argv[1]
r = {
    "name": "legacy-local", "metadata": "examples/nccr_ctc_dictionary.json", "n": 800, "seed": 7,
    "override_marginals": {"sex": {"Male": 700, "Female": 300}},
    "oversample": {"variable": "iccc_category", "values": ["__none__"], "factor": 5},
    "survival": {"group_col": "iccc_category", "horizon_months": 120, "specs": {"__default__": 0.8}},
}
df = run_recipe(r)["data"]
print(tag, "src", synthpediatric.__file__)
print(tag, "WHOLE", hashlib.sha256(df.to_csv(index=False).encode()).hexdigest())
for c in df.columns:
    print(tag, "COL", c, df[c].dtype, hashlib.sha256(df[c].to_csv(index=False).encode()).hexdigest()[:16])
print(tag, "LOG0.8", repr(float(np.log(0.8))), repr(float(np.log(np.array([0.8] * 8))[0])))
print(tag, "MONTHS", " ".join(repr(float(x)) for x in df["months"]))
