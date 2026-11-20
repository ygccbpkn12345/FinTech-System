# import wandb
import csv
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '5'

import tensorflow as tf
from tensorflow import keras
from keras.layers import Input, Dense, Lambda
from gymnasium import spaces
# import argparse
import numpy as np
from threading import Thread
from multiprocessing import cpu_count
import math
import time
import numpy as np
import gym
import pandas as pd
import matplotlib
import matplotlib.pylab as plt

matplotlib.use('Agg')

# import env_portfolio
from env_new import StockPortfolioEnv

# from env_portfolio import StockPortfolioEnv

tf.keras.backend.set_floatx('float64')

from sklearn.decomposition import PCA

# wandb.init(name='A3C_conv', project="new_A3C")

"""
    gamma：折扣因子，用于计算长期奖励。
    update_interval：每隔一定步数更新模型。
    actor_lr 和 critic_lr：actor和critic网络的学习率。
"""
# parser = argparse.ArgumentParser()
# parser.add_argument('--gamma', type=float, default=0.99)
# parser.add_argument('--update_interval', type=int, default=5)
# parser.add_argument('--actor_lr', type=float, default=0.0005)
# parser.add_argument('--critic_lr', type=float, default=0.001)
# args = parser.parse_args()

CUR_EPISODE = 0
""""
state_dim：环境状态的维度。
action_dim：动作空间的维度。
action_bound：动作的最大取值范围（假设动作是连续的）。
std_bound：标准差的上下界，用于限制策略分布的探索范围。

self.model：神经网络模型，用于学习动作分布（均值和标准差）。
self.opt：优化器，使用 Adam 优化算法更新策略网络的参数。
self.entropy_beta：熵系数，用于鼓励策略的探索性（虽然此处未使用）。
"""

class Actor:
    def __init__(self, state_dim, action_dim, action_bound, std_bound):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.action_bound = action_bound
        self.std_bound = std_bound
        self.model = self.create_model()
        self.opt = tf.keras.optimizers.Adam(0.00001)
        # self.opt = tf.keras.optimizers.Adam(args.actor_lr)
        self.entropy_beta = 0.001

    def create_model(self):
        # 创建一个输入层其形状为：state_dim
        state_input = Input((self.state_dim,))
        # 创建一个全连接层（也称为密集层），包含32个神经元，并使用ReLU作为激活函数。
        dense_1 = Dense(32, activation='relu')(state_input)
        # 创建一个全连接层（也称为密集层），包含32个神经元，并使用ReLU作为激活函数。
        dense_2 = Dense(32, activation='relu')(dense_1)
        # 创建一个全连接层，其神经元数量等于动作空间的维度：self.action_dim。
        out_mu = Dense(self.action_dim, activation='tanh')(dense_2)
        # 使用 Lambda 层来对 out_mu 的输出进行缩放。
        # self.action_bound 是动作空间的上界（假设动作是均匀分布的）。
        mu_output = Lambda(lambda x: x * self.action_bound)(out_mu)
        # 创建另一个全连接层，其神经元数量同样等于动作空间的维度 self.action_dim。
        # 它是一个平滑的、近似ReLU的函数，但它的输出始终是正的，没有像ReLU那样的0的输出区域。Softplus函数通常用于确保输出为正，
        std_output = Dense(self.action_dim, activation='softplus')(dense_2)
        return tf.keras.models.Model(state_input, [mu_output, std_output])

    def get_action(self, state):
        state = np.reshape(state, (self.state_dim, -1)).T
        mu, std = self.model.predict(state)
        mu, std = mu[0], std[0]
        # 生成一个形状为 self.action_dim 的数组，其中的每个元素都是从均值为 mu、标准差为 std 的正态分布中随机抽取的。)
        return np.random.normal(mu, std, size=self.action_dim)

    def log_pdf(self, mu, std, action):
        std = tf.clip_by_value(std, self.std_bound[0], self.std_bound[1])
        var = std ** 2
        log_policy_pdf = -0.5 * (action - mu) ** 2 / \
                         var - 0.5 * tf.math.log(var * 2 * np.pi)
        return tf.reduce_sum(log_policy_pdf, 1, keepdims=True)

    def entropy(self, std):
        return tf.reduce_sum(tf.math.log(std) + 0.5 * np.log(2.0 * np.pi * np.e), axis=-1)
    
    def compute_loss(self, mu, std, actions, advantages):
        # 计算loss
        log_policy_pdf = self.log_pdf(mu, std, actions)
        loss_policy = log_policy_pdf * advantages
        entropy = self.entropy(std)
        entropy_loss = -self.entropy_beta * tf.reduce_mean(entropy)
        policy_loss = -tf.reduce_sum(loss_policy)
        total_loss = policy_loss + entropy_loss
        return total_loss

    # def compute_loss(self, mu, std, actions, advantages):
    #     # 计算loss
    #     log_policy_pdf = self.log_pdf(mu, std, actions)
    #     loss_policy = log_policy_pdf * advantages
    #     return tf.reduce_sum(-loss_policy)

    def train(self, states, actions, advantages):
        # 梯度
        with tf.GradientTape() as tape:
            mu, std = self.model(states, training=True)
            loss = self.compute_loss(mu, std, actions, advantages)
        grads = tape.gradient(loss, self.model.trainable_variables)
        self.opt.apply_gradients(zip(grads, self.model.trainable_variables))
        return loss


