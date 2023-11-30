# Robust Reinforcement Learning via adversary pools
We investigate the effect of population based training on the robustness of solutions to the robust MDP.

## Setup instructions
To install the code with anaconda run 
- `conda env create -f environment.yml`
- `conda activate adversary_pools`
- `python setup.py develop` 
- If you want to run videos make sure to install ffmpeg. If you have brew you can run `brew install ffmpeg`.

## Running the envs
The relevant file is run_adv_mujoco.py in `run_scripts/mujoco`. For configurations, check out the options on the argparser.