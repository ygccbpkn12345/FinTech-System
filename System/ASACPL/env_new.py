# import os
# os.environ['CUDA_VISIBLE_DEVICES'] = '7'  # 指定使用第一个GPU
# import wandb
# wandb.init(name='A3C_reward', project="Test-Asset")
import numpy as np
import pandas as pd
from gym.utils import seeding
import gym
# import math
from gym import spaces
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from stable_baselines3.common.vec_env import DummyVecEnv

import math

class StockPortfolioEnv(gym.Env):
    metadata = {'render.modes': ['human']}
    def __init__(self, 
                df,
                stock_dim,
                hmax,
                initial_amount,
                transaction_cost_pct,
                reward_scaling,
                state_space,
                action_space,
                tech_indicator_list,
                initial_weights,
                turbulence_threshold=None,
                lookback=252,
                day = 0):
        #super(StockEnv, self).__init__()
        #money = 10 , scope = 1
        self.day = day
        self.lookback=lookback
        self.df = df
        self.stock_dim = stock_dim
        self.hmax = hmax
        self.initial_amount = initial_amount
        self.transaction_cost_pct =transaction_cost_pct
        self.reward_scaling = reward_scaling
        self.state_space = state_space
        self.action_space = action_space
        self.tech_indicator_list = tech_indicator_list
        self.initial_weights = initial_weights

        # action_space normalization and shape is self.stock_dim
        self.action_space = spaces.Box(low = 0, high = 1,shape = (self.action_space,)) 
 
        # covariance matrix + technical indicators
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape = (self.state_space+len(self.tech_indicator_list),self.state_space))

        # load data from a pandas dataframe
        self.data = self.df.loc[self.day:self.day+self.stock_dim-1,:]
        # print("self.data:",self.data)
        
        self.covs = self.data['cov_list'].values[0]
        self.covs = self.covs.replace("[", "").replace("]", "")
        self.covs = np.fromstring(self.covs, sep=' ')
        num_dim = int(self.stock_dim)
        self.covs = np.reshape(self.covs,[num_dim,-1])
        # print("self.covs.shape:",self.covs)
        # print(self.data["f01"].values.tolist())
        self.state =  np.append(np.array(self.covs), [self.data[tech].values.tolist() for tech in self.tech_indicator_list ], axis=0)
        # print("state:",self.state.shape)
        self.terminal = False     
        self.turbulence_threshold = turbulence_threshold        
        # initalize state: inital portfolio return + individual stock return + individual weights
        self.portfolio_value = self.initial_amount
    
        # memorize portfolio value each step
        self.asset_memory = [self.initial_amount]
        # memorize portfolio return each step
        self.portfolio_return_memory = [0]
        self.actions_memory=[self.initial_weights]
        self.date_memory=[self.data.date.unique()[0]]
             
    def step(self, actions):
        # print()
        self.terminal = self.day >= len(self.df.index.unique())-self.stock_dim
        if self.terminal:
            """
            添加需要重新进行测试
            """
            # weights = self.softmax_normalization(actions)
            # print("weights:",weights)
            # self.actions_memory.append(weights)
            # file_path = 'C:/AAAAA-Experiment/Experiment_paper_1/American/WeightEndOfDDate.txt'
            # with open(file_path, 'a') as file:
            #     file.write(f"{self.date_memory[-1]}:{self.actions_memory[-1]}\n")

            # df = pd.DataFrame(self.portfolio_return_memory)
            # df.columns = ['daily_return']
            # plt.plot(df.daily_return.cumsum(),'r')
            # plt.savefig('result/cumulative_reward.png')
            # plt.close()
            
            # plt.plot(self.portfolio_return_memory,'r')
            # plt.savefig('result/rewards.png')
            # plt.close()

            print("=================================")
            print("begin_total_asset:{}".format(self.asset_memory[0]))           
            print("end_total_asset:{}".format(self.portfolio_value))

            df_daily_return = pd.DataFrame(self.portfolio_return_memory)
            df_daily_return.columns = ['daily_return']
            if df_daily_return['daily_return'].std() !=0:
              sharpe = (252**0.5)*df_daily_return['daily_return'].mean()/ \
                       df_daily_return['daily_return'].std()
              print("Sharpe: ",sharpe)
            print("=================================")
            # return self.state, self.reward, self.terminal, {}
        
        else:
            weights = self.softmax_normalization(actions)
            # print("weights:",weights)
            # self.actions_memory.append(weights)
            last_day_memory = self.data
            #load next state
            self.day += self.stock_dim
            self.data = self.df.loc[self.day:self.day+self.stock_dim-1,:]
            # print("self.data",self.data)
            self.covs = self.data['cov_list'].values[0]
            self.covs = self.covs.replace("[", "").replace("]", "")
            self.covs = np.fromstring(self.covs, sep=' ')
            num_dim = int(self.stock_dim)
            self.covs = np.reshape(self.covs,[num_dim,-1])
            self.state = np.append(np.array(self.covs), [self.data[tech].values.tolist() for tech in self.tech_indicator_list ], axis=0)
            # for i in range(len(weights)):
            #     portfolio_num = int ((weights[i] * self.portfolio_value) / last_day_memory.close.values[i])
            #     # print("weights:",weights[i],"last_day_memory.close.values[i]",last_day_memory.close.values[i])
            #     # print("portfolio_num",portfolio_num)
            #     new_portfolio_value += portfolio_num * (self.data.close.values[i] - last_day_memory.close.values[i])
            #     print("new_portfolio_value:",new_portfolio_value)
            # portfolio_return = new_portfolio_value / self.portfolio_value
            # portfolio_return = sum(((self.data.close.values / last_day_memory.close.values)-1)*weights)
            # print("self.data.close.values:",self.data.close.values)
            # update portfolio value
            # portfolio_return = (int (portfolio_return * 10000)) / 10000
            y = self.data.close.values / last_day_memory.close.values
            portfolio_return = sum((y -1)*weights)
            # weights = np.multiply(weights, y) / np.dot(weights, y)
            # weights = self.softmax_normalization(weights)
            # portfolio_return = sum((y -1)*weights)
            self.actions_memory.append(weights)
            # print("portfolio_return:",portfolio_return)

            new_portfolio_value = self.portfolio_value * (1 + portfolio_return)
            self.portfolio_value = new_portfolio_value
            # save into memory
            self.portfolio_return_memory.append(portfolio_return)
            self.date_memory.append(self.data.date.unique()[0])
            self.asset_memory.append(new_portfolio_value)
            # the reward is the new portfolio value or end portfolio value
            self.reward = portfolio_return
            # if portfolio_return > 0:
            #     self.reward = 1
            # else:
            #     self.reward = -1
            # self.reward = self.reward*self.reward_scaling
            # print("day：",int(self.day/self.stock_dim),"Step_reward: ", self.reward,"portfolio_return:",new_portfolio_value)

        return self.state, self.reward, self.terminal, {}

        # return self.state, self.reward, self.terminal, {}

    def reset(self):
        self.asset_memory = [self.initial_amount]
        self.day = 0
        self.data = self.df.loc[self.day:self.day+self.stock_dim-1,:]
        self.covs = self.data['cov_list'].values[0]
        self.covs = self.covs.replace("[", "").replace("]", "")
        self.covs = np.fromstring(self.covs, sep=' ')
        num_dim = int(self.stock_dim)
        self.covs = np.reshape(self.covs,[num_dim,-1])
        self.state =  np.append(np.array(self.covs), [self.data[tech].values.tolist() for tech in self.tech_indicator_list ], axis=0)
        self.portfolio_value = self.initial_amount
        self.terminal = False 
        self.portfolio_return_memory = [0]
        self.actions_memory=[self.initial_weights] 
        self.date_memory=[self.data.date.unique()[0]] 
        return self.state
    
    def render(self, mode='human'):
        return self.state
        
    def softmax_normalization(self, actions):
        numerator = np.exp(actions)
        denominator = np.sum(np.exp(actions))
        softmax_output = numerator/denominator
        # softmax_output_rounded = np.round(softmax_output, decimals=2)
        return softmax_output

    def save_asset_memory(self):
        date_list = self.date_memory
        portfolio_return = self.portfolio_return_memory
        df_account_value = pd.DataFrame({'date':date_list,'daily_return':portfolio_return})
        return df_account_value

    def save_action_memory(self):
        # date and close price length must match actions length
        date_list = self.date_memory
        df_date = pd.DataFrame(date_list)      
        df_date.columns = ['date']
        action_list = self.actions_memory
        df_actions = pd.DataFrame(action_list)
        df_actions.columns = self.data.tic.values
        df_actions.index = df_date.date
        df_actions = pd.DataFrame({'date':date_list,'actions':action_list})
        return df_actions
    
    def initial_weights(self, data_frame):
        # Get data frame of close prices 
        # Reset the Index to tic and date
        df_prices = data_frame.copy()
        df_prices = df_prices.reset_index().set_index(['tic', 'date']).sort_index()
        tic_list = list(set([i for i,j in df_prices.index]))
        
        # Get all the Close Prices
        df_close = pd.DataFrame()
        for ticker in tic_list:
            series = df_prices.xs(ticker).close
            df_close[ticker] = series
        """
        mu = expected_returns.mean_historical_return(df_close)
        Sigma = risk_models.sample_cov(df_close)
        ef = EfficientFrontier(mu,Sigma, weight_bounds=(0.01, 1))
        """
        raw_weights = ef.max_sharpe()
        initial_weights = [j for i,j in raw_weights.items()]
        
        return initial_weights

    def _seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def get_sb_env(self):
        e = DummyVecEnv([lambda: self])
        obs = e.reset()
        return e,obs