class Critic:
    def __init__(self, state_dim):
        self.state_dim = state_dim
        self.model = self.create_model()
        self.opt = tf.keras.optimizers.Adam(0.00001)
        # self.opt = tf.keras.optimizers.Adam(args.critic_lr)

    def create_model(self):
        return tf.keras.Sequential([
            Input((self.state_dim,)),
            Dense(32, activation='relu'),
            Dense(32, activation='relu'),
            Dense(16, activation='relu'),
            Dense(1, activation='linear')
        ])

    def compute_loss(self, v_pred, td_targets):
        # 计算损失平方差
        mse = tf.keras.losses.MeanSquaredError()
        return mse(td_targets, v_pred)

    def train(self, states, td_targets):
        # 梯度
        with tf.GradientTape() as tape:
            v_pred = self.model(states, training=True)
            # print("v_pred:",v_pred.shape)
            assert v_pred.shape == td_targets.shape
            loss = self.compute_loss(v_pred, tf.stop_gradient(td_targets))
        grads = tape.gradient(loss, self.model.trainable_variables)
        # print("grads_2:",grads)
        self.opt.apply_gradients(zip(grads, self.model.trainable_variables))
        return loss


class DRL_Agent:
    def __init__(self, env):
        # env = gym.make(env_name)
        self.env = env
        self.state_dim = env.observation_space.shape[0]
        self.action_dim = env.action_space.shape[0]
        self.action_bound = env.action_space.high[0]
        self.std_bound = [0.0, 1.0]

        self.global_actor = Actor(self.state_dim, self.action_dim, self.action_bound, self.std_bound)
        self.global_critic = Critic(self.state_dim)
        self.num_workers = 5
        
        # print("self.num_workers:",self.num_workers)

    def train(self, max_episodes=100):
        workers = []
        for i in range(self.num_workers):
            # env = gym.make(self.env_name)
            workers.append(
                WorkerAgent(self.env, self.global_actor, self.global_critic, max_episodes)
            )

        for worker in workers:
            worker.start()

        for worker in workers:
            worker.join()
        # end_of_train = True
        return self.global_actor.model


def DRL_prediction(model, test_data, test_env, test_obs):
    """make a prediction"""
    account_memory = []
    actions_memory = []
    for i in range(len(test_data.date.unique())):
        test_obs = np.reshape(test_obs, (state_space, -1))
        mu, std = model.predict(test_obs)
        mu, std = mu[0], std[0]
        action = np.random.normal(mu, std, size=state_space)
        action = np.clip(action, 0, state_space)
        action = np.reshape(action, [1, action.shape[0]])
        test_obs, rewards, dones, info = test_env.step(action)
        if i == (len(test_data.date.unique()) - 2):
            account_memory = test_env.env_method(method_name="save_asset_memory")
            # print(type(account_memory))
            actions_memory = test_env.env_method(method_name="save_action_memory")
    return account_memory[0], actions_memory[0]


