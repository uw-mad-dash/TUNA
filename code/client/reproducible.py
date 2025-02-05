# This module makes sure that experiments are reproducible by fixing the seeds
# of Python's and numpy's random generators, as well as replacing stray random
# generators found in MLOS, with ones that have their seed fixed.

import random
import numpy as np

DEFAULT_RANDOM_SEED = 1337


def fix_global_random_state(seed=None):
    if seed is None:
        seed = DEFAULT_RANDOM_SEED

    # Used by the MLOS HomogeneousRandomForestOptimizer
    random.seed(seed)
    np.random.seed(seed)  # Not sure if actually needed


def fix_optimizer_random_state(optimizer, seed=None):
    if seed is None:
        seed = DEFAULT_RANDOM_SEED

    # Replace random number generator (Experiment_designer.rng numpy Generator)
    optimizer.experiment_designer.rng = np.random.Generator(np.random.PCG64(seed=seed))

    # Replace the random state of all input parameter space (sub)dimensions
    # NOTE: even if we set the random state when we construct the input space
    # (i.e. when calling SimpleHypergrid(..., random_state=random_state))
    # for some reason, the random states are replaced...
    random_state = random.Random()
    random_state.seed(seed)
    optimizer.experiment_designer.optimization_problem.parameter_space.random_state = (
        random_state
    )
