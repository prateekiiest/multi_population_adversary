#!/usr/bin/env bash

# 11/25/19
#ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA --use_s3 \
#--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --num_cpus 30 --run_transfer_tests" --tmux --start --stop --cluster-name=sa_test
#
#ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA_GaS --use_s3 \
#--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --add_gaussian_noise_state --num_cpus 30 --run_transfer_tests" --tmux --start --stop --cluster-name=sa_test2
#
#ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA_GaA --use_s3 \
#--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --add_gaussian_noise_action --num_cpus 30 --run_transfer_tests" --tmux --start --stop --cluster-name=sa_test3
#
#ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA_GaS_GaA --use_s3 \
#--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --add_gaussian_noise_state --add_gaussian_noise_action --num_cpus 30 --run_transfer_tests" \
#--tmux --start --stop --cluster-name=sa_test4

####################################################################################################
# 11/26/19
#ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA --use_s3 \
#--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --num_cpus 30 --run_transfer_tests" --tmux --start --stop --cluster-name=sa_test
#
#ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA_GaS --use_s3 \
#--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --add_gaussian_noise_state --num_cpus 30 --run_transfer_tests" \
#--tmux --start --stop --cluster-name=sa_test2
#
#ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA_GaA --use_s3 \
#--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --add_gaussian_noise_action --num_cpus 30 --run_transfer_tests" \
#--tmux --start --stop --cluster-name=sa_test3
#
#ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA_GaS_GaA --use_s3 \
#--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --add_gaussian_noise_state --add_gaussian_noise_action --num_cpus 30 --run_transfer_tests" \
#--tmux --start --stop --cluster-name=sa_test4

####################################################################################################
# 12/1/19 running the exps with 4 humans to attempt to encourage it to avoid humans
ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA_h4 --use_s3 \
--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --num_cpus 18 --run_transfer_tests --human_num 4" --tmux --start --cluster-name=sa_test1

ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA_GaS_h4 --use_s3 \
--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --add_gaussian_noise_state --num_cpus 18 --run_transfer_tests --human_num 4" \
--tmux --start --cluster-name=sa_test2

ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA_GaA_h4 --use_s3 \
--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --add_gaussian_noise_action --num_cpus 18 --run_transfer_tests --human_num 4" \
--tmux --start --cluster-name=sa_test3

ray exec ../autoscale.yaml "python /home/ubuntu/adversarial_sim2real/run_scripts/test_rllib_script.py --exp_title SA_GaS_GaA_h4 --use_s3 \
--train_batch_size 30000 --checkpoint_freq 50 --num_iters 500 --add_gaussian_noise_state --add_gaussian_noise_action --num_cpus 18 --run_transfer_tests --human_num 4" \
--tmux --start --cluster-name=sa_test4