class WorkerAgent(Thread):
    def __init__(self, env, global_actor, global_critic, max_episodes):
        Thread.__init__(self)
        self.env = env
        self.state_dim = self.env.observation_space.shape[0]
        self.action_dim = self.env.action_space.shape[0]
        self.action_bound = self.env.action_space.high[0]
        self.std_bound = [0.0, 1.0]
        self.max_episodes = max_episodes
        self.global_actor = global_actor
        self.global_critic = global_critic
        self.actor = Actor(self.state_dim, self.action_dim,
                           self.action_bound, self.std_bound)
        self.critic = Critic(self.state_dim)
        self.actor.model.set_weights(self.global_actor.model.get_weights())
        self.critic.model.set_weights(self.global_critic.model.get_weights())

        # self.actor.opt = tf.keras.optimizers.Adam(0.00005)
        # self.critic.opt = tf.keras.optimizers.Adam(0.00005)

    def n_step_td_target(self, rewards, next_v_value, done):
        td_targets = np.zeros_like(rewards)
        cumulative = 0
        if not done:
            cumulative = next_v_value
        for k in reversed(range(0, len(rewards))):
            # cumulative = args.gamma * cumulative + rewards[k]
            cumulative = 0.9 * cumulative +  rewards[k]
            td_targets[k] = cumulative
        return td_targets

    def advatnage(self, td_targets, baselines):
        return td_targets - baselines

    def list_to_batch(self, list):
        batch = list[0]
        for elem in list[1:]:
            batch = np.append(batch, elem, axis=0)
        return batch

    def train(self):
        global CUR_EPISODE
        # LossTotal = []
        # EndReward = []
        print("max_episodes:",self.max_episodes)
        while self.max_episodes > CUR_EPISODE:
            state_batch = []
            action_batch = []
            reward_batch = []
            episode_reward, done = 0, False
            state = self.env.reset()
            end_reward = 1
            loss_total = 0
            while not done:
                # self.env.render()
                action = self.actor.get_action(state)
                "确保智能体的动作在指定的有效范围内[0,1]"
                action = np.clip(action, 0, self.action_bound)
                state = np.reshape(state, (self.state_dim, -1))
                pca = PCA(n_components=1)
                state = pca.fit_transform(state).T
                action = np.reshape(action, [1, action.shape[0]])
                next_state, reward, done, _ = self.env.step(action)
                next_state = np.reshape(next_state, [self.state_dim, -1])
                next_state = pca.fit_transform(next_state).T
                reward = np.reshape(reward, [1, 1])
                end_reward *= (1+reward[0][0])
                state_batch.append(state)
                action_batch.append(action)
                reward_batch.append(reward)
                # print("reward is : ",reward)
                if len(state_batch) >= 5 or done:
                    # 将累积的状态、动作和奖励列表转换为批次形式，以便用于神经网络的训练
                    states = self.list_to_batch(state_batch)
                    actions = self.list_to_batch(action_batch)
                    rewards = self.list_to_batch(reward_batch)
                    # rewards = np.clip(rewards,0.5,1.5)
                    # print("reward is : ",rewards)
                    # 使用评论家网络（critic）预测下一个状态的价值。
                    next_v_value = self.critic.model.predict(next_state)
                    td_targets = self.n_step_td_target(rewards, next_v_value, done)
                    # print("self.critic.model.predict(states).shape:",self.critic.model.predict(states).shape)
                    # td_targets = (td_targets - np.mean(td_targets)) / (np.std(td_targets) + 1e-8)

                    # 计算优势函数，它是目标值和当前状态估计值之间的差异。
                    advantages = td_targets - self.critic.model.predict(states)

                    # advantages = (advantages - np.mean(advantages)) / (np.std(advantages) + 1e-8)
                    # td_targets = (td_targets - np.mean(td_targets)) / (np.std(td_targets) + 1e-8)
                    # print("td_targets", td_targets)
                    # print("advantages",advantages)
                    # 使用累积的批次数据训练全局演员网络（global_actor）和评论家网络（global_critic）
                    actor_loss = self.global_actor.train(states, actions, advantages)
                    critic_loss = self.global_critic.train(states, td_targets)
                    loss_total += actor_loss + critic_loss

                    # 将全局网络的权重复制到本地网络。

                    self.actor.model.set_weights(self.global_actor.model.get_weights())
                    self.critic.model.set_weights(self.global_critic.model.get_weights())

                    state_batch = []
                    action_batch = []
                    reward_batch = []
                # end_reward = reward[0][0]
                state = next_state[0]
            filename = 'D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_LossTotal_CNN.csv'
            # 打开文件，准备写入
            with open(filename, 'a') as csvfile:
                # 创建csv.writer对象
                csvwriter = csv.writer(csvfile)
                # 写入数据
                row = [np.float32(loss_total)]
                csvwriter.writerow(row) 
            filename = 'D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_EndReward_CNN.csv'
            # 打开文件，准备写入
            with open(filename, 'a') as csvfile:
                # 创建csv.writer对象
                csvwriter = csv.writer(csvfile)
                # 写入数据
                row = [np.float32(end_reward)]
                csvwriter.writerow(row) 
            print('EP{} EpisodeLoss{} EpisodeLoss={} '.format(CUR_EPISODE, end_reward, loss_total))
            CUR_EPISODE += 1

    def run(self):
        self.train()


