import time

import numpy as np

from .sampler import BaseSampler
from .utils import flatten_function


class RejectionSampler(BaseSampler):
    """The summary line for a class docstring should fit on one line.

    If the class has public attributes, they may be documented here
    in an ``Attributes`` section and follow the same formatting as a
    function's ``Args`` section. Alternatively, attributes may be documented
    inline with the attribute's declaration (see __init__ method below).

    Properties created with the ``@property`` decorator should be documented
    in the property's getter method.

    Attributes:
        attr1 (str): Description of `attr1`.
        attr2 (:obj:`int`, optional): Description of `attr2`.

    """

    # set and get for threshold
    @property
    def threshold(self):
        return self._threshold

    @threshold.setter
    def threshold(self, threshold):
        if isinstance(threshold, (int, float)):
            if threshold > 0 or np.isclose(threshold, 0):
                self._threshold = threshold
            else:
                raise ValueError("Passed argument {} must not be negative".format(threshold))
        else:
            raise TypeError("Passed argument {} has to be and integer or float.".format(threshold))

    def __init__(self, priors, simulator, observation, summaries, distance='euclidean', verbosity=1, seed=None):
        """constructor"""

        # call BaseSampler __init__
        super().__init__(priors, simulator, observation, summaries, distance, verbosity, seed)

    def _reset(self):
        """reset class properties for a new call of sample method"""
        self._nr_iter = 0
        self._Thetas = np.empty(0)
        self._simtime = 0
        self._runtime = 0

    def _run_rejection_sampling(self, batch_size):
        """the abc rejection sampling algorithm with batches"""

        # observed data and their summary statistics
        X = self.observation
        stats_x = flatten_function(self.summaries, X)

        # convenience function to compute summaries of generated data
        simulate_and_summarize = lambda thetas: flatten_function(self.summaries, self.simulate(thetas))
        compute_distance = lambda stats_y: self.distance(stats_x, stats_y)

        # initialize the loop
        accepted_thetas = []
        distances = []

        starttime = time.clock()

        nr_batches = 0

        while len(accepted_thetas) < self.nr_samples:
            nr_batches += 1

            # draw batch_size parameters from priors
            thetas_batch = self.priors.sample(batch_size)

            # compute the summary statistics for this batch
            summaries_batch = np.apply_along_axis(simulate_and_summarize, axis=1, arr=thetas_batch)

            # compute the distances for this batch
            d_batch = np.apply_along_axis(compute_distance, axis=1, arr=summaries_batch)

            # accept only those thetas with a distance lower than the threshold
            accepted_thetas.extend(thetas_batch[d_batch <= self.threshold])
            distances.extend(d_batch[d_batch <= self.threshold])

            self._runtime = (time.clock() - starttime)
            self._nr_iter += batch_size
            self._acceptance_rate = len(accepted_thetas) / self.nr_iter

            self.log(accepted_thetas, False) # after each batch

        # we only want nr_samples samples. throw away what's too much
        accepted_thetas = accepted_thetas[:self.nr_samples]
        thetas = np.array(accepted_thetas)

        self._runtime = time.clock() - starttime

        self._nr_iter = (nr_batches * batch_size)
        self._acceptance_rate = self.nr_samples / self.nr_iter
        self._Thetas = thetas
        self._distances = distances[:self.nr_samples]
        return thetas

    def sample(self, threshold, nr_samples, batch_size=1000):
        """Main method of sampler. Draw from prior and simulate data until nr_samples were accepted according to threshold.

        Args:
            threshold: Threshold is used as acceptance criteria for samples.
            nr_samples: Number of samples drawn from prior distribution.
            distance: distance measure to compare summary statistics. (default) euclidean

        Returns:
            Nothing

        """
        self.threshold = threshold
        self.nr_samples = nr_samples

        if self.verbosity:
            print("Rejection sampler started with threshold: {} and number of samples: {}".format(self.threshold,
                                                                                                  self.nr_samples))

        self._reset()

        # RUN ABC REJECTION SAMPLING
        self._run_rejection_sampling(batch_size)

        self.log(final=True)

    def log(self, accepted_thetas=[], final=False):

        if self.verbosity > 1 and not final:
            print("Samples: %6d / %6d (%3d %%)- Threshold: %.4f - Iterations: %10d - Acceptance rate: %4f - Time: %8.2f s" % (
                len(accepted_thetas),
                self.nr_samples,
                int(np.round(len(accepted_thetas) / self.nr_samples * 100)), 
                self.threshold, 
                self.nr_iter, 
                self.acceptance_rate, 
                self.runtime)
            )

        if final:
            print("Samples: %6d - Threshold: %.4f - Iterations: %10d - Acceptance rate: %4f - Time: %8.2f s" % (
                self.nr_samples, 
                self.threshold, 
                self.nr_iter, 
                self.acceptance_rate,
                self.runtime)
            )

    def __str__(self):
        return "{} - priors: {} - simulator: {} - summaries: {} - observation: {} - discrepancy: {} - verbosity: {}".format(
            type(self).__name__, len(self.priors), self.simulator, len(self.summaries), self.observation.shape,
            self.discrepancy, self.verbosity
        )
