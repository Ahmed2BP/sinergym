"""Implementation of custom Gym environments."""

import numpy as np
import gym

from collections import deque
from energym.utils.common import CSVLogger
from energym.utils.common import RANGES_5ZONE
from stable_baselines3.common.env_util import is_wrapped


class NormalizeObservation(gym.ObservationWrapper):

    def __init__(self, env, ranges=RANGES_5ZONE):
        """Observations normalized to range [0, 1].

        Args:
            env (object): Original Gym environment.
            ranges: Observation variables ranges to apply normalization (rely on environment)
        """
        super(NormalizeObservation, self).__init__(env)
        self.unwrapped_observation = None
        self.ranges = ranges

    def step(self, action):
        observation, reward, done, info = self.env.step(action)

        return self.observation(observation), reward, done, info

    def observation(self, obs):
        """Applies normalization to observation.

        Args:
            obs (object): Original observation.

        Returns:
            object: Normalized observation.
        """
        # Save original obs in class attribute
        self.unwrapped_observation = obs.copy()
        variables = self.env.variables["observation"]

        # NOTE: If you want to recor day, month and our. You should add to variables that keys
        for i, variable in enumerate(variables):
            # normalization
            obs[i] = (obs[i]-self.ranges[variable][0]) / \
                (self.ranges[variable][1]-self.ranges[variable][0])
            # If value is out
            if obs[i] > 1:
                obs[i] = 1
            if obs[i] < 0:
                obs[i] = 0
        # Return obs values in the SAME ORDER than obs argument.
        return np.array(obs)

    def get_unwrapped_obs(self):
        """Get last environment observation without normalization.

        Returns:
            object: Last original observation.
        """
        return self.unwrapped_observation


class MultiObsWrapper(gym.Wrapper):

    def __init__(self, env, n=5):
        """Stack of observations.

        Args:
            env (object): Original Gym environment.
            n (int, optional): Number of observations to be stacked. Defaults to 5.
        """
        gym.Wrapper.__init__(self, env)
        self.n = n
        self.history = deque([], maxlen=n)
        shape = env.observation_space.shape
        self.observation_space = gym.spaces.Box(
            low=-5e6, high=5e6, shape=((n,) + shape), dtype=np.float32)

    def reset(self):
        """Resets the environment.

        Returns:
            list: Stacked previous observations.
        """
        obs = self.env.reset()
        for _ in range(self.n):
            self.history.append(obs)
        return self._get_obs()

    def _get_obs(self):
        """Get observation history.

        Returns:
            np.array: Array of previous observations.
        """
        return np.array(self.history)


class LoggerWrapper(gym.Wrapper):

    def __init__(self, env, flag=True):
        """CSVLogger to log interactions with environment.

        Args:
            env (object): Original Gym environment.
            flag (bool, optional): State of logger (activate or deactivate).
        """
        gym.Wrapper.__init__(self, env)
        # Headers for csv logger
        monitor_header_list = ['timestep,month,day,hour']+env.variables['observation'] + \
            env.variables['action']+['time (seconds)', 'reward',
                                     'power_penalty', 'comfort_penalty', 'done']
        self.monitor_header = ''
        for element_header in monitor_header_list:
            self.monitor_header += element_header+','
        self.monitor_header = self.monitor_header[:-1]
        self.progress_header = 'episode_num,cumulative_reward,mean_reward,cumulative_power_consumption,mean_power_consumption,cumulative_comfort_penalty,mean_comfort_penalty,cumulative_power_penalty,mean_power_penalty,comfort_violation (%),length(timesteps),time_elapsed(seconds)'

        # Create simulation logger, by default is active (flag=True)
        self.logger = CSVLogger(monitor_header=self.monitor_header, progress_header=self.progress_header,
                                log_progress_file=env.simulator._env_working_dir_parent+'/progress.csv', flag=flag)

    def step(self, action):
        """Step the environment. Logging new information

        Args:
            action: Action executed in step

        Returns:
            (np.array(),float,bool,dict) tuple 
        """
        obs, reward, done, info = self.env.step(action)
        # We added some extra values (month,day,hour) manually in env, so we need to delete them.
        obs = obs[:-3]
        if is_wrapped(self, NormalizeObservation):
            # Record action and new observation in simulator's csv
            self.logger.log_step_normalize(timestep=info['timestep'],
                                           date=[info['month'],
                                                 info['day'], info['hour']],
                                           observation=obs,
                                           action=info['action_'],
                                           simulation_time=info['time_elapsed'],
                                           reward=reward,
                                           total_power_no_units=info['total_power_no_units'],
                                           comfort_penalty=info['comfort_penalty'],
                                           done=done)
            # Record original observation too
            self.logger.log_step(timestep=info['timestep'],
                                 date=[info['month'],
                                       info['day'], info['hour']],
                                 observation=self.env.get_unwrapped_obs()[:-3],
                                 action=info['action_'],
                                 simulation_time=info['time_elapsed'],
                                 reward=reward,
                                 total_power_no_units=info['total_power_no_units'],
                                 comfort_penalty=info['comfort_penalty'],
                                 power=info['total_power'],
                                 done=done)
        else:
            # Only record observation without normalization
            self.logger.log_step(timestep=info['timestep'],
                                 date=[info['month'],
                                       info['day'], info['hour']],
                                 observation=obs,
                                 action=info['action_'],
                                 simulation_time=info['time_elapsed'],
                                 reward=reward,
                                 total_power_no_units=info['total_power_no_units'],
                                 comfort_penalty=info['comfort_penalty'],
                                 power=info['total_power'],
                                 done=done)

        return obs, reward, done, info

    def reset(self):
        """Resets the environment. Recording episode summary in logger
        """
        # It isn't first episode simulation, so we can logger last episode
        if self.env.simulator._episode_existed:
            self.env.simulator.logger_main.debug(
                'End of episode, recording summary (progress.csv) if logger is active')
            self.logger.log_episode(episode=self.env.simulator._epi_num)

        # Then, reset environment
        obs = self.env.reset()

        # Create monitor.csv for information of this episode
        self.env.simulator.logger_main.debug(
            'Creating monitor.csv for current episode (episode '+str(self.env.simulator._epi_num)+') if logger is active')
        self.logger.set_log_file(
            self.env.simulator._eplus_working_dir+'/monitor.csv')
        # Store initial state of simulation
        self.logger.log_step(timestep=0,
                             date=[obs[-2], obs[-3], obs[-1]],
                             observation=obs,
                             action=[None for _ in range(
                                 len(self.env.variables['action']))],
                             simulation_time=0,
                             reward=None,
                             total_power_no_units=None,
                             comfort_penalty=None,
                             power=None,
                             done=False)

        return obs

    def close(self):
        """Close env. Recording last episode summary.
        """
        # Record last episode summary before end simulation
        self.env.simulator.logger_main.debug(
            'End of episode, recording summary (progress.csv) if logger is active')
        self.logger.log_episode(episode=self.env.simulator._epi_num)

        # Then, close env
        self.env.close()

    def activate_logger(self):
        """Activate logger if its flag False.
        """
        self.logger.activate_flag()

    def deactivate_logger(self):
        """Deactivate logger if its flag True.
        """
        self.logger.deactivate_flag()