if __name__ == "__main__":
    # end_of_train = False
    train_df = pd.read_csv("D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/datasets/02_train_CNN.csv")
    test_df = pd.read_csv("D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/datasets/02_test_CNN.csv")
    # verify_df = pd.read_csv("C:/AAAAA-Experiment/Experiment_paper_1/American/datasets/test2/02_verify_CNN.csv")
    # 建立环境
    # 它包含了四个技术指标（可能是股票市场的技术分析指标）
    tech_indicator_list = ['f1', 'f2', 'f3', 'f4']
    # 股票种类数。
    stock_dimension = len(train_df.tic.unique())
    # 假设状态空间的大小与股票种类的数量相同。
    state_space = stock_dimension

    weights_initial = [1 / stock_dimension] * stock_dimension
    env_kwargs = {
        "hmax": 500,
        "initial_amount": 1000000,
        "transaction_cost_pct": 0.001,
        "state_space": state_space,
        "stock_dim": stock_dimension,
        "tech_indicator_list": tech_indicator_list,
        "action_space": stock_dimension,
        "reward_scaling": 0,
        'initial_weights': [1 / stock_dimension] * stock_dimension
    }
    e_train_gym = StockPortfolioEnv(df=train_df, **env_kwargs)
    env_train, _ = e_train_gym.get_sb_env()
    agent = DRL_Agent(env=env_train)
    A3C_train = agent.train()

    print("--------------------------Training------------------------------")
    # if end_of_train:
    e_trade_gym_train = StockPortfolioEnv(df=train_df, **env_kwargs)
    env_trade, obs_trade = e_trade_gym_train.get_sb_env()
    # print(obs_trade.shape)
    a3c_train_daily_return, a3c_train_weights = DRL_prediction(model=A3C_train,
                                                               test_data=train_df,
                                                               test_env=env_trade,
                                                               test_obs=obs_trade)
    a3c_train_weights.to_csv("D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_train_weights_CNN.csv",index=False)
    a3c_train_daily_return.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_train_daily_return_CNN.csv',index=False) 
    
    print("--------------------------Test------------------------------")    
    e_trade_gym_test = StockPortfolioEnv(df = test_df, **env_kwargs)
    env_trade, obs_trade = e_trade_gym_test.get_sb_env()
    a3c_test_daily_return, a3c_test_weights = DRL_prediction(model=A3C_train,
                                                             test_data=test_df,
                                                             test_env=env_trade,
                                                             test_obs=obs_trade)
    a3c_test_weights.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_test_weights_CNN.csv',index=False)
    a3c_test_daily_return.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_test_daily_return_CNN.csv',index=False)
    print("--------------------------Test------------------------------")    
    e_trade_gym_test = StockPortfolioEnv(df = test_df, **env_kwargs)
    env_trade, obs_trade = e_trade_gym_test.get_sb_env()
    a3c_test_daily_return, a3c_test_weights = DRL_prediction(model=A3C_train,
                                                             test_data=test_df,
                                                             test_env=env_trade,
                                                             test_obs=obs_trade)
    a3c_test_weights.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_test_weights_CNN1.csv',index=False)
    a3c_test_daily_return.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_test_daily_return_CNN1.csv',index=False)
    print("--------------------------Test------------------------------")    
    e_trade_gym_test = StockPortfolioEnv(df = test_df, **env_kwargs)
    env_trade, obs_trade = e_trade_gym_test.get_sb_env()
    a3c_test_daily_return, a3c_test_weights = DRL_prediction(model=A3C_train,
                                                             test_data=test_df,
                                                             test_env=env_trade,
                                                             test_obs=obs_trade)
    a3c_test_weights.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_test_weights_CNN2.csv',index=False)
    a3c_test_daily_return.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_test_daily_return_CNN2.csv',index=False)

    print("--------------------------Test------------------------------")    
    e_trade_gym_test = StockPortfolioEnv(df = test_df, **env_kwargs)
    env_trade, obs_trade = e_trade_gym_test.get_sb_env()
    a3c_test_daily_return, a3c_test_weights = DRL_prediction(model=A3C_train,
                                                             test_data=test_df,
                                                             test_env=env_trade,
                                                             test_obs=obs_trade)
    a3c_test_weights.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_test_weights_CNN3.csv',index=False)
    a3c_test_daily_return.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_test_daily_return_CNN3.csv',index=False)

    print("--------------------------Test------------------------------")    
    e_trade_gym_test = StockPortfolioEnv(df = test_df, **env_kwargs)
    env_trade, obs_trade = e_trade_gym_test.get_sb_env()
    a3c_test_daily_return, a3c_test_weights = DRL_prediction(model=A3C_train,
                                                             test_data=test_df,
                                                             test_env=env_trade,
                                                             test_obs=obs_trade)
    a3c_test_weights.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_test_weights_CNN4.csv',index=False)
    a3c_test_daily_return.to_csv('D:/AAA ZJGSU/Experiment/AAAAA-Experiment/AAA_Paper1_05/S&P500/test2023/result/04_a3c_test_daily_return_CNN4.csv',index=False)

