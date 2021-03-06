import time

import numpy as np
import scipy.stats as ss

from .rejection_sampler import RejectionSampler
from .sampler import BaseSampler
from .utils import flatten_function

"""class doc"""


class SMCSampler(BaseSampler):
    # set and get for threshold
    @property
    def thresholds(self):
        return self._thresholds

    @thresholds.setter
    def thresholds(self, thresholds):
        thresholds = np.atleast_1d(thresholds)
        if all((isinstance(t, (int, float)) and not t < 0 for t in thresholds)):
            self._thresholds = thresholds
        else:
            raise ValueError(
                "Passed argument {} must not be a list of integers or float and non-negative".format(thresholds))

    @property
    def particles(self):
        return self._particles

    @property
    def weights(self):
        return self._weights

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

        # call BaseSampler __init__
        super().__init__(priors, simulator, observation, summaries, distance, verbosity, seed)

    def sample(self, thresholds, nr_samples, distance='euclidean'):
        """Draw samples using Sequential Monte Carlo.

        Args:
            thresholds: list of acceptance threshold. len(thresholds defines number of SMC iterations)
            nr_particles: Number of particles used to represent the distribution
            distance: distance measure to compare summary statistics. (default) euclidean

        Returns:
            Nothing

        """

        self._thresholds = thresholds
        self._threshold = thresholds[-1] # final threshold, to have same attribute as other classes
        self.nr_samples = nr_samples
        print("SMC sampler started with thresholds: {} and number of samples: {}".format(self.thresholds, self.nr_samples))
        self._reset()
        self._run_PMC_sampling()
        
        self.log(self.threshold, final=True)

    def _calculate_weights(self, curr_theta, prev_thetas, ws, sigma):

        prior_mean = 0

        prior_pdf = self.priors.logpdf(curr_theta)

        kernel = ss.multivariate_normal(curr_theta, sigma, allow_singular=True).pdf
        weight = np.exp(prior_pdf) / np.dot(ws, kernel(prev_thetas))

        return weight

    def _run_PMC_sampling(self):
        T = len(self.thresholds)
        X = self.observation

        list_of_stats_x = flatten_function(self.summaries, X)
        num_priors = len(self.priors)  # TODO: multivariate prior?
        nr_iter = 0

        # create a large array to store all particles (THIS CAN BE VERY MEMORY INTENSIVE)
        thetas = np.zeros((T, self.nr_samples, num_priors))
        weights = np.zeros((T, self.nr_samples))
        sigma = np.zeros((T, num_priors, num_priors))
        distances = np.zeros((T, self.nr_samples))

        start = time.clock()

        for t in range(T):
            # init particles by using ABC Rejection Sampling with first treshold
            if t == 0:
                rej_samp = RejectionSampler(
                    priors=self.priors.tolist(),
                    simulator=self.simulator,
                    summaries=self.summaries,
                    distance=self.distance,
                    observation=self.observation,
                    verbosity=self.verbosity
                )
                rej_samp.sample(threshold=self.thresholds[0], nr_samples=self.nr_samples)

                nr_iter += rej_samp.nr_iter
                self._nr_iter = nr_iter
                self._runtime = time.clock() - start
                self._acceptance_rate = self.nr_samples / self.nr_iter

                thetas[t, :, :] = rej_samp.Thetas
                distances[t, :] = rej_samp.distances
                # create even particle for each
                weights[t, :] = np.ones(self.nr_samples) / self.nr_samples
                sigma[t, :, :] = 2 * np.cov(thetas[t, :, :].T)
            else:
                if self.verbosity:
                    print('starting iteration[', t, ']')
                for i in range(0, self.nr_samples):
                    while (True):
                        nr_iter += 1
                        # sample from the previous iteration, with weights and perturb the sample
                        idx = np.random.choice(np.arange(self.nr_samples), p=weights[t - 1, :])
                        theta = np.atleast_1d(thetas[t - 1, idx, :])
                        thetap = np.atleast_1d(ss.multivariate_normal(theta, sigma[t - 1], allow_singular=True).rvs())

                        # for which theta pertubation produced unreasonable values?
                        for id, prior in enumerate(self.priors):
                            if prior.pdf(thetap[id]) == 0:
                                thetap[id] = theta[id]

                        Y = self.simulate((np.atleast_1d(thetap)))  # unpack thetas as single arguments for simulator
                        list_of_stats_y = flatten_function(self.summaries, Y)
                        # either use predefined distance function or user defined discrepancy function
                        d = self.distance(list_of_stats_x, list_of_stats_y)

                        if d <= self.thresholds[t]:
                            distances[t, i] = d
                            thetas[t, i, :] = thetap
                            # weights represent how probable a theta is
                            # small weights mean theta* is close to old thetas
                            # heigh weights mean, theta* is far from old thetas
                            # we want the close ones, so we have to invert the weights
                            # so that small weights become the large ones
                            weights[t, i] = self._calculate_weights(thetas[t, i, :], thetas[t - 1, :],
                                                                    weights[t - 1, :], sigma[t - 1])
                            break
                            
                        self._nr_iter = nr_iter
                        self._runtime = time.clock() - start
                        self._acceptance_rate = self.nr_samples / self.nr_iter

                        if nr_iter % 1000 == 0:
                            self.log(self.thresholds[t], thetas[t][thetas[t] != 0], False)

            self.log(self.threshold, thetas[t], False)
            weights[t, :] = weights[t, :] / sum(weights[t, :])
            sigma[t, :, :] = 2 * np.cov(thetas[t, :, :].T, aweights=weights[t, :])

        self._runtime = time.clock() - start
        self._nr_iter = nr_iter
        self._acceptance_rate = self.nr_samples / self.nr_iter
        self._particles = thetas
        self._weights = weights
        self._Thetas = thetas[T - 1, :, :]
        self._distances = distances

        return thetas[T - 1, :, :]

    def _reset(self):
        """reset class properties for a new call of sample method"""
        self._nr_iter = 0
        self._Thetas = np.empty(0)
        self._simtime = 0
        self._runtime = 0

    def log(self, threshold, accepted_thetas=[], final=False):

        if self.verbosity > 1 and not final:
            print("Samples: %6d / %6d (%3d %%)- Threshold: %.4f - Iterations: %10d - Acceptance rate: %4f - Time: %8.2f s" % (
                len(accepted_thetas),
                self.nr_samples,
                int(np.round(len(accepted_thetas) / self.nr_samples * 100)), 
                threshold, 
                self.nr_iter, 
                self.acceptance_rate, 
                self.runtime)
            )

        if final:
            print("Samples: %6d - Threshold: %.4f - Iterations: %10d - Acceptance rate: %4f - Time: %8.2f s" % (
                self.nr_samples, 
                threshold, 
                self.nr_iter, 
                self.acceptance_rate,
                self.runtime)
            )

    def __str__(self):
        return "{} - priors: {} - simulator: {} - summaries: {} - observation: {} - discrepancy: {} - verbosity: {}".format(
            type(self).__name__, len(self.priors), self.simulator, len(self.summaries), self.observation.shape,
            self.discrepancy, self.verbosity
        )